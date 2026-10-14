# Databricks notebook source
# MAGIC %md
# MAGIC # 10 — Ingest one quarter into bronze
# MAGIC - Input: `/Volumes/<catalog>/bronze/raw/zips/data_<quarter>.zip` (uploaded unchanged from Backblaze)
# MAGIC - Output: `<catalog>.bronze.drive_stats_raw`, all CSV columns kept as raw strings, plus
# MAGIC   `source_file`, `ingested_at`, `quarter`
# MAGIC - Idempotent: the quarter's partition is replaced (`replaceWhere`), never appended.
# MAGIC - Check: bronze row count == data lines in the CSV files (counted with a separate plain-text reader).
# MAGIC   Fails loudly on mismatch. Records completion in `<catalog>.ops.quarter_status`.

# COMMAND ----------

import json
import os
import zipfile
from datetime import datetime, timezone

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "backblaze")
dbutils.widgets.text("quarter", "")  # e.g. Q2_2026; empty = next unprocessed quarter
CATALOG = dbutils.widgets.get("catalog")
QUARTERS = ["Q3_2023", "Q4_2023", "Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024",
            "Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]


def completed(stage):
    return {r.quarter for r in spark.sql(
        f"SELECT quarter FROM {CATALOG}.ops.quarter_status WHERE stage = '{stage}' AND status = 'complete'").collect()}


QUARTER = dbutils.widgets.get("quarter") or next((q for q in QUARTERS if q not in completed("bronze")), None)
if QUARTER is None:
    dbutils.notebook.exit(json.dumps({"status": "nothing to do"}))
assert QUARTER in QUARTERS, f"unknown quarter {QUARTER}"
print("quarter:", QUARTER)

VOL = f"/Volumes/{CATALOG}/bronze/raw"
ZIP = f"{VOL}/zips/data_{QUARTER}.zip"
CSV_DIR = f"{VOL}/csv/{QUARTER}"
TABLE = f"{CATALOG}.bronze.drive_stats_raw"

# COMMAND ----------

# Unzip (idempotent: skip files already extracted with the right size)
os.makedirs(CSV_DIR, exist_ok=True)
with zipfile.ZipFile(ZIP) as zf:
    members = [m for m in zf.infolist() if m.filename.endswith(".csv") and "__MACOSX" not in m.filename]
    for m in members:
        dest = f"{CSV_DIR}/{os.path.basename(m.filename)}"
        if os.path.exists(dest) and os.path.getsize(dest) == m.file_size:
            continue
        with zf.open(m) as src, open(dest, "wb") as dst:
            while chunk := src.read(64 << 20):
                dst.write(chunk)
csv_files = sorted(f for f in os.listdir(CSV_DIR) if f.endswith(".csv"))
assert len(csv_files) == len(members), (len(csv_files), len(members))
print(len(csv_files), "daily files")

# COMMAND ----------

# Independent count: physical non-empty lines minus one header per file
lines = (spark.read.text(f"{CSV_DIR}/*.csv")
         .where(F.length(F.trim("value")) > 0).count())
expected_rows = lines - len(csv_files)

# Raw strings, header by name; no type inference, no filtering
df = (spark.read.option("header", True).option("inferSchema", False).option("mode", "FAILFAST")
      .csv(f"{CSV_DIR}/*.csv")
      .withColumn("source_file", F.col("_metadata.file_name"))
      .withColumn("ingested_at", F.current_timestamp())
      .withColumn("quarter", F.lit(QUARTER)))

(df.write.format("delta").mode("overwrite")
   .option("replaceWhere", f"quarter = '{QUARTER}'")
   .option("mergeSchema", True)
   .partitionBy("quarter")
   .saveAsTable(TABLE))

# COMMAND ----------

stats = spark.sql(f"""
  SELECT count(*) n, count(DISTINCT source_file) files, min(date) min_date, max(date) max_date,
         sum(CASE WHEN date <> substr(source_file, 1, 10) THEN 1 ELSE 0 END) date_ne_file
  FROM {TABLE} WHERE quarter = '{QUARTER}'""").first().asDict()
print(stats, "expected_rows:", expected_rows)
assert stats["n"] == expected_rows, f"bronze rows {stats['n']} != CSV data lines {expected_rows}"
assert stats["files"] == len(csv_files)
assert stats["date_ne_file"] == 0

details = {**stats, "csv_files": len(csv_files), "csv_data_lines": expected_rows}
spark.sql(f"DELETE FROM {CATALOG}.ops.quarter_status WHERE quarter = '{QUARTER}' AND stage = 'bronze'")
spark.createDataFrame(
    [(QUARTER, "bronze", "complete", stats["n"], json.dumps(details, default=str), datetime.now(timezone.utc))],
    "quarter string, stage string, status string, row_count bigint, details string, completed_at timestamp",
).write.mode("append").saveAsTable(f"{CATALOG}.ops.quarter_status")
dbutils.notebook.exit(json.dumps({"quarter": QUARTER, **details}, default=str))
