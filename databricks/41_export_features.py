# Databricks notebook source
# MAGIC %md
# MAGIC # 41 — Export early-warning train / test sets
# MAGIC Split rules: `src/reliability/early_warning.py` (project plan, Phase 5).
# MAGIC - drive assignment: SHA-256("bb-ew-v1:" + serial) first 8 hex digits / 0xFFFFFFFF < test_frac -> test drive
# MAGIC   (identical to `is_test_drive`; re-verified locally on every exported serial)
# MAGIC - **train**: train drives, dates < cutoff, labels known; all `fail_30d = 1` rows + a fixed-seed sample of
# MAGIC   negatives at `neg_rate` (the rate is recorded so metrics can be re-weighted if needed)
# MAGIC - **test**: test drives, dates >= cutoff, all rows (natural distribution; unknown-label rows kept and flagged,
# MAGIC   then excluded at evaluation)
# MAGIC Writes Parquet to `/Volumes/<catalog>/gold/exports/ew_train|ew_test/` and `ew_manifest.json`.

# COMMAND ----------

import json

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "backblaze")
dbutils.widgets.text("cutoff", "2025-07-01")
dbutils.widgets.text("test_frac", "0.3")
dbutils.widgets.text("neg_rate", "0.02")
CATALOG = dbutils.widgets.get("catalog")
CUTOFF = dbutils.widgets.get("cutoff")
TEST_FRAC = float(dbutils.widgets.get("test_frac"))
NEG_RATE = float(dbutils.widgets.get("neg_rate"))
BASE = f"/Volumes/{CATALOG}/gold/exports"

f = spark.table(f"{CATALOG}.gold.drive_day_features").withColumn(
    "is_test_drive",
    (F.conv(F.substring(F.sha2(F.concat(F.lit("bb-ew-v1:"), F.col("serial_number")), 256), 1, 8), 16, 10)
     .cast("double") / F.lit(0xFFFFFFFF)) < F.lit(TEST_FRAC))

train = (f.where(~F.col("is_test_drive") & (F.col("date") < F.lit(CUTOFF)) & F.col("label_30d_known"))
         .where((F.col("fail_30d") == 1) | (F.rand(seed=42) < F.lit(NEG_RATE))))
test = f.where(F.col("is_test_drive") & (F.col("date") >= F.lit(CUTOFF)))

train.repartition(8).write.mode("overwrite").parquet(f"{BASE}/ew_train")
test.repartition(32).write.mode("overwrite").parquet(f"{BASE}/ew_test")

# COMMAND ----------

def stats(path):
    d = spark.read.parquet(path)
    r = d.agg(F.count("*").alias("rows"), F.countDistinct("serial_number").alias("drives"),
              F.sum("fail_7d").alias("pos_7d"), F.sum("fail_30d").alias("pos_30d"),
              F.min("date").cast("string").alias("min_date"), F.max("date").cast("string").alias("max_date"),
              F.sum(F.col("is_test_drive").cast("int")).alias("test_drive_rows")).first().asDict()
    return r

m = {"cutoff": CUTOFF, "test_frac": TEST_FRAC, "neg_rate": NEG_RATE,
     "ew_train": stats(f"{BASE}/ew_train"), "ew_test": stats(f"{BASE}/ew_test")}
# overlap check on the Databricks side too
overlap = (spark.read.parquet(f"{BASE}/ew_train").select("serial_number").distinct()
           .join(spark.read.parquet(f"{BASE}/ew_test").select("serial_number").distinct(), "serial_number").count())
m["serial_overlap"] = overlap
assert overlap == 0, f"{overlap} serials in both train and test"
assert m["ew_train"]["test_drive_rows"] == 0 and m["ew_test"]["test_drive_rows"] == m["ew_test"]["rows"]
assert m["ew_train"]["max_date"] < CUTOFF <= m["ew_test"]["min_date"]
dbutils.fs.put(f"{BASE}/ew_manifest.json", json.dumps(m, indent=2), overwrite=True)
print(json.dumps(m, indent=2))
dbutils.notebook.exit(json.dumps(m))
