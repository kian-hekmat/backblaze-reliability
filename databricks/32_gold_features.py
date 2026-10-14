# Databricks notebook source
# MAGIC %md
# MAGIC # 32 — gold.drive_day_features for one quarter (data drives only)
# MAGIC Feature definitions: `src/reliability/features.py`; labels: `src/reliability/labels.py`.
# MAGIC
# MAGIC Incremental by quarter:
# MAGIC - reads silver for [quarter start - 30 days, quarter end] so 7/30-day windows see the prior quarter
# MAGIC - `*_ever` flags continue from the previous quarter's final state (max over its rows)
# MAGIC - after writing, labels are refreshed for the previous quarter's last 31 days, because failures in
# MAGIC   this quarter change them (DECISIONS, approved change 3)
# MAGIC
# MAGIC Run order per quarter: silver -> 30 drive_lifetimes -> 31 model stats -> 32 features.
# MAGIC Check: for a sample of drives (random + failed), Spark output must equal the reference pandas
# MAGIC implementation computed from those drives' silver history. Since the reference is tested for
# MAGIC prefix invariance (no future data), equality shows the Spark features use only past data.

# COMMAND ----------

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from pyspark.sql import Window
from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "backblaze")
dbutils.widgets.text("quarter", "")
CATALOG = dbutils.widgets.get("catalog")
_nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
sys.path.insert(0, "/Workspace" + os.path.dirname(os.path.dirname(_nb)) + "/src")
from reliability.features import CRITICAL, TREND_ATTRS, compute_features  # noqa: E402
from reliability.labels import HORIZONS, compute_labels  # noqa: E402

