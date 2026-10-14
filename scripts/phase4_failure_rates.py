"""Phase 4: failure rates and survival on the full gold scope (data drives only).

Inputs: data/exports/{drive_lifetimes, model_period_stats, model_age_stats} (scripts/pull_exports.py).
Outputs under results/phase4/:
  afr_baseline_window.csv / afr_baseline_quarter.csv    raw AFR (Backblaze formula)
  km_by_model.csv / km_by_manufacturer.csv              Kaplan-Meier by age, delayed entry + right-censoring
  weibull_by_model.csv                                  hazard shape (decreasing / constant / increasing)
  bayes_estimates.csv, bayes_age_effect.csv, bayes_diagnostics.json
  bayes_vs_raw_disagreement.csv                         where pooling changes the answer most
  out_of_time_predictions.csv, out_of_time_summary.json fit on first 8 quarters, predict the last 4
Usage: uv run python scripts/phase4_failure_rates.py [--quick]
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
from reliability.afr import afr  # noqa: E402
from reliability.survival import km_curve, weibull_fit  # noqa: E402

QUICK = "--quick" in sys.argv
OUT = ROOT / "results/phase4"
OUT.mkdir(parents=True, exist_ok=True)
EXP = ROOT / "data/exports"
QUARTERS = ["Q3_2023", "Q4_2023", "Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024",
            "Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]
MIN_DRIVES_KM, MIN_FAILURES_WEIBULL, MIN_AT_RISK = 500, 30, 100
MCMC_KW = dict(num_warmup=300, num_samples=300, num_chains=2) if QUICK else dict(num_warmup=1500, num_samples=1000, num_chains=4, target_accept=0.99)

lt = pd.read_parquet(EXP / "drive_lifetimes")
mps = pd.read_parquet(EXP / "model_period_stats")
mas = pd.read_parquet(EXP / "model_age_stats")
lt, mps, mas = lt[lt["is_data_drive"]], mps[mps["is_data_drive"]], mas[mas["is_data_drive"]]
quarters_present = [q for q in QUARTERS if q in set(mps["quarter"])]
print("quarters:", quarters_present)

# 1. Raw AFR ---------------------------------------------------------------------------------------------
q = mps.groupby(["quarter", "manufacturer", "model", "model_short"], as_index=False)[["drive_count", "drive_days", "failures"]].sum()
q["afr_pct"] = afr(q["failures"], q["drive_days"])
q.to_csv(OUT / "afr_baseline_quarter.csv", index=False)
w = mps.groupby(["manufacturer", "model", "model_short"], as_index=False)[["drive_days", "failures"]].sum()
w = w.merge(lt.groupby("model").size().rename("drives").reset_index(), on="model")
w["afr_pct"] = afr(w["failures"], w["drive_days"])
w.sort_values("afr_pct", ascending=False).to_csv(OUT / "afr_baseline_window.csv", index=False)

# 2. Kaplan-Meier by age (years), delayed entry ------------------------------------------------------------
surv = lt[lt["age_ok"] == 1].assign(entry=lambda d: d["entry_age_days"] / 365.25,
                                    exit=lambda d: d["exit_age_days"] / 365.25)
grid = np.round(np.arange(0, 12.01, 0.25), 2)
km_rows = []
for model, g in surv.groupby("model"):
    if len(g) < MIN_DRIVES_KM:
        continue
    k = km_curve(g["entry"], g["exit"], g["failed"], grid=grid[grid <= g["exit"].max()], min_at_risk=MIN_AT_RISK)
    k = k[k["survival"].notna()]
    km_rows.append(k.assign(model=model, manufacturer=g["manufacturer"].iloc[0], drives=len(g), failures=int(g["failed"].sum())))
pd.concat(km_rows).to_csv(OUT / "km_by_model.csv", index=False)
km_m = []
for mfr, g in surv.groupby("manufacturer"):
    k = km_curve(g["entry"], g["exit"], g["failed"], grid=grid[grid <= g["exit"].max()], min_at_risk=MIN_AT_RISK)
    km_m.append(k[k["survival"].notna()].assign(manufacturer=mfr, drives=len(g), failures=int(g["failed"].sum())))
pd.concat(km_m).to_csv(OUT / "km_by_manufacturer.csv", index=False)

# 3. Weibull hazard shape per model ------------------------------------------------------------------------
wb = []
for model, g in surv.groupby("model"):
    if g["failed"].sum() < MIN_FAILURES_WEIBULL:
        continue
    f = weibull_fit(g["entry"], g["exit"], g["failed"])
    wb.append({"model": model, "manufacturer": g["manufacturer"].iloc[0], "drives": f.n, "failures": f.events,
               "shape_k": f.shape, "shape_lo95": f.shape_ci[0], "shape_hi95": f.shape_ci[1],
               "scale_years": f.scale, "hazard_shape": f.hazard_shape,
               "entry_age_median": g["entry"].median(), "exit_age_max": g["exit"].max()})
pd.DataFrame(wb).sort_values("shape_k").to_csv(OUT / "weibull_by_model.csv", index=False)

# 4. Hierarchical Bayes on the full window -------------------------------------------------------------------
# Main model: Poisson with model x quarter overdispersion (DECISIONS 2026-10-14). The Poisson-only model as
# originally specified is fitted too, for the out-of-time comparison.
cells = mas[["model", "manufacturer", "quarter", "age_year", "drive_days", "failures"]]
excluded_unknown_age = int(cells.loc[cells["age_year"] < 0, "drive_days"].sum())
tr = mps.groupby(["model", "quarter"], as_index=False)[["drive_days", "failures"]].sum()
q_disp = []
for m_, g in tr[tr["quarter"].isin(QUARTERS[:8])].groupby("model"):
    if g["drive_days"].sum() >= 1e6 and len(g) >= 6:
        rate = g["failures"].sum() / g["drive_days"].sum()
        exp_ = g["drive_days"] * rate
        q_disp.append({"model": m_, "quarters": len(g), "failures": int(g["failures"].sum()),
                       "dispersion_index": float(((g["failures"] - exp_) ** 2 / exp_).sum() / (len(g) - 1))})
pd.DataFrame(q_disp).sort_values("dispersion_index", ascending=False).to_csv(OUT / "overdispersion_train_quarters.csv", index=False)

prep = bayes.prepare(cells, overdispersion=True)
mcmc = bayes.fit(prep, seed=0, **MCMC_KW)
diag = bayes.diagnostics(mcmc)
diag.update(model="poisson + model x quarter overdispersion", sigma_mq_median=float(np.median(mcmc.get_samples()["sigma_mq"])),
            excluded_unknown_age_drive_days=excluded_unknown_age, mcmc=MCMC_KW, n_models=len(prep.models),
            n_cells=len(prep.cells), quarters=quarters_present)
(OUT / "bayes_diagnostics.json").write_text(json.dumps(diag, indent=2))
est = bayes.model_estimates(prep, mcmc)
est.to_csv(OUT / "bayes_estimates.csv", index=False)
bayes.age_effect(mcmc).to_csv(OUT / "bayes_age_effect.csv", index=False)
est["abs_diff"] = (est["afr_observed_mix_median"] - est["raw_afr"]).abs()
est["interval_width"] = est["afr_observed_mix_hi"] - est["afr_observed_mix_lo"]
est.sort_values("abs_diff", ascending=False).to_csv(OUT / "bayes_vs_raw_disagreement.csv", index=False)
print("bayes diagnostics:", {k: diag[k] for k in ["max_r_hat", "min_ess", "divergences", "sigma_mq_median"]})

# 5. Out-of-time check: fit first 8 quarters, predict the last 4, for both model variants --------------------
if len(quarters_present) == 12:
    train_q, test_q = QUARTERS[:8], QUARTERS[8:]
    summ = {"train_quarters": train_q, "test_quarters": test_q}
    for name, od in [("overdispersed", True), ("poisson_only", False)]:
        prep_t = bayes.prepare(cells[cells["quarter"].isin(train_q)], overdispersion=od)
        mcmc_t = bayes.fit(prep_t, seed=1, **MCMC_KW)
        diag_t = bayes.diagnostics(mcmc_t)
        pred = bayes.predict_counts(prep_t, mcmc_t, cells[cells["quarter"].isin(test_q)])
        pred.to_csv(OUT / f"out_of_time_predictions_{name}.csv", index=False)
        summ[name] = {"models_predicted": len(pred), "coverage_90": float(pred["covered"].mean()),
                      "n_covered": int(pred["covered"].sum()),
                      "below_interval": int((pred["actual"] < pred["pred_lo"]).sum()),
                      "above_interval": int((pred["actual"] > pred["pred_hi"]).sum()),
                      "train_fit_diagnostics": {k: diag_t[k] for k in ["max_r_hat", "min_ess", "divergences"]}}
        print(f"out-of-time [{name}]:", {k: summ[name][k] for k in ["models_predicted", "coverage_90", "below_interval", "above_interval"]})
    held = cells[cells["quarter"].isin(test_q) & ~cells["model"].isin(prep_t.models["model"])]
    summ["models_in_test_not_in_train"] = sorted(held["model"].unique().tolist())
    (OUT / "out_of_time_summary.json").write_text(json.dumps(summ, indent=2))
else:
    print("out-of-time check skipped: needs all 12 quarters, have", len(quarters_present))

# 6. Sensitivity: MG08ACA16TEY Q3 2025 "cosmetic" failures (firmware-update pulls, per Backblaze) ------------
SENS_MODEL, SENS_Q = "TOSHIBA MG08ACA16TEY", "Q3_2025"
if SENS_Q in quarters_present:
    sq = q[q["model"] == SENS_MODEL].set_index("quarter")[["drive_days", "failures", "afr_pct"]]
    keep = cells[~((cells["model"] == SENS_MODEL) & (cells["quarter"] == SENS_Q))]
    prep_s = bayes.prepare(keep, overdispersion=True)
    est_s = bayes.model_estimates(prep_s, bayes.fit(prep_s, seed=2, **MCMC_KW))
    full_row = est[est["model"] == SENS_MODEL].iloc[0]
    sens_row = est_s[est_s["model"] == SENS_MODEL].iloc[0]
    others = est.set_index("model")["afr_observed_mix_median"]
    others_s = est_s.set_index("model")["afr_observed_mix_median"]
    shift = (others_s - others).drop(SENS_MODEL).abs()
    sens = {"model": SENS_MODEL, "excluded_quarter": SENS_Q,
            "by_quarter": sq.reset_index().to_dict("records"),
            "raw_afr_window_with": float(afr(sq["failures"].sum(), sq["drive_days"].sum())),
            "raw_afr_window_without": float(afr(sq.drop(SENS_Q)["failures"].sum(), sq.drop(SENS_Q)["drive_days"].sum())),
            "bayes_with": {k: float(full_row[k]) for k in ["afr_observed_mix_lo", "afr_observed_mix_median", "afr_observed_mix_hi"]},
            "bayes_without": {k: float(sens_row[k]) for k in ["afr_observed_mix_lo", "afr_observed_mix_median", "afr_observed_mix_hi"]},
            "max_shift_other_models_median_afr": float(shift.max())}
    (OUT / "sensitivity_mg08aca16tey.json").write_text(json.dumps(sens, indent=2, default=float))
    print("sensitivity:", {k: sens[k] for k in ["raw_afr_window_with", "raw_afr_window_without", "max_shift_other_models_median_afr"]})
