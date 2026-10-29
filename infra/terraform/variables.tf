variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "scribbleai"
}

variable "region" {
  description = "AWS region. ap-south-1 (Mumbai) is closest to Manipal; the synopsis used us-east-1."
  type        = string
  default     = "ap-south-1"
}

variable "alert_email" {
  description = "Address that receives deploy notifications, CloudWatch alarms and budget alerts (you must confirm the SNS subscription e-mail)."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/name, e.g. DarthVader69oss/scribbleai-cloud."
  type        = string
}

variable "create_github_oidc_provider" {
  description = "Set false if this AWS account already has the token.actions.githubusercontent.com OIDC provider."
  type        = bool
  default     = true
}

variable "instance_type" {
  description = "EC2 type for the web front end. Use the one marked 'Free tier eligible' for your account (t3.micro on new accounts, t2.micro on old ones)."
  type        = string
  default     = "t3.micro"
}

variable "allowed_cidr" {
  description = "Who may open the demo page. 0.0.0.0/0 = anyone on the internet; use your campus range to lock it down."
  type        = string
  default     = "0.0.0.0/0"
}

variable "model_ids" {
  description = "Model folders expected under s3://<bucket>/models/. The first one is the default."
  type        = list(string)
  default     = ["finetuned", "base"]
}

variable "lambda_memory_mb" {
  description = "Lambda memory. CPU share scales with memory, so more memory = faster inference."
  type        = number
  default     = 2048
}

variable "lambda_timeout_s" {
  description = "Lambda timeout. API Gateway itself gives up after 29 s."
  type        = number
  default     = 29
}

variable "image_tag" {
  description = "Tag used the first time the function is created. After that GitHub Actions updates the image and Terraform ignores it."
  type        = string
  default     = "latest"
}

variable "enable_warmup" {
  description = "Ping the function every 5 minutes so the first stroke in front of a faculty member is not a cold start."
  type        = bool
  default     = true
}

variable "api_rate_limit" {
  description = "API Gateway steady-state requests per second (the protection against a runaway client)."
  type        = number
  default     = 10
}

variable "api_burst_limit" {
  description = "API Gateway burst size."
  type        = number
  default     = 20
}

variable "api_daily_quota" {
  description = "Maximum API calls per day for the demo API key."
  type        = number
  default     = 5000
}

variable "monthly_budget_usd" {
  description = "AWS Budgets alert threshold (synopsis: 5 USD)."
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the Lambda function."
  type        = number
  default     = 14
}
