# Databricks notebook source
# MAGIC %md
# MAGIC # 40 — Export gold tables to Parquet for local modeling
# MAGIC Writes each table to `/Volumes/<catalog>/gold/exports/<table>/` (overwritten each run) plus
# MAGIC `_manifest.json` with exact row counts and sum checks; the local download is reconciled against it
# MAGIC (`scripts/pull_exports.py`). `drive_day_features` is exported separately for Phase 5 (sampled train / full test).

# COMMAND ----------

import json

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "backblaze")
dbutils.widgets.text("tables", "drive_lifetimes,model_period_stats,model_age_stats")
CATALOG = dbutils.widgets.get("catalog")
TABLES = [t.strip() for t in dbutils.widgets.get("tables").split(",") if t.strip()]
BASE = f"/Volumes/{CATALOG}/gold/exports"

manifest = {}
for t in TABLES:
    df = spark.table(f"{CATALOG}.gold.{t}")
    df.coalesce(4).write.mode("overwrite").parquet(f"{BASE}/{t}")
    back = spark.read.parquet(f"{BASE}/{t}")
    entry = {"rows": back.count()}
    if "drive_days" in df.columns:
        entry["sum_drive_days"] = back.agg(F.sum("drive_days")).first()[0]
    if "failures" in df.columns:
        entry["sum_failures"] = back.agg(F.sum("failures")).first()[0]
    if "failed" in df.columns:
        entry["sum_failed"] = back.agg(F.sum("failed")).first()[0]
        entry["sum_n_obs_days"] = back.agg(F.sum("n_obs_days")).first()[0]
    assert entry["rows"] == df.count(), f"{t}: Parquet rows != Delta rows"
    manifest[t] = entry

dbutils.fs.put(f"{BASE}/_manifest.json", json.dumps(manifest, indent=2), overwrite=True)
print(json.dumps(manifest, indent=2))
dbutils.notebook.exit(json.dumps(manifest))
