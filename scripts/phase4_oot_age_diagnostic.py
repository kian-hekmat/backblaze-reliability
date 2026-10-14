"""Diagnostic for the out-of-time misses: does the shared (cross-sectional) age curve cause systematic over-prediction?

Refits the out-of-time check (train Q3 2023-Q2 2025, test Q3 2025-Q2 2026) with the age effect removed (all cells in one
age bucket) and compares the actual / predicted ratio with the age-aware fit. Writes results/phase4/oot_age_diagnostic.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import numpyro
import pandas as pd

numpyro.set_host_device_count(4)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reliability import bayes  # noqa: E402

QUARTERS = ["Q3_2023", "Q4_2023", "Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024",
            "Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]
mas = pd.read_parquet(ROOT / "data/exports/model_age_stats")
cells = mas[mas["is_data_drive"]][["model", "manufacturer", "quarter", "age_year", "drive_days", "failures"]]
cells = cells[cells["age_year"] >= 0]
out = {}
for name, c in [("age_aware", cells), ("no_age_effect", cells.assign(age_year=0))]:
    prep = bayes.prepare(c[c["quarter"].isin(QUARTERS[:8])], overdispersion=True)
    mcmc = bayes.fit(prep, seed=1, num_warmup=1000, num_samples=1000, num_chains=4)
    pred = bayes.predict_counts(prep, mcmc, c[c["quarter"].isin(QUARTERS[8:])])
    big = pred[pred["drive_days"] >= 1_000_000]
    ratio = big["actual"] / big["pred_median"]
    out[name] = {"coverage_90_all": float(pred["covered"].mean()), "models": len(pred),
                 "below": int((pred["actual"] < pred["pred_lo"]).sum()), "above": int((pred["actual"] > pred["pred_hi"]).sum()),
                 "big_models": len(big), "big_median_actual_over_pred": float(ratio.median()),
                 "big_total_actual": int(big["actual"].sum()), "big_total_pred_median": float(big["pred_median"].sum()),
                 "divergences": bayes.diagnostics(mcmc)["divergences"]}
    pred.to_csv(ROOT / f"results/phase4/oot_predictions_{name}.csv", index=False)
    print(name, out[name])
(ROOT / "results/phase4/oot_age_diagnostic.json").write_text(json.dumps(out, indent=2))
