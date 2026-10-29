# Least privilege: each principal gets only the actions it uses, on only the resources it touches.

# ------------------------------------------------------------------ Lambda execution role
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_access" {
  statement {
    sid       = "ReadModelArtifacts"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/models/*"]
  }

  statement {
    sid       = "ListModelPrefix"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["models/*"]
    }
  }

  statement {
    sid       = "PredictionLog"
    actions   = ["dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.predictions.arn]
  }
}

resource "aws_iam_role_policy" "lambda_access" {
  name   = "model-and-log-access"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_access.json
}

# ------------------------------------------------------------------ EC2 instance role (web front end)
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "web" {
  name               = "${local.name}-web"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "web_ssm" {
  role       = aws_iam_role.web.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" # Session Manager + Run Command, so no SSH port
}

data "aws_iam_policy_document" "web_access" {
  statement {
    sid     = "ReadWebFiles"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/ui/*",
      "${aws_s3_bucket.artifacts.arn}/deploy/*",
    ]
  }

  statement {
    sid       = "ListWebFiles"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["ui/*", "deploy/*", "ui", "deploy"]
    }
  }

  statement {
    sid       = "ReadApiSettings"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.api_url.arn, aws_ssm_parameter.api_key.arn]
  }
}

resource "aws_iam_role_policy" "web_access" {
  name   = "web-files-and-api-settings"
  role   = aws_iam_role.web.id
  policy = data.aws_iam_policy_document.web_access.json
}

resource "aws_iam_instance_profile" "web" {
  name = "${local.name}-web"
  role = aws_iam_role.web.name
}

# ------------------------------------------------------------------ GitHub Actions (OIDC: no long-lived AWS keys in GitHub)
resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_github_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"] # only the main branch of this one repo
    }
  }
}

resource "aws_iam_role" "github" {
  name               = "${local.name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.inference.arn]
  }

  statement {
    sid = "LambdaRollout"
    actions = [
      "lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration",
      "lambda:InvokeFunction",
    ]
    resources = [aws_lambda_function.inference.arn]
  }

  statement {
    sid       = "PublishWebFiles"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/ui/*", "${aws_s3_bucket.artifacts.arn}/deploy/*"]
  }

  statement {
    sid       = "ListWebFiles"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid     = "RefreshWebServer"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ssm:${var.region}::document/AWS-RunShellScript",
      aws_instance.web.arn,
    ]
  }

  statement {
    sid       = "ReadCommandResult"
    actions   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    resources = ["*"]
  }

  statement {
    sid       = "NotifyTeam"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "deploy"
  role   = aws_iam_role.github.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
