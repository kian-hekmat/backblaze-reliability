"""Phase 4 verification: 90% interval coverage of the hierarchical model (with model x quarter overdispersion)
on synthetic fleets with known rates and true quarter-to-quarter drift (sigma_mq = 0.3).

Uses the generator from tests/test_bayes.py. Writes results/phase4/bayes_synthetic_coverage.json.
Usage: uv run python scripts/bayes_synthetic_coverage.py [n_sims]
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from reliability.bayes import diagnostics, fit, model_estimates, prepare  # noqa: E402
from test_bayes import synth_fleet  # noqa: E402

n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 40
per_sim, by_size = [], {}
for seed in range(n_sims):
    df, truth, _ = synth_fleet(1000 + seed, sigma_mq=0.3)   # data with true quarter-to-quarter drift
    prep = prepare(df, overdispersion=True)
    mcmc = fit(prep, num_warmup=500, num_samples=500, num_chains=1, seed=seed)
    est = model_estimates(prep, mcmc)
    est["truth"] = est["model"].map(truth)
    est["covered"] = (est["afr_observed_mix_lo"] <= est["truth"]) & (est["truth"] <= est["afr_observed_mix_hi"])
    d = diagnostics(mcmc)
    per_sim.append({"seed": 1000 + seed, "coverage": float(est["covered"].mean()), "n_models": len(est),
                    "divergences": d["divergences"], "max_r_hat": d["max_r_hat"]})
    for dd, g in est.assign(size=est["drive_days"] // 8).groupby("size"):  # drive-days per quarter
        by_size.setdefault(int(dd), []).extend(g["covered"].tolist())
cov = [c for s in per_sim for c in [s["coverage"]] * s["n_models"]]
out = {"n_sims": n_sims, "nominal": 0.9,
       "overall_coverage": float(np.mean([s["coverage"] for s in per_sim])),
       "coverage_by_model_drive_days": {k: float(np.mean(v)) for k, v in sorted(by_size.items())},
       "sims_with_divergences": int(sum(s["divergences"] > 0 for s in per_sim)),
       "max_r_hat_over_sims": float(max(s["max_r_hat"] for s in per_sim)),
       "per_sim": per_sim}
(ROOT / "results/phase4").mkdir(parents=True, exist_ok=True)
(ROOT / "results/phase4/bayes_synthetic_coverage.json").write_text(json.dumps(out, indent=2))
print({k: out[k] for k in ["n_sims", "overall_coverage", "coverage_by_model_drive_days", "sims_with_divergences", "max_r_hat_over_sims"]})
