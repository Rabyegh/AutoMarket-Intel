/**
 * AutoMarket Intel — AWS Infrastructure (Terraform)
 * ==================================================
 * Resources created by this module:
 *   - S3 bucket for raw data archive (versioning, SSE, public-access blocked)
 *   - IAM role for Snowflake external-stage access (least-privilege, S3 read-only)
 *   - IAM role for GitHub Actions OIDC (S3 write, no long-lived keys)
 *   - IAM policies attached to each role
 *
 * IMPORTANT: Do NOT run `terraform apply` without reviewing the plan.
 * This file does not create Snowflake resources; those are in infra/snowflake/setup.sql.
 *
 * Usage:
 *   cd infra/terraform
 *   cp terraform.tfvars.example terraform.tfvars   # fill in values
 *   terraform init
 *   terraform plan -var-file=terraform.tfvars      # review before applying
 *   # terraform apply -var-file=terraform.tfvars   # only after review
 */

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ── Local values ──────────────────────────────────────────────────────────────

locals {
  bucket_name = var.s3_raw_bucket
  common_tags = {
    Project     = "automarket-intel"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── S3 bucket ─────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "raw" {
  bucket = local.bucket_name
  tags   = local.common_tags
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── IAM role for Snowflake external stage (read-only S3) ─────────────────────
#
# Snowflake requires a specific trust relationship format.
# After creating this role, execute in Snowflake:
#   DESC INTEGRATION S3_INT_AUTOMARKET;
# Then update the trust policy with STORAGE_AWS_IAM_USER_ARN and
# STORAGE_AWS_EXTERNAL_ID from that output.
# See docs/DEPLOY.md for the full trust-relationship workflow.

resource "aws_iam_role" "snowflake_reader" {
  name        = "automarket-snowflake-reader"
  description = "Allows Snowflake to read Parquet files from the AutoMarket raw bucket"
  tags        = local.common_tags

  # Trust relationship — Snowflake's IAM user will assume this role.
  # Replace STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID with
  # the values from: DESC INTEGRATION S3_INT_AUTOMARKET;
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = var.snowflake_iam_user_arn  # from DESC INTEGRATION output
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.snowflake_external_id  # from DESC INTEGRATION output
          }
        }
      }
    ]
  })
}

resource "aws_iam_policy" "snowflake_s3_read" {
  name        = "automarket-snowflake-s3-read"
  description = "Least-privilege S3 read for Snowflake external stage"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.raw.arn,
          "${aws_s3_bucket.raw.arn}/raw/used_cars/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "snowflake_reader" {
  role       = aws_iam_role.snowflake_reader.name
  policy_arn = aws_iam_policy.snowflake_s3_read.arn
}

# ── IAM role for GitHub Actions OIDC ─────────────────────────────────────────
# Allows GitHub Actions workflows to assume this role without long-lived keys.
# OIDC provider must already exist in the AWS account.

resource "aws_iam_role" "github_actions" {
  name        = "automarket-github-actions"
  description = "GitHub Actions OIDC role for AutoMarket Intel CI/CD"
  tags        = local.common_tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            # Restrict to the specific repository and branch
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/main"
          }
        }
      }
    ]
  })
}

resource "aws_iam_policy" "github_actions_s3" {
  name        = "automarket-github-actions-s3"
  description = "S3 write permissions for GitHub Actions CI/CD uploads"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.raw.arn,
          "${aws_s3_bucket.raw.arn}/raw/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_actions" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions_s3.arn
}
