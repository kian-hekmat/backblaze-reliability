# Databricks notebook source
# MAGIC %md
# MAGIC # 30 — gold.drive_lifetimes (one row per drive)
# MAGIC Rebuilt in full from silver on each run (~400k drives; cheap). The window is all silver dates loaded so far.
# MAGIC
# MAGIC - `failed` = 1 iff the drive's last observed row has failure = 1 (DECISIONS: failure semantics)
# MAGIC - `event` = failed | censored_window_end (still running on the last window day) |
# MAGIC   censored_left_fleet (stopped reporting before the window end without a failure row)
# MAGIC - Age (DECISIONS, approved change 1): `entry_age_days` = SMART 9 power-on hours at first observation / 24;
# MAGIC   `exit_age_days` = entry age + calendar days from first to last observation. Survival by age uses
# MAGIC   delayed entry at `entry_age_days` (left truncation). `age_ok` flags plausible SMART 9 values.
# MAGIC
# MAGIC Checks: serial unique; every serial whose final silver row is a failure has failed = 1; counts match silver.

# COMMAND ----------

import json
from datetime import datetime, timezone

from pyspark.sql import Window
from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "backblaze")
CATALOG = dbutils.widgets.get("catalog")
SILVER = f"{CATALOG}.silver.drive_stats"
TABLE = f"{CATALOG}.gold.drive_lifetimes"
MAX_PLAUSIBLE_AGE_DAYS = 15 * 365  # SMART 9 above 15 years is treated as a bad reading

s = spark.table(SILVER)
win_start, win_end = s.agg(F.min("date"), F.max("date")).first()
print("window:", win_start, win_end)

# COMMAND ----------

w_first = Window.partitionBy("serial_number").orderBy("date")
w_last = Window.partitionBy("serial_number").orderBy(F.col("date").desc())
ranked = (s.select("serial_number", "date", "failure", "model", "model_short", "manufacturer",
                   "capacity_bytes", "is_data_drive", "smart_9_raw")
          .withColumn("_rf", F.row_number().over(w_first))
          .withColumn("_rl", F.row_number().over(w_last)))

first_row = ranked.where("_rf = 1").select(
    "serial_number", F.col("date").alias("first_date"), F.col("smart_9_raw").alias("poh_first"))
last_row = ranked.where("_rl = 1").select(
    "serial_number", F.col("date").alias("last_date"), F.col("failure").alias("last_failure"),
    F.col("smart_9_raw").alias("poh_last"))

# Most frequent model / capacity per drive (ties -> latest value); counts of distinct values logged
def mode_of(col):
    c = ranked.groupBy("serial_number", col).agg(F.count("*").alias("n"), F.max("date").alias("d"))
    w = Window.partitionBy("serial_number").orderBy(F.col("n").desc(), F.col("d").desc())
    return c.withColumn("_r", F.row_number().over(w)).where("_r = 1").select("serial_number", col)

agg = ranked.groupBy("serial_number").agg(
    F.count("*").alias("n_obs_days"),
    F.sum("failure").alias("n_failure_rows"),
    F.min(F.when(F.col("failure") == 1, F.col("date"))).alias("first_failure_date"),
    F.countDistinct("model").alias("n_models"),
    F.countDistinct("capacity_bytes").alias("n_capacities"),
)
model_attrs = (mode_of("model").join(
    ranked.select("serial_number", "model", "model_short", "manufacturer").distinct(), ["serial_number", "model"])
    .dropDuplicates(["serial_number"]))

