-- ============================================================================
-- AutoMarket Intel — Snowflake Bootstrap
-- ============================================================================
-- Run once with an ACCOUNTADMIN (or SYSADMIN + SECURITYADMIN) role.
-- This script is idempotent (CREATE … IF NOT EXISTS everywhere).
--
-- IMPORTANT: Three values in this script require post-creation coordination
-- with AWS before the S3 storage integration will function:
--
--   1. STORAGE_AWS_ROLE_ARN  (set in step "Storage Integration" below)
--      → Obtain the ARN of the AWS IAM role you create for Snowflake access.
--      → See docs/DEPLOY.md "AWS trust relationship" for the exact policy.
--
--   2. RSA_PUBLIC_KEY for AUTOMARKET_SVC  (set at the bottom of this file)
--      → Run: openssl genrsa -out rsa_key.pem 2048
--      → Run: openssl rsa -in rsa_key.pem -pubout -out rsa_key_pub.pem
--      → Paste the PUBLIC key content into the ALTER USER statement below.
--      → Store the PRIVATE key at the path in SNOWFLAKE_PRIVATE_KEY_PATH.
--
--   3. After running CREATE STORAGE INTEGRATION, execute:
--         DESC INTEGRATION S3_INT_AUTOMARKET;
--      Note the STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID values.
--      Add them to your AWS IAM role's trust policy (see docs/DEPLOY.md).
--
-- Never put private keys, passwords, or access tokens in this file.
-- Never commit this file with real ARNs unless using placeholder values.
-- ============================================================================

-- ── Roles ─────────────────────────────────────────────────────────────────────
CREATE ROLE IF NOT EXISTS AUTOMARKET_ROLE;
GRANT ROLE AUTOMARKET_ROLE TO ROLE SYSADMIN;

-- ── Virtual warehouse ─────────────────────────────────────────────────────────
CREATE WAREHOUSE IF NOT EXISTS AUTOMARKET_WH
    WAREHOUSE_SIZE = 'X-SMALL'
    AUTO_SUSPEND   = 60          -- suspend after 60 s of inactivity
    AUTO_RESUME    = TRUE
    COMMENT        = 'AutoMarket Intel — used-car pricing pipeline. X-Small for batch.';

GRANT USAGE ON WAREHOUSE AUTOMARKET_WH TO ROLE AUTOMARKET_ROLE;

-- ── Resource monitor (credit cap) ─────────────────────────────────────────────
-- Adjust CREDIT_QUOTA to your comfort level before running.
-- This prevents unexpected charges from runaway queries.
CREATE RESOURCE MONITOR IF NOT EXISTS AUTOMARKET_MONITOR
    WITH CREDIT_QUOTA = 5          -- 5 credits/month hard cap (adjust as needed)
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
        ON 80 PERCENT DO NOTIFY
        ON 100 PERCENT DO SUSPEND;

ALTER WAREHOUSE AUTOMARKET_WH SET RESOURCE_MONITOR = AUTOMARKET_MONITOR;

-- ── Database ──────────────────────────────────────────────────────────────────
-- The database name must match SNOWFLAKE_DATABASE in your environment.
-- If you use a non-standard name, update .env and dbt/profiles.yml accordingly.
CREATE DATABASE IF NOT EXISTS AUTOMARKET_DB
    COMMENT = 'AutoMarket Intel — Used-Car Pricing & Inventory Intelligence';

GRANT ALL ON DATABASE AUTOMARKET_DB TO ROLE AUTOMARKET_ROLE;

-- ── Schemas ───────────────────────────────────────────────────────────────────
-- TRANSIENT = no Fail-safe storage cost (acceptable for reproducible pipeline data)
CREATE TRANSIENT SCHEMA IF NOT EXISTS AUTOMARKET_DB.RAW
    COMMENT = 'Raw ingestion layer — loaded by Python pipeline via COPY INTO';
CREATE TRANSIENT SCHEMA IF NOT EXISTS AUTOMARKET_DB.STAGING
    COMMENT = 'dbt staging — typed views over RAW';
