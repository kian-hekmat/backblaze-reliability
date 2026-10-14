"""Upload local modeling results to the Databricks results volume, with a row-count manifest.

Each entry maps a results table name (loaded as backblaze.gold.res_<name> by notebook 50_load_results)
to a local CSV or Parquet file. Usage: uv run python scripts/push_results.py
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parents[1]
PROFILE = os.environ.get("DATABRICKS_PROFILE", "kianhekmatnejad")
VOL = "dbfs:/Volumes/backblaze/gold/results"
RESULTS = {
    "bayes_estimates": "results/phase4/bayes_estimates.csv",
    "bayes_age_effect": "results/phase4/bayes_age_effect.csv",
    "km_by_model": "results/phase4/km_by_model.csv",
    "km_by_manufacturer": "results/phase4/km_by_manufacturer.csv",
    "weibull_by_model": "results/phase4/weibull_by_model.csv",
    "out_of_time_predictions": "results/phase4/out_of_time_predictions.csv",
    "ew_metrics_30d": "results/phase5/metrics_30d.csv",
    "ew_metrics_by_manufacturer_30d": "results/phase5/metrics_by_manufacturer_30d.csv",
    "ew_tradeoff_30d": "results/phase5/tradeoff_30d.csv",
    "ew_lead_times_30d": "results/phase5/lead_times_30d.csv",
    "ew_feature_importance_30d": "results/phase5/feature_importance_30d.csv",
    "ew_test_scores_30d": "data/results/ew_test_scores_30d.parquet",   # drive-day scores, test period only
}


def cp(src, dst):
    subprocess.run(["databricks", "-p", PROFILE, "fs", "cp", str(src), dst, "--overwrite"], check=True, capture_output=True)


manifest = {}
for name, rel in RESULTS.items():
    p = ROOT / rel
    if not p.exists():
        print(f"[skip] {name}: {rel} not found")
        continue
    rows = ds.dataset(p, format="parquet").count_rows() if p.suffix == ".parquet" else len(pd.read_csv(p))
    cp(p, f"{VOL}/{name}{p.suffix}")
    manifest[name] = {"file": f"{name}{p.suffix}", "rows": rows}
    print(f"[ok] {name}: {rows} rows")
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
    json.dump(manifest, fh, indent=2)
cp(fh.name, f"{VOL}/_manifest.json")
