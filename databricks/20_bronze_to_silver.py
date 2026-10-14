# Databricks notebook source
# MAGIC %md
# MAGIC # 20 — Bronze to silver for one quarter
# MAGIC Applies the data-quality rules in `docs/DECISIONS.md`:
# MAGIC - types cast; SMART raw values that are non-null but fail to cast are counted (and fail the job)
# MAGIC - model normalization via `reliability.normalize.normalize_model` (same tested function as locally)
# MAGIC - dedup on (date, serial_number): prefer failure=1, then most non-null SMART, then lowest source file
# MAGIC - per-drive capacity = most frequent positive value within the quarter; non-positive -> null
# MAGIC - `is_data_drive` = capacity >= 4 TB
# MAGIC - only the SMART attributes chosen in DECISIONS are kept
# MAGIC
# MAGIC Writes `<catalog>.silver.drive_stats` (partitioned by date) with MERGE, so re-running a quarter
# MAGIC replaces exactly that quarter's rows. Checks row conservation and (date, serial) uniqueness; fails loudly.

# COMMAND ----------

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from pyspark.sql import Window
from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "backblaze")
dbutils.widgets.text("quarter", "")
CATALOG = dbutils.widgets.get("catalog")

_nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
sys.path.insert(0, "/Workspace" + os.path.dirname(os.path.dirname(_nb)) + "/src")
from reliability.normalize import DATA_DRIVE_MIN_BYTES, normalize_model  # noqa: E402

