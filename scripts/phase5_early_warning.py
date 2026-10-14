"""Phase 5: early-warning models vs. the simple SMART rule, evaluated on the natural test distribution.

Inputs: data/exports/ew_train, ew_test (Databricks notebook 41; pulled with
`uv run python scripts/pull_exports.py ew_train ew_test` after copying ew_manifest.json).
Outputs under results/phase5/:
  split_checks.json                 serial overlap, hash re-check, date ranges, label leakage guards
  metrics_<h>.json / .csv           per model: PR-AUC, recall/false alarms at budgets, drive-level lead times
  metrics_by_manufacturer_<h>.csv
  tradeoff_<h>.csv                  alerts per 1,000 drive-days vs. recall curve (for the dashboard)
  lead_times_<h>.csv                per failed test drive: first-alert lead time per model
  undetected_<h>.json               failures never alerted, and whether any SMART signal existed
  feature_importance_<h>.csv        LightGBM gain importance
Usage: uv run python scripts/phase5_early_warning.py
"""

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reliability.early_warning import (baseline_score, drive_day_metrics, drive_level_metrics,  # noqa: E402
                                       is_test_drive, threshold_for_budget)
from reliability.features import TREND_ATTRS  # noqa: E402

OUT = ROOT / "results/phase5"
OUT.mkdir(parents=True, exist_ok=True)
EXP = ROOT / "data/exports"
manifest = json.loads((EXP / "ew_manifest.json").read_text())
MFRS = ["HGST", "Seagate", "Toshiba", "WDC"]
FEATURES = ([c for a in TREND_ATTRS for c in (f"s{a}", f"s{a}_d7", f"s{a}_d30", f"s{a}_ever")]
            + ["temp_max30", "any_crit_now", "any_crit_ever", "age_days", "capacity_tb"]
            + [f"mfr_{m}" for m in MFRS])
LABEL_DERIVED = {"fail_7d", "fail_30d", "days_to_failure", "label_7d_known", "label_30d_known", "date", "serial_number"}
assert not (set(FEATURES) & LABEL_DERIVED), "label-derived column in feature set"
BUDGETS = [1.0, 5.0, 10.0]  # alerts per 1,000 drive-days
READ_COLS = (["serial_number", "date", "manufacturer", "capacity_bytes", "age_days", "days_to_failure",
              "fail_7d", "fail_30d", "label_7d_known", "label_30d_known", "temp_max30", "any_crit_now", "any_crit_ever"]
             + [c for a in TREND_ATTRS for c in (f"s{a}", f"s{a}_d7", f"s{a}_d30", f"s{a}_ever")])


def load(name):
    df = ds.dataset(EXP / name, format="parquet").to_table(columns=READ_COLS).to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    df["capacity_tb"] = (df["capacity_bytes"] / 1e12).astype("float32")
    for m in MFRS:
        df[f"mfr_{m}"] = (df["manufacturer"] == m).astype("float32")
    num = [c for c in FEATURES if c not in df.columns or df[c].dtype != "float32"]
    df[[c for c in num if c in df.columns]] = df[[c for c in num if c in df.columns]].astype("float32")
    return df


train, test = load("ew_train"), load("ew_test")

# --- split checks (real data) ------------------------------------------------------------------------
tr_s, te_s = set(train["serial_number"]), set(test["serial_number"])
checks = {
    "train_rows": len(train), "test_rows": len(test), "train_drives": len(tr_s), "test_drives": len(te_s),
    "serial_overlap": len(tr_s & te_s),
    "train_serials_hashed_as_test": int(sum(is_test_drive(s) for s in tr_s)),
    "test_serials_hashed_as_train": int(sum(not is_test_drive(s) for s in te_s)),
    "train_date_range": [str(train["date"].min().date()), str(train["date"].max().date())],
    "test_date_range": [str(test["date"].min().date()), str(test["date"].max().date())],
    "cutoff": manifest["cutoff"], "neg_rate": manifest["neg_rate"],
    "manifest_train_rows": manifest["ew_train"]["rows"], "manifest_test_rows": manifest["ew_test"]["rows"],
    "label_only_future": bool(((test["fail_30d"] == 1) <= (test["days_to_failure"].between(0, 29))).all()),
    "no_positive_after_failure": bool((test.loc[test["days_to_failure"] < 0, "fail_30d"] == 0).all()),
}
(OUT / "split_checks.json").write_text(json.dumps(checks, indent=2))
assert checks["serial_overlap"] == 0 and checks["train_serials_hashed_as_test"] == 0 and checks["test_serials_hashed_as_train"] == 0
assert checks["train_rows"] == checks["manifest_train_rows"] and checks["test_rows"] == checks["manifest_test_rows"]
assert checks["train_date_range"][1] < manifest["cutoff"] <= checks["test_date_range"][0]
print("split checks ok:", {k: checks[k] for k in ["train_rows", "test_rows", "train_drives", "test_drives"]})


def signed_log(x):
    return np.sign(x) * np.log1p(np.abs(x))


