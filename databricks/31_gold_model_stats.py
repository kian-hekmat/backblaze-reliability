# Databricks notebook source
# MAGIC %md
# MAGIC # 31 — gold.model_period_stats and gold.model_age_stats
# MAGIC - `model_period_stats`: per model per quarter: drive count, drive-days, failures (AFR inputs). `failures` counts
# MAGIC   counted failures (a drive's final-row failure, as in drive_lifetimes); `failure_flags` counts raw failure=1 rows.
# MAGIC - `model_age_stats`: per model per quarter per age year: drive-days and failures, for the
# MAGIC   age-aware Bayesian model (DECISIONS, approved change 2). Row age = drive's entry age (SMART 9 at first
# MAGIC   observation) + days since first observation. Drives with implausible SMART 9 get age_year = -1 (unknown).
# MAGIC
# MAGIC Rebuilt in full from silver + drive_lifetimes. Checks: drive-days and failures sum to silver totals.

# COMMAND ----------

import json
from datetime import datetime, timezone

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "backblaze")
CATALOG = dbutils.widgets.get("catalog")
SILVER, LT = f"{CATALOG}.silver.drive_stats", f"{CATALOG}.gold.drive_lifetimes"

s = spark.table(SILVER).select("serial_number", "date", "quarter", "failure")
lt = spark.table(LT).select("serial_number", "model", "model_short", "manufacturer", "capacity_bytes",
                            "is_data_drive", "first_date", "entry_age_days", "age_ok", "failure_date")
# Model attributes come from drive_lifetimes so a drive counts under one model for its whole life.
# `failures` counts only a drive's counted failure (its final row; DECISIONS failure semantics), consistent with
# drive_lifetimes. `failure_flags` keeps every raw failure=1 row (differs only for drives that reappeared).
rows = (s.join(lt, "serial_number")
        .withColumn("failure_flag", F.col("failure"))
        .withColumn("failure", F.coalesce((F.col("date") == F.col("failure_date")).cast("int"), F.lit(0)))
        .withColumn("age_days", F.col("entry_age_days") + F.datediff("date", "first_date"))
        .withColumn("age_year", F.when(F.col("age_ok") == 1, F.floor(F.col("age_days") / 365.25)).otherwise(-1)))

keys = ["model", "model_short", "manufacturer", "capacity_bytes", "is_data_drive", "quarter"]
mps = (rows.groupBy(*keys)
       .agg(F.countDistinct("serial_number").alias("drive_count"), F.count("*").alias("drive_days"),
            F.sum("failure").alias("failures"), F.sum("failure_flag").alias("failure_flags"),
            F.avg(F.when(F.col("age_ok") == 1, F.col("age_days"))).alias("mean_age_days"),
            F.min("date").alias("period_start"), F.max("date").alias("period_end"))
       .withColumn("afr_pct", F.col("failures") / (F.col("drive_days") / 365.0) * 100))
mps.write.format("delta").mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{CATALOG}.gold.model_period_stats")

mas = (rows.groupBy(*keys, "age_year")
       .agg(F.countDistinct("serial_number").alias("drive_count"), F.count("*").alias("drive_days"),
            F.sum("failure").alias("failures"), F.sum("failure_flag").alias("failure_flags")))
mas.write.format("delta").mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{CATALOG}.gold.model_age_stats")

# COMMAND ----------

chk = spark.sql(f"""SELECT
  (SELECT count(*) FROM {SILVER}) silver_rows, (SELECT sum(failure) FROM {SILVER}) silver_failure_flags,
  (SELECT sum(failed) FROM {LT}) lifetimes_failed,
  (SELECT sum(failure_flags) FROM {CATALOG}.gold.model_period_stats) mps_failure_flags,
  (SELECT sum(drive_days) FROM {CATALOG}.gold.model_period_stats) mps_drive_days,
  (SELECT sum(failures) FROM {CATALOG}.gold.model_period_stats) mps_failures,
  (SELECT sum(drive_days) FROM {CATALOG}.gold.model_age_stats) mas_drive_days,
  (SELECT sum(failures) FROM {CATALOG}.gold.model_age_stats) mas_failures,
  (SELECT count(*) FROM {CATALOG}.gold.model_period_stats) mps_rows,
  (SELECT count(*) FROM {CATALOG}.gold.model_age_stats) mas_rows,
  (SELECT sum(drive_days) FROM {CATALOG}.gold.model_age_stats WHERE age_year = -1) unknown_age_drive_days
""").first().asDict()
print(json.dumps(chk, indent=2))
assert chk["mps_drive_days"] == chk["mas_drive_days"] == chk["silver_rows"]
assert chk["mps_failures"] == chk["mas_failures"] == chk["lifetimes_failed"]
assert chk["mps_failure_flags"] == chk["silver_failure_flags"]
null_failures = spark.sql(f"""SELECT (SELECT count(*) FROM {CATALOG}.gold.model_period_stats WHERE failures IS NULL)
                                   + (SELECT count(*) FROM {CATALOG}.gold.model_age_stats WHERE failures IS NULL)""").first()[0]
chk["rows_with_null_failures"] = null_failures
assert null_failures == 0, "null failure counts in model stats"

spark.sql(f"DELETE FROM {CATALOG}.ops.quarter_status WHERE quarter = 'ALL' AND stage = 'gold_model_stats'")
spark.createDataFrame(
    [("ALL", "gold_model_stats", "complete", chk["mps_rows"], json.dumps(chk), datetime.now(timezone.utc))],
    "quarter string, stage string, status string, row_count bigint, details string, completed_at timestamp",
).write.mode("append").saveAsTable(f"{CATALOG}.ops.quarter_status")
dbutils.notebook.exit(json.dumps(chk))
