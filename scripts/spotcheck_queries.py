"""Spot-check every analysis query (results/sql/qNN_*.csv, computed in Databricks SQL) against the same numbers
computed independently in pandas from local exports and results files. Writes results/sql/spotcheck.json.

Usage: uv run python scripts/spotcheck_queries.py   (needs data/exports from pull_exports.py and data/results scores)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SQL, EXP, P4, P5 = ROOT / "results/sql", ROOT / "data/exports", ROOT / "results/phase4", ROOT / "results/phase5"
q = {f.stem.split("_")[0]: pd.read_csv(f) for f in sorted(SQL.glob("q*.csv"))}
mps = pd.read_parquet(EXP / "model_period_stats")
mps = mps[mps["is_data_drive"]]
mas = pd.read_parquet(EXP / "model_age_stats")
mas = mas[mas["is_data_drive"]]
lt = pd.read_parquet(EXP / "drive_lifetimes", columns=["model", "manufacturer", "is_data_drive", "failed"])
checks = []


def check(query, what, sql_value, pandas_value, tol=1e-6):
    ok = bool(np.isclose(float(sql_value), float(pandas_value), rtol=tol, atol=tol))
    checks.append({"query": query, "check": what, "sql": float(sql_value), "pandas": float(pandas_value), "match": ok})


# q01: Backblaze-rule model-quarters
sel = mps[(mps["drive_count"] > 100) & (mps["drive_days"] > 10000)]
check("q01", "rows (model-quarters passing Backblaze rule)", len(q["q01"]), len(sel))
check("q01", "total failures", q["q01"]["failures"].sum(), sel["failures"].sum())
# q02: manufacturer x capacity
cap = mps.assign(capacity_tb=(mps["capacity_bytes"] / 1e12).round()).groupby(["manufacturer", "capacity_tb"])
check("q02", "rows", len(q["q02"]), cap.ngroups)
check("q02", "total drive_days", q["q02"]["drive_days"].sum(), mps["drive_days"].sum())
# q03: age-year AFR (>= 10,000 drive-days)
ay = mas[mas["age_year"] >= 0].groupby(["manufacturer", "age_year"])[["drive_days", "failures"]].sum()
ay = ay[ay["drive_days"] >= 10000]
check("q03", "rows", len(q["q03"]), len(ay))
check("q03", "total failures", q["q03"]["failures"].sum(), ay["failures"].sum())
# q04: failed data drives per manufacturer
fd = lt[lt["is_data_drive"] & (lt["failed"] == 1)].groupby("manufacturer").size()
check("q04", "failed data drives (all manufacturers)", q["q04"]["failed_drives"].sum(), fd.sum())
# q05: fleet composition
check("q05", "total drive_days", q["q05"]["drive_days"].sum(), mps["drive_days"].sum())
check("q05", "total failures", q["q05"]["failures"].sum(), mps["failures"].sum())
# q06 / q07: Bayesian estimates
be = pd.read_csv(P4 / "bayes_estimates.csv")
check("q06", "rows", len(q["q06"]), len(be))
check("q06", "max posterior median AFR (2 dp)", q["q06"]["bayes_afr"].max(), round(be["afr_observed_mix_median"].max(), 2), tol=1e-9)
dis = pd.read_csv(P4 / "bayes_vs_raw_disagreement.csv").head(15)
check("q07", "same top-15 models", len(set(q["q07"]["model"]) & set(dis["model"])), 15)
# q08: hazard shapes
wb = pd.read_csv(P4 / "weibull_by_model.csv")
check("q08", "wear-out (increasing) models", (q["q08"]["hazard_shape"] == "increasing").sum(), (wb["hazard_shape"] == "increasing").sum())
# q09 / q10: alerts from the test-period scores
sc = pd.read_parquet(ROOT / "data/results/ew_test_scores_30d.parquet")
m30 = pd.read_csv(P5 / "metrics_30d.csv")
thr = m30.loc[(m30["model"] == "lightgbm") & (m30["budget_per_1000"] == 5.0), "threshold"].iloc[0]
sc["a"] = (sc["score_lightgbm"] >= thr).astype(int)
check("q09", "LightGBM 5/1000 alert drive-days", q["q09"]["lgbm_alert_drive_days"].sum(), sc["a"].sum())
check("q09", "rule alert drive-days", q["q09"]["rule_alert_drive_days"].sum(), sc["rule_alert"].sum())
f = sc[sc["days_to_failure"].notna() & (sc["days_to_failure"] >= 0)].sort_values(["serial_number", "date"])
f["prev"] = f.groupby("serial_number")["a"].shift(1).fillna(0)
onset = f[(f["a"] == 1) & (f["prev"] == 0)].groupby("serial_number")["days_to_failure"].max()
check("q10", "failed test drives", q["q10"]["failed_drives"].sum(), f["serial_number"].nunique())
check("q10", "alerted failed drives", q["q10"]["alerted"].sum(), len(onset))
check("q10", "alerted >= 7 days ahead", q["q10"]["alerted_7d_plus"].sum(), (onset >= 7).sum())
# q11: out-of-time
oot = pd.read_csv(P4 / "out_of_time_predictions_main_overdispersed_no_age.csv")
check("q11", "actual failures (test year)", q["q11"]["actual"].sum(), oot["actual"].sum())
check("q11", "models covered", q["q11"]["covered"].astype(str).str.lower().eq("true").sum(), oot["covered"].sum())
# q12: fleet AFR by quarter
fq = mps.groupby("quarter")[["drive_days", "failures"]].sum()
fq["afr"] = (fq["failures"] / (fq["drive_days"] / 365) * 100).round(2)
mrg = q["q12"].set_index("quarter").join(fq["afr"])
check("q12", "max |fleet AFR difference| across 12 quarters", (mrg["fleet_afr_pct"] - mrg["afr"]).abs().max(), 0.0, tol=1e-9)

queries = sorted({c["query"] for c in checks})
out = {"queries_checked": queries, "n_queries": len(queries), "all_match": all(c["match"] for c in checks), "checks": checks}
(SQL / "spotcheck.json").write_text(json.dumps(out, indent=2))
for c in checks:
    print(f"[{'OK' if c['match'] else 'MISMATCH'}] {c['query']} {c['check']}: sql={c['sql']} pandas={c['pandas']}")
sys.exit(0 if out["all_match"] else 1)