lt = (agg.join(first_row, "serial_number").join(last_row, "serial_number")
      .join(model_attrs, "serial_number").join(mode_of("capacity_bytes"), "serial_number", "left")
      .withColumn("is_data_drive", F.coalesce(F.col("capacity_bytes") >= F.lit(4_000_000_000_000), F.lit(False)))
      .withColumn("failed", F.col("last_failure"))
      .withColumn("failure_date", F.when(F.col("failed") == 1, F.col("last_date")))
      .withColumn("reappeared_after_failure",
                  (F.col("first_failure_date").isNotNull() & (F.col("first_failure_date") < F.col("last_date"))).cast("int"))
      .withColumn("event", F.when(F.col("failed") == 1, "failed")
                  .when(F.col("last_date") == F.lit(win_end), "censored_window_end")
                  .otherwise("censored_left_fleet"))
      .withColumn("censored", 1 - F.col("failed"))
      .withColumn("observed_days", F.datediff("last_date", "first_date") + 1)
      .withColumn("left_truncated", (F.col("first_date") == F.lit(win_start)).cast("int"))
      .withColumn("entry_age_days", F.col("poh_first") / 24.0)
      .withColumn("exit_age_days", F.col("entry_age_days") + F.col("observed_days"))
      .withColumn("age_ok", (F.col("poh_first").isNotNull() & (F.col("poh_first") >= 0)
                             & (F.col("entry_age_days") <= MAX_PLAUSIBLE_AGE_DAYS)
                             & (F.col("poh_last") >= F.col("poh_first"))).cast("int"))
      .withColumn("window_start", F.lit(win_start)).withColumn("window_end", F.lit(win_end))
      .select("serial_number", "model", "model_short", "manufacturer", "capacity_bytes", "is_data_drive",
              "first_date", "last_date", "n_obs_days", "observed_days", "failed", "failure_date", "censored",
              "event", "left_truncated", "poh_first", "poh_last", "entry_age_days", "exit_age_days", "age_ok",
              "n_failure_rows", "reappeared_after_failure", "n_models", "n_capacities",
              "window_start", "window_end"))

lt.write.format("delta").mode("overwrite").option("overwriteSchema", True).saveAsTable(TABLE)

# COMMAND ----------

chk = spark.sql(f"""
SELECT
  (SELECT count(*) FROM {TABLE}) n_rows,
  (SELECT count(DISTINCT serial_number) FROM {TABLE}) n_serials,
  (SELECT count(DISTINCT serial_number) FROM {SILVER}) silver_serials,
  (SELECT sum(n_obs_days) FROM {TABLE}) sum_obs_days,
  (SELECT count(*) FROM {SILVER}) silver_rows,
  (SELECT count(DISTINCT serial_number) FROM {SILVER} WHERE failure = 1) silver_failed_serials,
  (SELECT sum(failed) FROM {TABLE}) failed_drives,
  (SELECT sum(reappeared_after_failure) FROM {TABLE}) reappeared,
  (SELECT count(*) FROM {TABLE} WHERE n_failure_rows > 0 AND failed = 0) failure_row_not_final,
  (SELECT count(*) FROM {TABLE} WHERE n_models > 1) multi_model_drives,
  (SELECT count(*) FROM {TABLE} WHERE n_capacities > 1) multi_capacity_drives,
  (SELECT count(*) FROM {TABLE} WHERE is_data_drive AND age_ok = 0) data_drives_bad_age,
  (SELECT count(*) FROM {TABLE} WHERE is_data_drive) data_drives
""").first().asDict()
# Every failed drive in silver appears exactly once with failed = 1. Exception (logged): a serial that
# reappeared after a failure row, which Backblaze treats as not failed.
final_failures_in_silver = spark.sql(f"""
  SELECT count(*) FROM (SELECT serial_number, max_by(failure, date) f FROM {SILVER} GROUP BY 1) WHERE f = 1""").first()[0]
chk.update(final_failures_in_silver=final_failures_in_silver, window_start=str(win_start), window_end=str(win_end))
print(json.dumps(chk, indent=2))

assert chk["n_rows"] == chk["n_serials"] == chk["silver_serials"], "drive_lifetimes not one row per silver serial"
assert chk["sum_obs_days"] == chk["silver_rows"], "drive-days not conserved"
assert chk["failed_drives"] == final_failures_in_silver
assert chk["failed_drives"] + chk["failure_row_not_final"] == chk["silver_failed_serials"]

spark.sql(f"DELETE FROM {CATALOG}.ops.quarter_status WHERE quarter = 'ALL' AND stage = 'gold_lifetimes'")
spark.createDataFrame(
    [("ALL", "gold_lifetimes", "complete", chk["n_rows"], json.dumps(chk), datetime.now(timezone.utc))],
    "quarter string, stage string, status string, row_count bigint, details string, completed_at timestamp",
).write.mode("append").saveAsTable(f"{CATALOG}.ops.quarter_status")
dbutils.notebook.exit(json.dumps(chk))
