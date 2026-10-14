# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Setup catalog, schemas, volume, control table
# MAGIC Idempotent: safe to re-run. Creates:
# MAGIC - catalog `backblaze` with schemas `bronze`, `silver`, `gold`, `ops`
# MAGIC - volume `backblaze.bronze.raw` for quarterly ZIP/CSV files
# MAGIC - volume `backblaze.gold.exports` for Parquet exports to Snowflake
# MAGIC - control table `backblaze.ops.quarter_status` tracking completed quarters per stage

# COMMAND ----------

dbutils.widgets.text("catalog", "backblaze")
CATALOG = dbutils.widgets.get("catalog")

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
for schema in ["bronze", "silver", "gold", "ops"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.bronze.raw COMMENT 'Backblaze quarterly drive-stats files'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.gold.exports COMMENT 'Parquet exports of gold tables for Snowflake'")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.ops.quarter_status (
  quarter STRING NOT NULL,
  stage STRING NOT NULL,          -- bronze | silver | gold | export
  status STRING NOT NULL,         -- complete
  row_count BIGINT,
  details STRING,                 -- JSON with stage-specific checks
  completed_at TIMESTAMP
)
""")

# COMMAND ----------

display(spark.sql(f"SHOW SCHEMAS IN {CATALOG}"))
display(spark.sql(f"SHOW VOLUMES IN {CATALOG}.bronze"))
