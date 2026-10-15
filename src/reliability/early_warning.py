"""Early-warning splits, baseline rule, and evaluation metrics.

Splits (project plan, Phase 5): each drive is assigned to train or test by a hash of its serial number, so a drive
never appears in both; in addition, training uses only dates before `cutoff`, and testing only dates on or
after it. Rows with unknown labels are dropped before either.

Metrics are computed on the natural (unsampled) test distribution:
- PR-AUC (average precision) on drive-days
- recall at an alert budget: the score threshold that fires `budget` alerts per 1,000 test drive-days
- false alarms per 1,000 drive-days at that threshold
- drive level: share of failed test drives first alerted >= N days before failure (lead time), and healthy
  test drives ever alerted, per 1,000 drives per year of observation
"""

import hashlib

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

CRITICAL_COLS = ["s5", "s187", "s188", "s197", "s198"]


def is_test_drive(serial: str, test_frac: float = 0.3, salt: str = "bb-ew-v1") -> bool:
    """Deterministic drive-level assignment (stable across runs and machines)."""
    h = int(hashlib.sha256(f"{salt}:{serial}".encode()).hexdigest()[:8], 16)
    return h / 0xFFFFFFFF < test_frac


def split(df: pd.DataFrame, cutoff, label: str, test_frac: float = 0.3):
    """Return (train, test) with no serial overlap and a temporal cutoff. Unknown-label rows removed."""
    known = df[df[f"label_{label.split('_')[1]}_known"]] if f"label_{label.split('_')[1]}_known" in df else df
    test_mask = known["serial_number"].map(lambda s: is_test_drive(s, test_frac))
    cutoff = pd.Timestamp(cutoff)
    train = known[~test_mask & (known["date"] < cutoff)]
    test = known[test_mask & (known["date"] >= cutoff)]
    return train, test


def baseline_score(df: pd.DataFrame) -> np.ndarray:
    """Simple rule: 1 if any critical SMART raw value (5, 187, 188, 197, 198) is nonzero today, else 0."""
    return (df[CRITICAL_COLS].fillna(0).to_numpy() > 0).any(axis=1).astype(float)


def threshold_for_budget(scores: np.ndarray, budget_per_1000: float) -> float:
    """Lowest threshold whose alert rate does not exceed the budget (alerts per 1,000 drive-days)."""
    s = np.sort(np.asarray(scores, dtype=float))[::-1]
    k = int(np.floor(len(s) * budget_per_1000 / 1000.0))
    if k <= 0:
        return np.inf
    thr = s[k - 1]
    # ties at the threshold could exceed the budget; move above the tie if so
    if (s >= thr).sum() > k:
        above = s[s > thr]
        thr = above.min() if len(above) else np.inf
    return float(thr)


def drive_day_metrics(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    y = np.asarray(y).astype(int)
    scores = np.asarray(scores, dtype=float)
    alert = scores >= threshold
    n = len(y)
    tp = int((alert & (y == 1)).sum())
    fp = int((alert & (y == 0)).sum())
    return {
        "drive_days": n, "positives": int(y.sum()),
        "pr_auc": float(average_precision_score(y, scores)) if y.sum() else float("nan"),
        "prevalence": float(y.mean()),
        "threshold": threshold,
        "alerts_per_1000": (tp + fp) / n * 1000,
        "recall": tp / y.sum() if y.sum() else float("nan"),
        "precision": tp / (tp + fp) if (tp + fp) else float("nan"),
        "false_alarms_per_1000": fp / n * 1000,
    }


def drive_level_metrics(test: pd.DataFrame, scores: np.ndarray, threshold: float,
                        lead_days=(1, 7, 30)) -> tuple[dict, pd.DataFrame]:
    """Per-drive alerting outcome. `test` needs serial_number, date, days_to_failure (null if no failure).

    Returns (summary, per-failed-drive table with first alert and lead time)."""
    d = test[["serial_number", "date", "days_to_failure"]].copy()
    d["alert"] = np.asarray(scores) >= threshold
    failed = d[d["days_to_failure"].notna()]
    healthy = d[d["days_to_failure"].isna()]
    first = (failed[failed["alert"]].groupby("serial_number")["days_to_failure"].max()
             .rename("lead_days"))  # largest days_to_failure among alerted days = first alert
    per = failed.groupby("serial_number").size().rename("rows").to_frame().join(first)
    n_failed = len(per)
    h_drives = healthy.groupby("serial_number").agg(any_alert=("alert", "any"), days=("date", "size"))
    healthy_years = h_drives["days"].sum() / 365.0
    out = {"failed_drives": n_failed, "healthy_drives": len(h_drives),
           "failed_drives_alerted": int(per["lead_days"].notna().sum()),
           "healthy_drives_alerted": int(h_drives["any_alert"].sum()),
           "healthy_alerted_per_1000_drive_years":
               float(h_drives["any_alert"].sum() / healthy_years * 1000) if healthy_years else float("nan"),
           "median_lead_days": float(per["lead_days"].median()) if per["lead_days"].notna().any() else float("nan")}
    for n in lead_days:
        out[f"share_failed_alerted_{n}d_ahead"] = float((per["lead_days"] >= n).sum() / n_failed) if n_failed else float("nan")
    return out, per.reset_index()
