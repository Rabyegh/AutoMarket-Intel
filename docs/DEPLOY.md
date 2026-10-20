# Deploy Guide — AutoMarket Intel

This guide covers both the **local DuckDB pipeline** (zero cloud credentials) and the
**cloud pipeline** (AWS S3 → Snowflake → dbt Snowflake target).

---

## Prerequisites

### Local pipeline (no cloud required)

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | python.org |
| uv | latest | `pip install uv` |

### Cloud pipeline (additional requirements)

| Tool | Version | Notes |
|---|---|---|
| AWS CLI | v2 | Only needed for manual S3 operations; CI uses OIDC |
| Terraform | ≥ 1.6 | For provisioning S3 bucket + IAM roles |
| Snowflake account | trial or paid | X-Small warehouse — estimated < $5/month for weekly runs |

---

## Part A — Local Pipeline

```bash
# 1. Clone and install
git clone https://github.com/Rabyegh/AutoMarket-Intel.git
cd AutoMarket-Intel
uv venv .venv --python 3.11
uv pip install dbt-core dbt-duckdb ruff pytest pandas pyarrow duckdb pydantic rich typer

# 2. Run ingestion (CSV → DuckDB)
uv run python -m automarket.cli ingest \
  --data-dir data/raw/used_cars \
  --duckdb-path data/warehouse.duckdb

# 3. Build dbt models (DuckDB target)
$env:DUCKDB_PATH=(Resolve-Path "data\warehouse.duckdb").Path  # Windows PowerShell
.venv/Scripts/python.exe -c "from dbt.cli.main import cli; cli()" \
  -- build --project-dir dbt --profiles-dir dbt --target duckdb

# 4. View report
uv run python -m automarket.cli report
```

Run all tests:
```bash
uv run pytest tests/ -v
```

---

## Part B — Cloud Pipeline

The cloud path is:

```
data/raw/used_cars/ (CSV) → upload-s3 → S3 normalized Parquet
    → load-snowflake → Snowflake RAW.RAW_USED_CAR_LISTINGS
    → dbt build --target snowflake → STAGING / CORE / MARTS
```

### Step 1: AWS Infrastructure (Terraform)

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set aws_account_id, s3_raw_bucket, environment

terraform init
terraform plan -var-file=terraform.tfvars   # review before applying
# Apply only when you are satisfied with the plan:
# terraform apply -var-file=terraform.tfvars
```

Key Terraform outputs you will need:
- `snowflake_reader_role_arn` — use as `STORAGE_AWS_ROLE_ARN` in Snowflake setup
- `github_actions_role_arn` — set as `AWS_OIDC_ROLE_ARN` GitHub secret

### Step 2: Snowflake bootstrap

> Run with `ACCOUNTADMIN` or (`SYSADMIN` + `SECURITYADMIN`).

```bash
# Generate RSA key pair for service account (key-pair auth, no password)
openssl genrsa -out rsa_key.pem 2048
openssl rsa -in rsa_key.pem -pubout -out rsa_key_pub.pem
# rsa_key.pem  → store at SNOWFLAKE_PRIVATE_KEY_PATH (never commit this file)
# rsa_key_pub.pem → public key, needed in Step 2c below

# 2a. Run the idempotent bootstrap SQL
snowsql -f infra/snowflake/setup.sql
```

**2b. Create the Storage Integration** (edit setup.sql to uncomment the block, then fill in):
```sql
-- Replace <YOUR_AWS_IAM_ROLE_ARN> with the terraform output: snowflake_reader_role_arn
-- Replace <YOUR_S3_BUCKET_NAME> with your actual bucket name
CREATE STORAGE INTEGRATION IF NOT EXISTS S3_INT_AUTOMARKET
    TYPE = EXTERNAL_STAGE
    STORAGE_PROVIDER = 'S3'
    ENABLED = TRUE
    STORAGE_AWS_ROLE_ARN = '<terraform output: snowflake_reader_role_arn>'
    STORAGE_ALLOWED_LOCATIONS = ('s3://<bucket>/raw/used_cars/')
    COMMENT = 'AutoMarket Intel Parquet loader';