CREATE TRANSIENT SCHEMA IF NOT EXISTS AUTOMARKET_DB.CORE
    COMMENT = 'dbt core — dimension and fact tables';
CREATE TRANSIENT SCHEMA IF NOT EXISTS AUTOMARKET_DB.MARTS
    COMMENT = 'dbt marts — analytical aggregates';

GRANT ALL ON SCHEMA AUTOMARKET_DB.RAW     TO ROLE AUTOMARKET_ROLE;
GRANT ALL ON SCHEMA AUTOMARKET_DB.STAGING TO ROLE AUTOMARKET_ROLE;
GRANT ALL ON SCHEMA AUTOMARKET_DB.CORE    TO ROLE AUTOMARKET_ROLE;
GRANT ALL ON SCHEMA AUTOMARKET_DB.MARTS   TO ROLE AUTOMARKET_ROLE;

-- ── RAW table ─────────────────────────────────────────────────────────────────
-- Schema matches the canonical output of the Python ingestion pipeline
-- (see contracts/used_car_listings.v1.yaml and src/automarket/storage/serializer.py).
-- Column types match the Parquet schema produced by records_to_parquet().
CREATE TABLE IF NOT EXISTS AUTOMARKET_DB.RAW.RAW_USED_CAR_LISTINGS (
    ROW_ID          VARCHAR(16)    NOT NULL,   -- deterministic 16-char SHA-256 prefix
    SOURCE_FILE     VARCHAR(255)   NOT NULL,   -- originating CSV filename
    MAKE            VARCHAR(100)   NOT NULL,
    MODEL           VARCHAR(255)   NOT NULL,
    YEAR            INTEGER        NOT NULL,   -- registration year 1970–2025
    PRICE_GBP       INTEGER        NOT NULL,   -- asking price in GBP (NOT transaction price)
    TRANSMISSION    VARCHAR(20)    NOT NULL,   -- Manual | Automatic | Semi-Auto | Other
    MILEAGE_MILES   INTEGER        NOT NULL,
    FUEL_TYPE       VARCHAR(20)    NOT NULL,   -- Petrol | Diesel | Hybrid | Electric | Other
    TAX_GBP         INTEGER,                  -- nullable — absent in schema B files
    MPG             FLOAT,                    -- nullable — absent in schema B files
    ENGINE_SIZE_L   FLOAT                     -- nullable
);

GRANT ALL ON TABLE AUTOMARKET_DB.RAW.RAW_USED_CAR_LISTINGS TO ROLE AUTOMARKET_ROLE;

-- ── Quarantine table ──────────────────────────────────────────────────────────
-- Rejected rows are NOT uploaded to S3/Snowflake in the current design;
-- they remain in DuckDB's raw.raw_quarantine for local inspection.
-- This table is reserved for a future cloud quarantine path.
CREATE TABLE IF NOT EXISTS AUTOMARKET_DB.RAW.RAW_QUARANTINE (
    ROW_ID           VARCHAR(16),
    SOURCE_FILE      VARCHAR(255),
    MAKE             VARCHAR(100),
    MODEL            VARCHAR(255),
    YEAR             INTEGER,
    PRICE_GBP        INTEGER,
    TRANSMISSION     VARCHAR(20),
    MILEAGE_MILES    INTEGER,
    FUEL_TYPE        VARCHAR(20),
    TAX_GBP          INTEGER,
    MPG              FLOAT,
    ENGINE_SIZE_L    FLOAT,
    REJECTION_REASON VARCHAR(2000)
);

GRANT ALL ON TABLE AUTOMARKET_DB.RAW.RAW_QUARANTINE TO ROLE AUTOMARKET_ROLE;

-- ── Service account ───────────────────────────────────────────────────────────
-- Key-pair authentication only — no password is set.
CREATE USER IF NOT EXISTS AUTOMARKET_SVC
    DEFAULT_ROLE      = AUTOMARKET_ROLE
    DEFAULT_WAREHOUSE = AUTOMARKET_WH
    COMMENT           = 'Service account for AutoMarket Intel CI/CD pipeline';

GRANT ROLE AUTOMARKET_ROLE TO USER AUTOMARKET_SVC;