QUARTERS = ["Q3_2023", "Q4_2023", "Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024",
            "Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]
SILVER, LT, TABLE = f"{CATALOG}.silver.drive_stats", f"{CATALOG}.gold.drive_lifetimes", f"{CATALOG}.gold.drive_day_features"


def done(stage):
    return {r.quarter for r in spark.sql(
        f"SELECT quarter FROM {CATALOG}.ops.quarter_status WHERE stage='{stage}' AND status='complete'").collect()}


QUARTER = dbutils.widgets.get("quarter") or next(
    (q for q in QUARTERS if q in done("silver") and q not in done("features")), None)
if QUARTER is None:
    dbutils.notebook.exit(json.dumps({"status": "nothing to do"}))
assert QUARTER in done("silver")
qn, yr = int(QUARTER[1]), int(QUARTER[3:])
Q_START = date(yr, 3 * qn - 2, 1)
Q_END = date(yr + (qn == 4), 1 if qn == 4 else 3 * qn + 1, 1) - timedelta(days=1)
silver_quarters = sorted(done("silver"), key=QUARTERS.index)
prev_q = QUARTERS[QUARTERS.index(QUARTER) - 1] if QUARTERS.index(QUARTER) > 0 else None
has_prev = prev_q in silver_quarters
if has_prev:
    assert prev_q in done("features"), f"features for previous quarter {prev_q} must be built first"
print(QUARTER, Q_START, Q_END, "previous quarter features:", prev_q if has_prev else None)

lt = spark.table(LT)
WINDOW_END = lt.agg(F.max("window_end")).first()[0]
assert WINDOW_END >= Q_END, "drive_lifetimes is stale: rebuild it (notebook 30) after silver"

# COMMAND ----------

cols = ["serial_number", "date"] + [f"smart_{a}_raw" for a in TREND_ATTRS + [194]]
src = (spark.table(SILVER).where("is_data_drive")
       .where(F.col("date").between(F.lit(Q_START - timedelta(days=30)), F.lit(Q_END)))
       .select(*cols).withColumn("t", F.datediff("date", F.lit("1970-01-01"))))

w7 = Window.partitionBy("serial_number").orderBy("t").rangeBetween(-7, 0)
w30 = Window.partitionBy("serial_number").orderBy("t").rangeBetween(-30, 0)
wcum = Window.partitionBy("serial_number").orderBy("t").rangeBetween(Window.unboundedPreceding, 0)

f = src
for a in TREND_ATTRS:
    v = F.col(f"smart_{a}_raw")
    f = (f.withColumn(f"s{a}", v)
          .withColumn(f"s{a}_d7", F.when(v.isNotNull(), v - F.first(v, ignorenulls=True).over(w7)).cast("double"))
          .withColumn(f"s{a}_d30", F.when(v.isNotNull(), v - F.first(v, ignorenulls=True).over(w30)).cast("double"))
          .withColumn(f"_ever_local_{a}", F.max(F.when(v > 0, 1).otherwise(0)).over(wcum)))
f = f.withColumn("temp_max30", F.max("smart_194_raw").over(w30).cast("double"))

if has_prev:
    prev = (spark.table(TABLE).where(F.col("quarter") == prev_q).groupBy("serial_number")
            .agg(*[F.max(f"s{a}_ever").alias(f"_ever_prev_{a}") for a in TREND_ATTRS]))
    f = f.join(prev, "serial_number", "left")
else:
    for a in TREND_ATTRS:
        f = f.withColumn(f"_ever_prev_{a}", F.lit(0))
for a in TREND_ATTRS:
    f = f.withColumn(f"s{a}_ever", F.greatest(F.col(f"_ever_local_{a}"), F.coalesce(F.col(f"_ever_prev_{a}"), F.lit(0))))
f = (f.withColumn("any_crit_now", F.greatest(*[F.when(F.col(f"s{a}") > 0, 1).otherwise(0) for a in CRITICAL]))
      .withColumn("any_crit_ever", F.greatest(*[F.col(f"s{a}_ever") for a in CRITICAL])))

feat_cols = [c for a in TREND_ATTRS for c in (f"s{a}", f"s{a}_d7", f"s{a}_d30", f"s{a}_ever")] + \
            ["temp_max30", "any_crit_now", "any_crit_ever"]

# Labels from drive_lifetimes (failure date known up to the current window end)
def with_labels(df):
    j = df.join(lt.select("serial_number", "failure_date"), "serial_number", "left")
    j = j.withColumn("days_to_failure", F.datediff("failure_date", "date"))
    for h in HORIZONS:
        j = (j.withColumn(f"fail_{h}d", F.when(F.col("days_to_failure").between(0, h - 1), 1).otherwise(0))
              .withColumn(f"label_{h}d_known", F.col("failure_date").isNotNull()
                          | (F.date_add("date", h - 1) <= F.lit(WINDOW_END))))
    return j.drop("failure_date")

meta = lt.select("serial_number", "model", "manufacturer", "capacity_bytes", "first_date", "entry_age_days", "age_ok")
out = (with_labels(f.where(F.col("date").between(F.lit(Q_START), F.lit(Q_END))).select("serial_number", "date", *feat_cols))
       .join(meta, "serial_number", "left")
       .withColumn("age_days", F.when(F.col("age_ok") == 1, F.col("entry_age_days") + F.datediff("date", "first_date")))
       .drop("first_date", "entry_age_days", "age_ok")
       .withColumn("quarter", F.lit(QUARTER)))

(out.write.format("delta").mode("overwrite").option("replaceWhere", f"quarter = '{QUARTER}'")
    .option("mergeSchema", True).partitionBy("quarter").saveAsTable(TABLE))

# Refresh labels for the previous quarter's tail (failures in this quarter can turn them positive / known)
relabeled = 0
if has_prev:
    tail_start = Q_START - timedelta(days=31)
    fresh = with_labels(spark.table(TABLE).where(F.col("date") >= F.lit(tail_start)).where(F.col("quarter") == prev_q)
                        .select("serial_number", "date"))
    fresh.createOrReplaceTempView("fresh_labels")
    sets = ", ".join(f"t.{c} = s.{c}" for c in ["days_to_failure"] + [f"fail_{h}d" for h in HORIZONS] + [f"label_{h}d_known" for h in HORIZONS])
    spark.sql(f"""MERGE INTO {TABLE} t USING fresh_labels s
                  ON t.quarter = '{prev_q}' AND t.date >= DATE'{tail_start}' AND t.serial_number = s.serial_number AND t.date = s.date
                  WHEN MATCHED THEN UPDATE SET {sets}""")
    relabeled = fresh.count()

# COMMAND ----------

# Checks
q = spark.table(TABLE).where(F.col("quarter") == QUARTER)
silver_data_rows = spark.table(SILVER).where("is_data_drive").where(F.col("date").between(F.lit(Q_START), F.lit(Q_END))).count()
stats = q.agg(F.count("*").alias("rows"), F.countDistinct("serial_number", "date").alias("keys"),
              F.countDistinct("serial_number").alias("drives"),
              *[F.sum(f"fail_{h}d").alias(f"pos_{h}d") for h in HORIZONS],
              *[F.sum(F.when(~F.col(f"label_{h}d_known"), 1).otherwise(0)).alias(f"unknown_{h}d") for h in HORIZONS],
              F.sum(F.when(F.col("days_to_failure") < 0, 1).otherwise(0)).alias("rows_after_failure")).first().asDict()
assert stats["rows"] == stats["keys"] == silver_data_rows, (stats, silver_data_rows)
assert stats["rows_after_failure"] == 0

# Reference comparison on sampled drives: Spark vs pandas reference computed from full silver history
failed_ids = [r.serial_number for r in q.where("fail_30d = 1").select("serial_number").distinct().limit(60).collect()]
random_ids = [r.serial_number for r in q.select("serial_number").distinct().orderBy(F.rand(7)).limit(140).collect()]
sample = list(set(failed_ids + random_ids))
hist = (spark.table(SILVER).where(F.col("serial_number").isin(sample)).where(F.col("date") <= F.lit(Q_END))
        .select(*cols).toPandas())
hist["date"] = pd.to_datetime(hist["date"])
ref = compute_features(hist)
ref = ref[(ref["date"] >= pd.Timestamp(Q_START)) & (ref["date"] <= pd.Timestamp(Q_END))]
fd = lt.where(F.col("serial_number").isin(sample)).where("failed = 1").select("serial_number", "failure_date").toPandas()
labs = compute_labels(ref[["serial_number", "date"]], pd.Series(pd.to_datetime(fd["failure_date"]).values, index=fd["serial_number"]), WINDOW_END)
ref = ref.merge(labs, on=["serial_number", "date"])
got = q.where(F.col("serial_number").isin(sample)).toPandas()
got["date"] = pd.to_datetime(got["date"])
m = ref.merge(got, on=["serial_number", "date"], suffixes=("_ref", "_spark"), how="outer", indicator=True)
assert (m["_merge"] == "both").all(), m["_merge"].value_counts().to_dict()
mismatch = {}
for c in feat_cols + [f"fail_{h}d" for h in HORIZONS] + [f"label_{h}d_known" for h in HORIZONS]:
    a, b = m[f"{c}_ref"].astype(float).to_numpy(), m[f"{c}_spark"].astype(float).to_numpy()
    bad = ~((np.isnan(a) & np.isnan(b)) | np.isclose(a, b))
    if bad.any():
        mismatch[c] = int(bad.sum())
stats.update(reference_check_drives=len(sample), reference_check_rows=len(m), reference_mismatches=mismatch,
             previous_quarter_rows_relabeled=relabeled, window_end=str(WINDOW_END))
print(json.dumps(stats, indent=2, default=str))
assert not mismatch, f"Spark features differ from the reference implementation: {mismatch}"

spark.sql(f"DELETE FROM {CATALOG}.ops.quarter_status WHERE quarter = '{QUARTER}' AND stage = 'features'")
spark.createDataFrame(
    [(QUARTER, "features", "complete", stats["rows"], json.dumps(stats, default=str), datetime.now(timezone.utc))],
    "quarter string, stage string, status string, row_count bigint, details string, completed_at timestamp",
).write.mode("append").saveAsTable(f"{CATALOG}.ops.quarter_status")
dbutils.notebook.exit(json.dumps({"quarter": QUARTER, **stats}, default=str))
