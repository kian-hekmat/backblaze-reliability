# Databricks notebook source
# MAGIC %md
# MAGIC # 50 — Load local modeling results into gold results tables
# MAGIC Reads `/Volumes/<catalog>/gold/results/_manifest.json` (written by `scripts/push_results.py`) and loads
# MAGIC each file as `<catalog>.gold.res_<name>` (overwrite). Fails if a table's row count differs from its source file.

# COMMAND ----------

import json

dbutils.widgets.text("catalog", "backblaze")
CATALOG = dbutils.widgets.get("catalog")
BASE = f"/Volumes/{CATALOG}/gold/results"
manifest = json.loads(dbutils.fs.head(f"{BASE}/_manifest.json", 1 << 20))

loaded = {}
for name, entry in manifest.items():
    path = f"{BASE}/{entry['file']}"
    df = (spark.read.parquet(path) if path.endswith(".parquet")
          else spark.read.option("header", True).option("inferSchema", True).csv(path))
    table = f"{CATALOG}.gold.res_{name}"
    df.write.format("delta").mode("overwrite").option("overwriteSchema", True).saveAsTable(table)
    n = spark.table(table).count()
    assert n == entry["rows"], f"{table}: {n} rows loaded, source has {entry['rows']}"
    loaded[table] = n
print(json.dumps(loaded, indent=2))
dbutils.notebook.exit(json.dumps(loaded))
