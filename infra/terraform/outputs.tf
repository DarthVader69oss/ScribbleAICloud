output "demo_url" {
  description = "Open this on the laptop AND the tablet."
  value       = "http://${aws_eip.web.public_ip}/"
}

output "dashboard_url" {
  description = "Live prediction statistics read back from DynamoDB."
  value       = "http://${aws_eip.web.public_ip}/dashboard.html"
}

output "api_invoke_url" {
  description = "API Gateway endpoint (needs the x-api-key header)."
  value       = aws_api_gateway_stage.prod.invoke_url
}

output "api_key" {
  description = "For Postman. Show with: terraform output -raw api_key"
  value       = aws_api_gateway_api_key.demo.value
  sensitive   = true
}

output "model_upload_prefix" {
  description = "Where scripts/upload_models.sh puts the exported models."
  value       = "s3://${aws_s3_bucket.artifacts.id}/models/"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.inference.repository_url
}

output "cloudwatch_dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "github_actions_variables" {
  description = "Paste each line into GitHub > Settings > Secrets and variables > Actions > Variables."
  value       = <<-EOT
    AWS_REGION=${var.region}
    AWS_ROLE_ARN=${aws_iam_role.github.arn}
    ECR_REPOSITORY=${aws_ecr_repository.inference.name}
    LAMBDA_FUNCTION=${aws_lambda_function.inference.function_name}
    S3_BUCKET=${aws_s3_bucket.artifacts.id}
    EC2_INSTANCE_ID=${aws_instance.web.id}
    SNS_TOPIC_ARN=${aws_sns_topic.alerts.arn}
    DEMO_URL=http://${aws_eip.web.public_ip}
  EOT
}

output "region" {
  value = var.region
}

output "lambda_function_name" {
  value = aws_lambda_function.inference.function_name
}
