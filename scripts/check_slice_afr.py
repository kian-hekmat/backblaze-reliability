"""Phase 2 check: per-model AFR from the raw quarter (pandas) vs. the pipeline's result in Snowflake.

The pandas path reads the raw CSV-derived Parquet cache written by profile_quarter.py (no Databricks
involvement), applies the same documented rules (model normalization, dedup on (date, serial)),
and aggregates. Snowflake numbers come from BACKBLAZE.GOLD.MODEL_PERIOD_STATS.

Writes results/phase2_afr_reconciliation.csv and results/phase2_afr_reconciliation.json.
Usage: uv run python scripts/check_slice_afr.py data/work/Q2_2026_raw.parquet Q2_2026
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reliability.afr import afr_table  # noqa: E402
from reliability.normalize import normalize_model  # noqa: E402

path, quarter = sys.argv[1], sys.argv[2]
raw = pq.read_table(path, columns=["date", "serial_number", "model", "failure"]).to_pandas()
raw["failure"] = raw["failure"].astype(int)
raw_rows = len(raw)
raw = raw.sort_values("failure", ascending=False).drop_duplicates(["date", "serial_number"])
mapping = {m: normalize_model(m)[0] for m in raw["model"].unique()}
raw["model"] = raw["model"].map(mapping)
pandas_t = afr_table(raw, ["model"])

res = json.loads(subprocess.run(
    ["snow", "sql", "--format", "json", "-q",
     "USE ROLE ANALYST_READER; USE SECONDARY ROLES NONE; USE WAREHOUSE BI_WH; "
     f"SELECT MODEL, DRIVE_COUNT, DRIVE_DAYS, FAILURES, AFR_PCT FROM BACKBLAZE.GOLD.MODEL_PERIOD_STATS WHERE QUARTER = '{quarter}'"],
    check=True, capture_output=True, text=True).stdout)
sf = pd.DataFrame(next(r for r in reversed(res) if r and "MODEL" in r[0]))
sf.columns = [c.lower() for c in sf.columns]
sf = sf.astype({"drive_count": int, "drive_days": int, "failures": int, "afr_pct": float})

m = pandas_t.merge(sf, on="model", how="outer", suffixes=("_pandas", "_snowflake"), indicator=True)
for c in ["drive_count", "drive_days", "failures"]:
    m[f"{c}_match"] = m[f"{c}_pandas"] == m[f"{c}_snowflake"]
m["afr_match"] = np.isclose(m["afr_pct_pandas"], m["afr_pct_snowflake"], rtol=1e-9, atol=1e-12)
m.drop(columns="_merge").to_csv(ROOT / "results/phase2_afr_reconciliation.csv", index=False)

summary = {
    "quarter": quarter, "raw_rows": raw_rows, "rows_after_dedup": len(raw),
    "models_pandas": len(pandas_t), "models_snowflake": len(sf),
    "models_in_both": int((m["_merge"] == "both").sum()),
    "all_drive_counts_match": bool(m["drive_count_match"].all()),
    "all_drive_days_match": bool(m["drive_days_match"].all()),
    "all_failures_match": bool(m["failures_match"].all()),
    "all_afr_match": bool(m["afr_match"].all()),
    "total_drive_days_pandas": int(pandas_t["drive_days"].sum()),
    "total_drive_days_snowflake": int(sf["drive_days"].sum()),
    "total_failures_pandas": int(pandas_t["failures"].sum()),
    "total_failures_snowflake": int(sf["failures"].sum()),
}
(ROOT / "results/phase2_afr_reconciliation.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
sys.exit(0 if all(summary[k] for k in summary if k.startswith("all_")) else 1)