QUARTERS = ["Q3_2023", "Q4_2023", "Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024",
            "Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]
SMART_IDS = [1, 3, 4, 5, 7, 9, 10, 12, 187, 188, 192, 193, 194, 196, 197, 198, 199, 240, 241, 242]


def done(stage):
    return {r.quarter for r in spark.sql(
        f"SELECT quarter FROM {CATALOG}.ops.quarter_status WHERE stage='{stage}' AND status='complete'").collect()}


QUARTER = dbutils.widgets.get("quarter") or next(
    (q for q in QUARTERS if q in done("bronze") and q not in done("silver")), None)
if QUARTER is None:
    dbutils.notebook.exit(json.dumps({"status": "nothing to do"}))
assert QUARTER in done("bronze"), f"{QUARTER} has no completed bronze load"
qn, yr = int(QUARTER[1]), int(QUARTER[3:])
Q_START = date(yr, 3 * qn - 2, 1)
Q_END = date(yr + (qn == 4), 1 if qn == 4 else 3 * qn + 1, 1) - timedelta(days=1)
print(QUARTER, Q_START, Q_END)

SILVER = f"{CATALOG}.silver.drive_stats"

# COMMAND ----------

bronze = spark.table(f"{CATALOG}.bronze.drive_stats_raw").where(F.col("quarter") == QUARTER)
bronze_rows = bronze.count()

# Model normalization: map the (small) set of distinct raw strings through the tested Python function
raw_models = [r.model for r in bronze.select("model").distinct().collect()]
model_map = spark.createDataFrame(
    [(m, *normalize_model(m)) for m in raw_models if m is not None],
    "model_raw string, model string, model_short string, manufacturer string")

smart_cols = []
for i in SMART_IDS:
    smart_cols += [F.expr(f"try_cast(smart_{i}_normalized AS INT)").alias(f"smart_{i}_normalized"),
                   F.expr(f"try_cast(smart_{i}_raw AS BIGINT)").alias(f"smart_{i}_raw")]

typed = bronze.select(
    F.to_date("date").alias("date"),
    F.trim("serial_number").alias("serial_number"),
    F.col("model").alias("model_raw"),
    F.expr("try_cast(capacity_bytes AS BIGINT)").alias("capacity_bytes_raw"),
    F.col("failure").cast("int").alias("failure"),
    "datacenter", "cluster_id", "vault_id", "pod_id", "pod_slot_num",
    *smart_cols,
    "source_file",
)

# Cast-failure audit: non-null string that became null after casting
audit_exprs = [F.sum(F.when(F.col("date").isNull(), 1).otherwise(0)).alias("bad_date"),
               F.sum(F.when(~F.col("failure").isin(0, 1) | F.col("failure").isNull(), 1).otherwise(0)).alias("bad_failure"),
               F.sum(F.when(F.col("serial_number").isNull() | (F.col("serial_number") == ""), 1).otherwise(0)).alias("bad_serial")]
audit = typed.agg(*audit_exprs).first().asDict()
cast_fail = bronze.agg(*[
    F.sum(F.when(F.col(f"smart_{i}_{k}").isNotNull() &
                 F.expr(f"try_cast(smart_{i}_{k} AS {'INT' if k == 'normalized' else 'BIGINT'})").isNull(), 1)
          .otherwise(0)).alias(f"smart_{i}_{k}")
    for i in SMART_IDS for k in ("normalized", "raw")]).first().asDict()
cast_fail = {k: v for k, v in cast_fail.items() if v}
print("audit:", audit, "smart cast failures:", cast_fail)
assert all(v == 0 for v in audit.values()), audit
assert not cast_fail, f"SMART values failed to cast: {cast_fail}"

# COMMAND ----------

# Dedup on (date, serial_number)
n_smart_nonnull = sum(F.when(F.col(f"smart_{i}_raw").isNotNull(), 1).otherwise(0) for i in SMART_IDS)
w = Window.partitionBy("date", "serial_number").orderBy(
    F.col("failure").desc(), n_smart_nonnull.desc(), F.col("source_file").asc())
deduped = typed.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")

# Per-drive capacity: most frequent positive value within the quarter
cap_counts = (deduped.where(F.col("capacity_bytes_raw") > 0)
              .groupBy("serial_number", "capacity_bytes_raw").count())
wc = Window.partitionBy("serial_number").orderBy(F.col("count").desc(), F.col("capacity_bytes_raw").desc())
drive_cap = (cap_counts.withColumn("_rn", F.row_number().over(wc)).where("_rn = 1")
             .select("serial_number", F.col("capacity_bytes_raw").alias("capacity_bytes")))
multi_cap = cap_counts.groupBy("serial_number").count().where("count > 1").count()

silver_q = (deduped.join(model_map, "model_raw", "left")
            .join(drive_cap, "serial_number", "left")
            .withColumn("is_data_drive", F.coalesce(F.col("capacity_bytes") >= F.lit(DATA_DRIVE_MIN_BYTES), F.lit(False)))
            .withColumn("quarter", F.lit(QUARTER))
            .select("date", "serial_number", "model", "model_short", "manufacturer", "model_raw",
                    "capacity_bytes", "is_data_drive", "failure",
                    "datacenter", "cluster_id", "vault_id", "pod_id", "pod_slot_num",
                    *[f"smart_{i}_{k}" for i in SMART_IDS for k in ("normalized", "raw")],
                    "quarter", "source_file"))
silver_q.createOrReplaceTempView("silver_q")

# COMMAND ----------

if not spark.catalog.tableExists(SILVER):
    silver_q.limit(0).write.format("delta").partitionBy("date").saveAsTable(SILVER)

spark.sql(f"""
MERGE INTO {SILVER} t
USING silver_q s
ON t.date = s.date AND t.serial_number = s.serial_number
   AND t.date BETWEEN DATE'{Q_START}' AND DATE'{Q_END}'
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
WHEN NOT MATCHED BY SOURCE AND t.date BETWEEN DATE'{Q_START}' AND DATE'{Q_END}' THEN DELETE
""")

# COMMAND ----------

# Checks (fail loudly)
dup_dropped = bronze_rows - deduped.count()
s = spark.sql(f"""
  SELECT count(*) n, count(DISTINCT date, serial_number) n_keys, count(DISTINCT serial_number) drives,
         count(DISTINCT model) models, sum(failure) failures,
         sum(CASE WHEN model IS NULL THEN 1 ELSE 0 END) null_model,
         sum(CASE WHEN capacity_bytes IS NULL THEN 1 ELSE 0 END) null_capacity,
         sum(CASE WHEN is_data_drive THEN 1 ELSE 0 END) data_drive_rows,
         count(DISTINCT CASE WHEN is_data_drive THEN serial_number END) data_drives,
         count(DISTINCT CASE WHEN NOT is_data_drive THEN serial_number END) non_data_drives,
         sum(CASE WHEN quarter <> '{QUARTER}' THEN 1 ELSE 0 END) other_quarter_rows
  FROM {SILVER} WHERE date BETWEEN DATE'{Q_START}' AND DATE'{Q_END}'""").first().asDict()
rows_after_failure = spark.sql(f"""
  SELECT count(DISTINCT s.serial_number) FROM {SILVER} s
  JOIN (SELECT serial_number, min(date) fd FROM {SILVER} WHERE failure = 1
        AND date BETWEEN DATE'{Q_START}' AND DATE'{Q_END}' GROUP BY 1) f USING (serial_number)
  WHERE s.date > f.fd AND s.date <= DATE'{Q_END}'""").first()[0]
multi_model = spark.sql(f"""SELECT count(*) FROM (SELECT serial_number FROM {SILVER}
  WHERE date BETWEEN DATE'{Q_START}' AND DATE'{Q_END}' GROUP BY 1 HAVING count(DISTINCT model) > 1)""").first()[0]

details = {"bronze_rows": bronze_rows, "duplicate_rows_dropped": dup_dropped, "silver_rows": s["n"],
           "drives_with_multiple_capacities": multi_cap, "drives_with_multiple_models": multi_model,
           "drives_with_rows_after_failure": rows_after_failure, "raw_model_strings": len(raw_models), **s}
print(json.dumps(details, indent=2, default=str))

assert s["n"] == bronze_rows - dup_dropped, "row conservation failed: silver != bronze - duplicates"
assert s["n"] == s["n_keys"], "(date, serial_number) not unique in silver"
assert s["null_model"] == 0 and s["other_quarter_rows"] == 0

spark.sql(f"DELETE FROM {CATALOG}.ops.quarter_status WHERE quarter = '{QUARTER}' AND stage = 'silver'")
spark.createDataFrame(
    [(QUARTER, "silver", "complete", s["n"], json.dumps(details, default=str), datetime.now(timezone.utc))],
    "quarter string, stage string, status string, row_count bigint, details string, completed_at timestamp",
).write.mode("append").saveAsTable(f"{CATALOG}.ops.quarter_status")
dbutils.notebook.exit(json.dumps({"quarter": QUARTER, **details}, default=str))
