"""Do out-of-time forecast errors line up with each model's Weibull hazard shape?

For models with both an out-of-time prediction (main model) and a Weibull fit, relate log(actual / predicted median)
to the Weibull shape k (k > 1: wear-out, k < 1: early-life). Weibull is fit on the full window, which includes the
test year, so this is an explanation of the misses, not a forecast. Writes results/phase4/oot_vs_hazard.{csv,json}.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
p = pd.read_csv(ROOT / "results/phase4/out_of_time_predictions_main_overdispersed_no_age.csv")
w = pd.read_csv(ROOT / "results/phase4/weibull_by_model.csv")
m = p.merge(w[["model", "shape_k", "shape_lo95", "shape_hi95", "hazard_shape"]], on="model")
m = m[m["pred_median"] > 0]
m["log_ratio"] = np.log((m["actual"] + 0.5) / (m["pred_median"] + 0.5))
m["miss"] = np.where(m["actual"] > m["pred_hi"], "above", np.where(m["actual"] < m["pred_lo"], "below", "covered"))
m.to_csv(ROOT / "results/phase4/oot_vs_hazard.csv", index=False)
rho, pval = spearmanr(m["shape_k"], m["log_ratio"])
out = {"models": len(m), "spearman_rho_shape_vs_log_actual_over_pred": float(rho), "p_value": float(pval),
       "median_k_by_outcome": m.groupby("miss")["shape_k"].median().to_dict(),
       "counts_by_outcome_and_hazard": m.groupby(["miss", "hazard_shape"]).size().unstack(fill_value=0).to_dict()}
(ROOT / "results/phase4/oot_vs_hazard.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
print(m.sort_values("shape_k")[["model", "shape_k", "hazard_shape", "pred_median", "actual", "miss"]].round(2).to_string(index=False))