for h in (30, 7):
    y_col, known = f"fail_{h}d", f"label_{h}d_known"
    tr = train[train[known]]
    te = test[test[known]].reset_index(drop=True)
    y_tr, y_te = tr[y_col].to_numpy(), te[y_col].to_numpy()

    # validation for early stopping: a separate hash bucket of *train* drives (never test drives)
    val_mask = tr["serial_number"].map(lambda s: is_test_drive(s, 0.2, salt="bb-ew-val")).to_numpy()
    X_tr, X_val = tr.loc[~val_mask, FEATURES], tr.loc[val_mask, FEATURES]

    gbm = lgb.LGBMClassifier(n_estimators=2000, learning_rate=0.03, num_leaves=31, min_child_samples=200,
                             subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1)
    gbm.fit(X_tr, y_tr[~val_mask], eval_set=[(X_val, y_tr[val_mask])], eval_metric="average_precision",
            callbacks=[lgb.early_stopping(100, verbose=False)])
    logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
    Xl = lambda d: signed_log(d[FEATURES].fillna(0).to_numpy(dtype="float64"))
    logit.fit(Xl(tr), y_tr)

    scores = {"simple_rule": baseline_score(te),
              "logistic": logit.predict_proba(Xl(te))[:, 1],
              "lightgbm": gbm.predict_proba(te[FEATURES])[:, 1]}
    rule_rate = scores["simple_rule"].mean() * 1000
    budgets = sorted(set(BUDGETS + [round(rule_rate, 3)]))

    rows, lead_tables = [], {}
    for name, s in scores.items():
        for b in budgets if name != "simple_rule" else [round(rule_rate, 3)]:
            thr = 0.5 if name == "simple_rule" else threshold_for_budget(s, b)
            dd = drive_day_metrics(y_te, s, thr)
            dl, per = drive_level_metrics(te, s, thr, lead_days=(1, 7, 30))
            rows.append({"model": name, "budget_per_1000": b, "matches_rule_budget": b == round(rule_rate, 3), **dd, **dl})
            if b == round(rule_rate, 3):
                lead_tables[name] = per.set_index("serial_number")["lead_days"]
    met = pd.DataFrame(rows)
    met.to_csv(OUT / f"metrics_{h}d.csv", index=False)
    (OUT / f"metrics_{h}d.json").write_text(json.dumps({
        "horizon_days": h, "test_rows_known_labels": len(te), "test_positive_rows": int(y_te.sum()),
        "simple_rule_alerts_per_1000": rule_rate, "lightgbm_best_iteration": int(gbm.best_iteration_ or 0),
        "pr_auc": {n: float(met.loc[met["model"] == n, "pr_auc"].iloc[0]) for n in scores},
        "at_rule_budget": met[met["matches_rule_budget"]].to_dict("records")}, indent=2, default=float))

    # per manufacturer, at the rule's budget
    pm = []
    for name, s in scores.items():
        thr = 0.5 if name == "simple_rule" else threshold_for_budget(s, rule_rate)
        for m in MFRS:
            idx = (te["manufacturer"] == m).to_numpy()
            if idx.sum() and y_te[idx].sum():
                d = drive_day_metrics(y_te[idx], s[idx], thr)
                dl, _ = drive_level_metrics(te[idx], s[idx], thr)
                pm.append({"model": name, "manufacturer": m, **d, **dl})
    pd.DataFrame(pm).to_csv(OUT / f"metrics_by_manufacturer_{h}d.csv", index=False)

    # trade-off curve for the dashboard
    curve = []
    for name in ("logistic", "lightgbm"):
        for b in [0.25, 0.5, 1, 2, 3, 5, 7.5, 10, 15, 20, 30, 50]:
            thr = threshold_for_budget(scores[name], b)
            d = drive_day_metrics(y_te, scores[name], thr)
            curve.append({"model": name, "budget_per_1000": b, "recall": d["recall"],
                          "false_alarms_per_1000": d["false_alarms_per_1000"], "precision": d["precision"]})
    curve.append({"model": "simple_rule", "budget_per_1000": rule_rate,
                  **{k: drive_day_metrics(y_te, scores["simple_rule"], 0.5)[k] for k in ["recall", "false_alarms_per_1000", "precision"]}})
    pd.DataFrame(curve).to_csv(OUT / f"tradeoff_{h}d.csv", index=False)

    # lead times per failed drive, and undetected failures
    lt = pd.DataFrame(lead_tables)
    lt.index.name = "serial_number"
    failed = te[te["days_to_failure"].notna()].groupby("serial_number").agg(
        manufacturer=("manufacturer", "first"), any_signal=("any_crit_ever", "max"))
    lt = lt.join(failed)
    lt.to_csv(OUT / f"lead_times_{h}d.csv")
    und = lt[lt["lightgbm"].isna()]
    (OUT / f"undetected_{h}d.json").write_text(json.dumps({
        "failed_test_drives": len(lt), "undetected_by_lightgbm": len(und),
        "undetected_by_rule": int(lt["simple_rule"].isna().sum()),
        "undetected_by_both": int((lt["lightgbm"].isna() & lt["simple_rule"].isna()).sum()),
        "undetected_lightgbm_with_no_critical_smart_ever": int((und["any_signal"] == 0).sum()),
        "undetected_by_manufacturer": und["manufacturer"].value_counts().to_dict()}, indent=2))

    imp = pd.DataFrame({"feature": FEATURES, "gain": gbm.booster_.feature_importance("gain")})
    imp["gain_share"] = imp["gain"] / imp["gain"].sum()
    imp.sort_values("gain", ascending=False).to_csv(OUT / f"feature_importance_{h}d.csv", index=False)
    print(f"[{h}d] PR-AUC:", {n: round(float(met.loc[met['model'] == n, 'pr_auc'].iloc[0]), 4) for n in scores},
          "rule alerts/1000:", round(rule_rate, 2))