-- Set the RSA public key AFTER generating the key pair:
--   openssl genrsa -out rsa_key.pem 2048
--   openssl rsa -in rsa_key.pem -pubout -out rsa_key_pub.pem
-- Then paste the public key content (without BEGIN/END headers):
--   ALTER USER AUTOMARKET_SVC SET RSA_PUBLIC_KEY='<paste_public_key_here>';
--
-- Store the private key at the path set in SNOWFLAKE_PRIVATE_KEY_PATH.
-- NEVER commit the private key file.

-- ── Storage integration ───────────────────────────────────────────────────────
-- PREREQUISITE: Create an AWS IAM role for Snowflake BEFORE running this block.
-- See docs/DEPLOY.md "S3 storage integration" for the required IAM policy.
--
-- After running this statement, execute:
--   DESC INTEGRATION S3_INT_AUTOMARKET;
-- and note:
--   STORAGE_AWS_IAM_USER_ARN  → add to your IAM role's trust policy (Principal)
--   STORAGE_AWS_EXTERNAL_ID   → add as sts:ExternalId condition in trust policy
--
-- Replace <YOUR_AWS_IAM_ROLE_ARN> and <YOUR_S3_BUCKET_NAME> before running.
-- ─────────────────────────────────────────────────────────────────────────────
-- CREATE STORAGE INTEGRATION IF NOT EXISTS S3_INT_AUTOMARKET
--     TYPE = EXTERNAL_STAGE
--     STORAGE_PROVIDER = 'S3'
--     ENABLED = TRUE
--     STORAGE_AWS_ROLE_ARN = '<YOUR_AWS_IAM_ROLE_ARN>'
--     STORAGE_ALLOWED_LOCATIONS = ('s3://<YOUR_S3_BUCKET_NAME>/raw/used_cars/')
--     COMMENT = 'AutoMarket Intel — S3 access for Parquet loading';
--
-- GRANT USAGE ON INTEGRATION S3_INT_AUTOMARKET TO ROLE AUTOMARKET_ROLE;
-- ─────────────────────────────────────────────────────────────────────────────
-- After adding the Snowflake IAM user ARN to your AWS IAM trust policy,
-- uncomment and run the STAGE and FILE FORMAT blocks below.

-- ── Parquet file format ────────────────────────────────────────────────────────
-- ─────────────────────────────────────────────────────────────────────────────
-- CREATE OR REPLACE FILE FORMAT AUTOMARKET_DB.RAW.PARQUET_FORMAT_AUTOMARKET
--     TYPE = 'PARQUET'
--     SNAPPY_COMPRESSION = TRUE
--     BINARY_AS_TEXT = FALSE       -- treat binary columns as binary, not text
--     COMMENT = 'Parquet format for AutoMarket Intel normalized listings';
-- ─────────────────────────────────────────────────────────────────────────────

-- ── External stage ─────────────────────────────────────────────────────────────
-- ─────────────────────────────────────────────────────────────────────────────
-- CREATE OR REPLACE STAGE AUTOMARKET_DB.RAW.S3_STAGE_AUTOMARKET
--     STORAGE_INTEGRATION = S3_INT_AUTOMARKET
--     URL = 's3://<YOUR_S3_BUCKET_NAME>/raw/used_cars/'
--     FILE_FORMAT = AUTOMARKET_DB.RAW.PARQUET_FORMAT_AUTOMARKET
--     COMMENT = 'External stage for AutoMarket Intel normalized Parquet files';
--
-- GRANT READ ON STAGE AUTOMARKET_DB.RAW.S3_STAGE_AUTOMARKET TO ROLE AUTOMARKET_ROLE;
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Verify setup ─────────────────────────────────────────────────────────────
-- After completing all steps, verify:
--   SHOW WAREHOUSES LIKE 'AUTOMARKET_WH';
--   SHOW DATABASES LIKE 'AUTOMARKET_DB';
--   SELECT * FROM AUTOMARKET_DB.RAW.RAW_USED_CAR_LISTINGS LIMIT 1;
-- ─────────────────────────────────────────────────────────────────────────────
