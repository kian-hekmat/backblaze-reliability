"""External validation: pipeline per-model quarterly stats vs Backblaze's published Drive Stats tables.

Pass criterion (DECISIONS, approved change 4): drive counts and drive-days match exactly for every published
model; failure-count differences are listed (and explained in RESULTS/DECISIONS), not hidden.

Writes results/validation/afr_validation_<quarter>.csv and results/validation/afr_validation_summary.json.
Usage: uv run python scripts/validate_vs_backblaze.py Q1_2026 Q2_2026
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dbsql import run  # noqa: E402

summary = {}
for quarter in sys.argv[1:]:
    pub = pd.read_csv(ROOT / f"results/validation/backblaze_published_{quarter.lower()}.csv")
    cols, rows = run(f"""SELECT model_short, drive_count, drive_days, failures
                         FROM backblaze.analytics.model_quarter_afr WHERE quarter = '{quarter}'""")
    ours = pd.DataFrame(rows, columns=cols).astype({"drive_count": int, "drive_days": int, "failures": int})
    m = pub.merge(ours, on="model_short", how="left", suffixes=("_backblaze", "_pipeline"))
    for c in ["drive_count", "drive_days", "failures"]:
        m[f"{c}_diff"] = m[f"{c}_pipeline"] - m[f"{c}_backblaze"]
    m["afr_pipeline"] = m["failures_pipeline"] / (m["drive_days_pipeline"] / 365) * 100
    m.to_csv(ROOT / f"results/validation/afr_validation_{quarter}.csv", index=False)
    summary[quarter] = {
        "published_models": len(pub),
        "models_found_in_pipeline": int(m["drive_days_pipeline"].notna().sum()),
        "drive_count_exact": int((m["drive_count_diff"] == 0).sum()),
        "drive_days_exact": int((m["drive_days_diff"] == 0).sum()),
        "failures_exact": int((m["failures_diff"] == 0).sum()),
        "failures_total_backblaze": int(pub["failures"].sum()),
        "failures_total_pipeline_same_models": int(m["failures_pipeline"].sum()),
        "models_with_failure_diff": m.loc[m["failures_diff"] != 0, ["model_short", "failures_backblaze",
                                          "failures_pipeline", "failures_diff"]].to_dict("records"),
        "models_with_count_or_days_diff": m.loc[(m["drive_count_diff"] != 0) | (m["drive_days_diff"] != 0),
                                                ["model_short", "drive_count_diff", "drive_days_diff"]].to_dict("records"),
    }
out = ROOT / "results/validation/afr_validation_summary.json"
prev = json.loads(out.read_text()) if out.exists() else {}
prev.update(summary)
out.write_text(json.dumps(prev, indent=2, default=int))
print(json.dumps(summary, indent=2, default=int))
