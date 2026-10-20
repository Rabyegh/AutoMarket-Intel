output "s3_bucket_name" {
  description = "Name of the S3 bucket created for raw data."
  value       = aws_s3_bucket.raw.bucket
}

output "s3_bucket_arn" {
  description = "ARN of the S3 raw data bucket."
  value       = aws_s3_bucket.raw.arn
}

output "snowflake_reader_role_arn" {
  description = <<-EOT
    ARN of the IAM role Snowflake assumes to read from S3.
    Use this value as STORAGE_AWS_ROLE_ARN in infra/snowflake/setup.sql.
  EOT
  value = aws_iam_role.snowflake_reader.arn
}

output "github_actions_role_arn" {
  description = <<-EOT
    ARN of the GitHub Actions OIDC role.
    Use this as the AWS_OIDC_ROLE_ARN GitHub repository secret.
  EOT
  value = aws_iam_role.github_actions.arn
}
