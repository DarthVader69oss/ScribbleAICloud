# ------------------------------------------------------------------ Lambda (container image)
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}-inference"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "inference" {
  function_name = "${local.name}-inference"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.inference.repository_url}:${var.image_tag}"
  architectures = ["x86_64"]
  memory_size   = var.lambda_memory_mb
  timeout       = var.lambda_timeout_s

  environment {
    variables = {
      MODEL_BUCKET     = aws_s3_bucket.artifacts.id
      MODEL_PREFIX     = "models"
      MODEL_IDS        = join(",", var.model_ids)
      DEFAULT_MODEL    = var.model_ids[0]
      PREDICTION_TABLE = aws_dynamodb_table.predictions.name
      LOG_TTL_DAYS     = "30"
      TORCH_THREADS    = "2"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy_attachment.lambda_logs]

  lifecycle {
    ignore_changes = [image_uri] # GitHub Actions owns the image; `terraform apply` must not roll it back
  }
}

# Keep one execution environment warm (see handler.py: an event without httpMethod just loads the model).
resource "aws_cloudwatch_event_rule" "warm" {
  count               = var.enable_warmup ? 1 : 0
  name                = "${local.name}-keep-warm"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "warm" {
  count = var.enable_warmup ? 1 : 0
  rule  = aws_cloudwatch_event_rule.warm[0].name
  arn   = aws_lambda_function.inference.arn
  input = jsonencode({ warmup = true })
}

resource "aws_lambda_permission" "events" {
  count         = var.enable_warmup ? 1 : 0
  statement_id  = "AllowEventBridgeWarmup"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.inference.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.warm[0].arn
}

# ------------------------------------------------------------------ API Gateway (REST API, API key + usage plan)
locals {
  routes = {
    predict = "POST"
    info    = "GET"
    stats   = "GET"
    health  = "GET"
  }
}

resource "aws_api_gateway_rest_api" "api" {
  name        = "${local.name}-api"
  description = "ScribbleAI handwriting recognition: POST /predict, GET /info /stats /health"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "route" {
  for_each    = local.routes
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = each.key
}

resource "aws_api_gateway_method" "route" {
  for_each         = local.routes
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.route[each.key].id
  http_method      = each.value
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "route" {
  for_each                = local.routes
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.route[each.key].id
  http_method             = aws_api_gateway_method.route[each.key].http_method
  integration_http_method = "POST" # API Gateway -> Lambda is always POST
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.inference.invoke_arn
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.inference.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "api" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_resource.route,
      aws_api_gateway_method.route,
      aws_api_gateway_integration.route,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  deployment_id = aws_api_gateway_deployment.api.id
  stage_name    = "prod"
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  stage_name  = aws_api_gateway_stage.prod.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true # per-route Count / Latency / 4XX / 5XX in CloudWatch
    throttling_rate_limit  = var.api_rate_limit
    throttling_burst_limit = var.api_burst_limit
  }
}

resource "aws_api_gateway_api_key" "demo" {
  name = "${local.name}-demo-key"
}

resource "aws_api_gateway_usage_plan" "demo" {
  name = "${local.name}-demo-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }

  throttle_settings {
    rate_limit  = var.api_rate_limit
    burst_limit = var.api_burst_limit
  }

  quota_settings {
    limit  = var.api_daily_quota
    period = "DAY"
  }
}

resource "aws_api_gateway_usage_plan_key" "demo" {
  key_id        = aws_api_gateway_api_key.demo.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.demo.id
}
