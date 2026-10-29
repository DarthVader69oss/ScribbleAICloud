# ------------------------------------------------------------------ S3: model artifacts + UI files
resource "aws_s3_bucket" "artifacts" {
  bucket        = "${local.name}-artifacts-${data.aws_caller_identity.me.account_id}"
  force_destroy = true # lets `terraform destroy` empty the bucket for you
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled" # every model upload gets a VersionId, which the API returns with each prediction
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 60
    }
  }

  depends_on = [aws_s3_bucket_versioning.artifacts]
}

# First copy of the web files; later updates come from GitHub Actions (aws s3 sync).
resource "aws_s3_object" "ui" {
  for_each = fileset("${local.repo_root}/ui", "*")
  bucket   = aws_s3_bucket.artifacts.id
  key      = "ui/${each.value}"
  source   = "${local.repo_root}/ui/${each.value}"
  etag     = filemd5("${local.repo_root}/ui/${each.value}")
}

resource "aws_s3_object" "deploy" {
  for_each = fileset("${local.repo_root}/deploy", "*")
  bucket   = aws_s3_bucket.artifacts.id
  key      = "deploy/${each.value}"
  source   = "${local.repo_root}/deploy/${each.value}"
  etag     = filemd5("${local.repo_root}/deploy/${each.value}")
}

# ------------------------------------------------------------------ ECR: Lambda container image
resource "aws_ecr_repository" "inference" {
  name                 = "${local.name}-inference"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "inference" {
  repository = aws_ecr_repository.inference.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the 5 newest images (storage is billed per GB-month)"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

# ------------------------------------------------------------------ DynamoDB: one row per prediction
resource "aws_dynamodb_table" "predictions" {
  name         = "${local.name}-predictions"
  billing_mode = "PAY_PER_REQUEST" # nothing to size; a demo costs cents
  hash_key     = "day"             # partition = UTC date, so "today's predictions" is a single cheap Query
  range_key    = "sk"              # sort key = ISO timestamp + request id, newest-first with ScanIndexForward=false

  attribute {
    name = "day"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at" # rows delete themselves after 30 days: bounded storage, bounded privacy exposure
    enabled        = true
  }
}

# ------------------------------------------------------------------ SSM Parameter Store: values the web server needs
resource "aws_ssm_parameter" "api_url" {
  name  = "/${local.name}/api_url"
  type  = "String"
  value = aws_api_gateway_stage.prod.invoke_url
}

resource "aws_ssm_parameter" "api_key" {
  name  = "/${local.name}/api_key"
  type  = "SecureString"
  value = aws_api_gateway_api_key.demo.value
}
