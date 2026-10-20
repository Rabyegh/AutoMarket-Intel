variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "eu-west-1"
}

variable "aws_account_id" {
  description = "AWS account ID (12-digit string). Required for OIDC trust policy."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit numeric string."
  }
}

variable "s3_raw_bucket" {
  description = "Name of the S3 bucket for raw used-car data. Must be globally unique."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9\\-]{1,61}[a-z0-9]$", var.s3_raw_bucket))
    error_message = "s3_raw_bucket must be a valid S3 bucket name (lowercase, 3-63 chars)."
  }
}

variable "environment" {
  description = "Deployment environment tag (e.g. dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "github_repo" {
  description = "GitHub repository in 'owner/repo' format for OIDC trust restriction."
  type        = string
  default     = "Rabyegh/AutoMarket-Intel"
}

variable "snowflake_iam_user_arn" {
  description = <<-EOT
    AWS IAM user ARN that Snowflake uses to assume the reader role.
    Obtain this from: DESC INTEGRATION S3_INT_AUTOMARKET;
    → STORAGE_AWS_IAM_USER_ARN column.
    Leave as placeholder until Snowflake storage integration is created.
  EOT
  type        = string
  default     = "arn:aws:iam::PLACEHOLDER:user/snowflake"
}

variable "snowflake_external_id" {
  description = <<-EOT
    External ID for the Snowflake → AWS trust relationship.
    Obtain this from: DESC INTEGRATION S3_INT_AUTOMARKET;
    → STORAGE_AWS_EXTERNAL_ID column.
    Leave as placeholder until Snowflake storage integration is created.
  EOT
  type        = string
  default     = "PLACEHOLDER_EXTERNAL_ID"
}
