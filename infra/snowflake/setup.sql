-- Snowflake bootstrap — run once with an ACCOUNTADMIN (or SYSADMIN + SECURITYADMIN) role.
-- This script is idempotent (CREATE IF NOT EXISTS everywhere).
-- See docs/DEPLOY.md for full instructions.

-- ── Role ──────────────────────────────────────────────────────────────────────
CREATE ROLE IF NOT EXISTS VINPIPE_ROLE;
GRANT ROLE VINPIPE_ROLE TO ROLE SYSADMIN;

-- ── Warehouse ─────────────────────────────────────────────────────────────────
CREATE WAREHOUSE IF NOT EXISTS VINPIPE_WH
  WAREHOUSE_SIZE = 'X-SMALL'
  AUTO_SUSPEND   = 60
  AUTO_RESUME    = TRUE
  COMMENT        = 'VIN Fleet Pipeline — small batch only';

GRANT USAGE ON WAREHOUSE VINPIPE_WH TO ROLE VINPIPE_ROLE;

-- ── Resource monitor (hard credit cap) ────────────────────────────────────────
-- Adjust CREDIT_QUOTA to your comfort level.
CREATE RESOURCE MONITOR IF NOT EXISTS VINPIPE_MONITOR
  WITH CREDIT_QUOTA = 5
  FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS
    ON 80 PERCENT DO NOTIFY
    ON 100 PERCENT DO SUSPEND;

ALTER WAREHOUSE VINPIPE_WH SET RESOURCE_MONITOR = VINPIPE_MONITOR;

-- ── Database and schemas ──────────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS VINPIPE_DB;
GRANT ALL ON DATABASE VINPIPE_DB TO ROLE VINPIPE_ROLE;

-- Transient schemas — no Fail-safe storage cost
CREATE TRANSIENT SCHEMA IF NOT EXISTS VINPIPE_DB.RAW;
CREATE TRANSIENT SCHEMA IF NOT EXISTS VINPIPE_DB.STAGING;
CREATE TRANSIENT SCHEMA IF NOT EXISTS VINPIPE_DB.CORE;
CREATE TRANSIENT SCHEMA IF NOT EXISTS VINPIPE_DB.MARTS;

GRANT ALL ON SCHEMA VINPIPE_DB.RAW     TO ROLE VINPIPE_ROLE;
GRANT ALL ON SCHEMA VINPIPE_DB.STAGING TO ROLE VINPIPE_ROLE;
GRANT ALL ON SCHEMA VINPIPE_DB.CORE    TO ROLE VINPIPE_ROLE;
GRANT ALL ON SCHEMA VINPIPE_DB.MARTS   TO ROLE VINPIPE_ROLE;

-- ── Service user ─────────────────────────────────────────────────────────────
-- Key-pair auth only — password intentionally omitted.
CREATE USER IF NOT EXISTS VINPIPE_SVC
  DEFAULT_ROLE      = VINPIPE_ROLE
  DEFAULT_WAREHOUSE = VINPIPE_WH
  COMMENT           = 'Service account for vinpipe CI/CD';

GRANT ROLE VINPIPE_ROLE TO USER VINPIPE_SVC;
-- Set public key: ALTER USER VINPIPE_SVC SET RSA_PUBLIC_KEY='<your_public_key>';