GRANT USAGE ON INTEGRATION S3_INT_AUTOMARKET TO ROLE AUTOMARKET_ROLE;
```

**2c. Get Snowflake's IAM identity for the trust policy:**
```sql
DESC INTEGRATION S3_INT_AUTOMARKET;
```
Note two values from the output:
- `STORAGE_AWS_IAM_USER_ARN` — add as `Principal` in the AWS IAM trust policy
- `STORAGE_AWS_EXTERNAL_ID` — add as `sts:ExternalId` condition

Update `infra/terraform/terraform.tfvars` with these values:
```
snowflake_iam_user_arn = "<STORAGE_AWS_IAM_USER_ARN>"
snowflake_external_id  = "<STORAGE_AWS_EXTERNAL_ID>"
```
Then: `terraform apply -var-file=terraform.tfvars`

**2d. Set the service account public key:**
```sql
ALTER USER AUTOMARKET_SVC SET RSA_PUBLIC_KEY='<contents of rsa_key_pub.pem, without BEGIN/END headers>';
```

**2e. Create File Format, Stage, and S3 bucket URL** (uncomment blocks in setup.sql):
```sql
CREATE OR REPLACE FILE FORMAT AUTOMARKET_DB.RAW.PARQUET_FORMAT_AUTOMARKET
    TYPE = 'PARQUET' SNAPPY_COMPRESSION = TRUE BINARY_AS_TEXT = FALSE;

CREATE OR REPLACE STAGE AUTOMARKET_DB.RAW.S3_STAGE_AUTOMARKET
    STORAGE_INTEGRATION = S3_INT_AUTOMARKET
    URL = 's3://<bucket>/raw/used_cars/'
    FILE_FORMAT = AUTOMARKET_DB.RAW.PARQUET_FORMAT_AUTOMARKET;
```

### Step 3: Environment setup

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
# Edit .env — do NOT commit this file
```

### Step 4: Install cloud dependencies

```bash
uv pip install boto3 snowflake-connector-python dbt-snowflake cryptography
```

### Step 5: Run cloud pipeline

```bash
# Set a run ID (reuse to skip re-loading already-loaded files)
export RUN_ID="$(date +%Y%m%d)-001"

# Upload CSVs + normalized Parquet to S3
uv run python -m automarket.cli upload-s3 \
  --data-dir data/raw/used_cars \
  --run-id "$RUN_ID"

# Load Parquet from S3 into Snowflake RAW (COPY INTO)
uv run python -m automarket.cli load-snowflake "$RUN_ID"

# Run dbt transformations against Snowflake
$env:SNOWFLAKE_DATABASE="AUTOMARKET_DB"  # Windows
.venv/Scripts/python.exe -c "from dbt.cli.main import cli; cli()" \
  -- build --project-dir dbt --profiles-dir dbt --target snowflake
```

Or use Make:
```bash
make cloud-pipeline RUN_ID=2026-10-20-001
```

---

## GitHub Actions Secrets

Configure these in **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `AWS_OIDC_ROLE_ARN` | `github_actions_role_arn` from Terraform output |
| `AWS_DEFAULT_REGION` | e.g. `eu-west-1` |
| `S3_RAW_BUCKET` | Your S3 bucket name |
| `SNOWFLAKE_ACCOUNT` | e.g. `xy12345.eu-west-1` |
| `SNOWFLAKE_USER` | `AUTOMARKET_SVC` |
| `SNOWFLAKE_PRIVATE_KEY` | Full PEM content of `rsa_key.pem` (the private key) |
| `SNOWFLAKE_DATABASE` | `AUTOMARKET_DB` |
| `SNOWFLAKE_WAREHOUSE` | `AUTOMARKET_WH` |
| `SNOWFLAKE_ROLE` | `AUTOMARKET_ROLE` |

> **Security:** The private key is written to `/tmp/snowflake_rsa_key.pem` during the
> workflow and deleted in the `always()` cleanup step. It is never printed or logged.

---

## Rollback

Raw CSV files are the source of truth. To rebuild from scratch:

```bash
# Local DuckDB
make clean && make demo

# Snowflake (full refresh)
uv run python -m automarket.cli load-snowflake "$RUN_ID"
.venv/Scripts/python.exe -c "from dbt.cli.main import cli; cli()" \
  -- build --full-refresh --project-dir dbt --profiles-dir dbt --target snowflake
```

---

## Cost estimate

| Resource | Configuration | Estimated cost |
|---|---|---|
| S3 bucket | ~500 MB raw data, versioning on | < $0.10/month |
| Snowflake compute | X-Small, auto-suspend 60s | < $2 per weekly run |
| Snowflake storage | ~500 MB Parquet | < $0.50/month |

> Always verify current pricing at aws.amazon.com/pricing and snowflake.com/pricing.
> The resource monitor (`AUTOMARKET_MONITOR`, 5-credit quota) provides a hard monthly cap.
