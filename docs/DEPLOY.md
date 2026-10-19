# Deploy Guide (P1)

_Complete this guide as part of tasks E8-05 and E8-06._

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| uv | latest | `pip install uv` |
| AWS CLI | v2 | For S3 sync |
| Snowflake account | trial or paid | X-Small warehouse |

## Environment Variables (Secrets)

Copy `.env.example` to `.env` and set all values. For CI, add them as **GitHub repository secrets**:

| Secret | Description |
|---|---|
| `SNOWFLAKE_ACCOUNT` | Account identifier (e.g., `xy12345.eu-west-1`) |
| `SNOWFLAKE_USER` | Service account username (`VINPIPE_SVC`) |
| `SNOWFLAKE_PRIVATE_KEY` | PEM content of the RSA private key |
| `SNOWFLAKE_DATABASE` | `VINPIPE_DB` |
| `SNOWFLAKE_WAREHOUSE` | `VINPIPE_WH` |
| `SNOWFLAKE_ROLE` | `VINPIPE_ROLE` |
| `AWS_OIDC_ROLE_ARN` | ARN of the OIDC role for CI |
| `AWS_DEFAULT_REGION` | e.g., `eu-west-1` |
| `S3_RAW_BUCKET` | Bucket name for raw archive |

## Bootstrap Steps

```bash
# 1. Clone and install
git clone https://github.com/Rabyegh/AutoMarket-Intel.git
cd automarket-intel
cp .env.example .env  # fill in values
uv sync

# 2. Snowflake (run once with ACCOUNTADMIN)
snowsql -f infra/snowflake/setup.sql

# 3. Set key-pair auth for VINPIPE_SVC
#    Generate key: openssl genrsa -out vinpipe_rsa.pem 2048
#    Extract public: openssl rsa -in vinpipe_rsa.pem -pubout -out vinpipe_rsa_pub.pem
#    Set in Snowflake: ALTER USER VINPIPE_SVC SET RSA_PUBLIC_KEY='<contents>';

# 4. S3 bucket
aws s3api create-bucket --bucket $S3_RAW_BUCKET --region $AWS_DEFAULT_REGION \
    --create-bucket-configuration LocationConstraint=$AWS_DEFAULT_REGION
aws s3api put-bucket-versioning --bucket $S3_RAW_BUCKET \
    --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket $S3_RAW_BUCKET \
    --public-access-block-configuration BlockPublicAcls=true,...

# 5. Run end-to-end
make demo           # local DuckDB
make dbt-build      # confirm local green
vinpipe sync-s3     # push raw to S3
vinpipe load --env snowflake
cd dbt && dbt build --target snowflake
```

## Rollback

Raw files are the source of truth. To rebuild the warehouse from scratch:

```bash
make clean
make demo          # rebuilds DuckDB from raw
# or for Snowflake:
vinpipe load --env snowflake
cd dbt && dbt build --target snowflake --full-refresh
```
