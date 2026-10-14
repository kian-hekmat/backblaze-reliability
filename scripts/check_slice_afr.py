"""Phase 2 check: per-model AFR from the raw quarter (pandas) vs. the pipeline's serving view in Databricks.

The pandas path reads the raw CSV-derived Parquet cache written by profile_quarter.py (no Databricks
involvement), applies the same documented rules (model normalization, dedup on (date, serial)),
and aggregates. Pipeline numbers come from backblaze.analytics.model_quarter_afr plus non-data drives from
backblaze.gold.model_period_stats (all 80 models are compared).

Writes results/phase2_afr_reconciliation.csv and results/phase2_afr_reconciliation.json.
Usage: uv run python scripts/check_slice_afr.py data/work/Q2_2026_raw.parquet Q2_2026
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reliability.afr import afr_table  # noqa: E402
from reliability.normalize import normalize_model  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from dbsql import run  # noqa: E402

path, quarter = sys.argv[1], sys.argv[2]
raw = pq.read_table(path, columns=["date", "serial_number", "model", "failure"]).to_pandas()
raw["failure"] = raw["failure"].astype(int)
raw_rows = len(raw)
raw = raw.sort_values("failure", ascending=False).drop_duplicates(["date", "serial_number"])
mapping = {m: normalize_model(m)[0] for m in raw["model"].unique()}
raw["model"] = raw["model"].map(mapping)
pandas_t = afr_table(raw, ["model"])

cols, rows = run(f"""
    SELECT model, drive_count, drive_days, failures, afr_pct FROM backblaze.analytics.model_quarter_afr WHERE quarter = '{quarter}'
    UNION ALL
    SELECT model, drive_count, drive_days, failures, failures / (CAST(drive_days AS DOUBLE) / 365) * 100
    FROM backblaze.gold.model_period_stats WHERE quarter = '{quarter}' AND NOT is_data_drive""")
sf = pd.DataFrame(rows, columns=cols).astype({"drive_count": int, "drive_days": int, "failures": int, "afr_pct": float})

m = pandas_t.merge(sf, on="model", how="outer", suffixes=("_pandas", "_pipeline"), indicator=True)
for c in ["drive_count", "drive_days", "failures"]:
    m[f"{c}_match"] = m[f"{c}_pandas"] == m[f"{c}_pipeline"]
m["afr_match"] = np.isclose(m["afr_pct_pandas"], m["afr_pct_pipeline"], rtol=1e-9, atol=1e-12)
m.drop(columns="_merge").to_csv(ROOT / "results/phase2_afr_reconciliation.csv", index=False)

summary = {
    "quarter": quarter, "raw_rows": raw_rows, "rows_after_dedup": len(raw),
    "models_pandas": len(pandas_t), "models_pipeline": len(sf),
    "models_in_both": int((m["_merge"] == "both").sum()),
    "all_drive_counts_match": bool(m["drive_count_match"].all()),
    "all_drive_days_match": bool(m["drive_days_match"].all()),
    "all_failures_match": bool(m["failures_match"].all()),
    "all_afr_match": bool(m["afr_match"].all()),
    "total_drive_days_pandas": int(pandas_t["drive_days"].sum()),
    "total_drive_days_pipeline": int(sf["drive_days"].sum()),
    "total_failures_pandas": int(pandas_t["failures"].sum()),
    "total_failures_pipeline": int(sf["failures"].sum()),
}
(ROOT / "results/phase2_afr_reconciliation.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
sys.exit(0 if all(summary[k] for k in summary if k.startswith("all_")) else 1)
