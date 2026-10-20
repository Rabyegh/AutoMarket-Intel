-- generate_schema_name macro
-- ────────────────────────────────────────────────────────────────────────────
-- Overrides dbt's default schema-name behavior to use the configured schema
-- exactly rather than prefixing it with the target schema (e.g. to avoid
-- 'staging_staging' or 'staging_raw' on Snowflake).
--
-- Behavior:
--   • Custom schema defined in dbt_project.yml (+schema: raw / staging / etc.)
--     → uses that schema name exactly, no prefix.
--   • No custom schema configured
--     → falls back to the target.schema from profiles.yml.
--
-- This is the standard dbt recommended override for projects that need exact
-- schema names on all adapters. See:
-- https://docs.getdbt.com/docs/build/custom-schemas

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema | trim }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
