import numpy as np
import pandas as pd
import pytest

from reliability.early_warning import (baseline_score, drive_day_metrics, drive_level_metrics, is_test_drive,
                                       split, threshold_for_budget)


def _frame(n_drives=400, days=60, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_drives):
        fail_day = rng.integers(10, days) if rng.random() < 0.1 else None
        for t in range(days):
            if fail_day is not None and t > fail_day:
                break
            dtf = None if fail_day is None else fail_day - t
            rows.append({"serial_number": f"S{i}", "date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(t)),
                         "days_to_failure": dtf, "fail_7d": int(dtf is not None and dtf <= 6),
                         "label_7d_known": True})
    return pd.DataFrame(rows)


def test_split_has_no_serial_overlap_and_respects_cutoff():
    df = _frame()
    train, test = split(df, "2025-02-01", "fail_7d")
    assert set(train["serial_number"]).isdisjoint(set(test["serial_number"]))
    assert train["date"].max() < pd.Timestamp("2025-02-01") <= test["date"].min()
    assert 0.2 < test["serial_number"].nunique() / df["serial_number"].nunique() < 0.4


def test_split_drops_unknown_labels():
    df = _frame()
    df.loc[df.index[:100], "label_7d_known"] = False
    train, test = split(df, "2025-01-15", "fail_7d")
    assert len(train) + len(test) <= (df["label_7d_known"]).sum()


def test_drive_assignment_is_deterministic():
    assert [is_test_drive(f"Z{i}") for i in range(50)] == [is_test_drive(f"Z{i}") for i in range(50)]


def test_baseline_rule():
    df = pd.DataFrame({"s5": [0, 0, 3, np.nan], "s187": [0, np.nan, 0, 0], "s188": [0, 0, 0, 0],
                       "s197": [0, 1, 0, 0], "s198": [0, 0, 0, np.nan]})
    assert baseline_score(df).tolist() == [0, 1, 1, 0]


def test_threshold_for_budget_respects_budget_with_ties():
    scores = np.array([0.9, 0.8, 0.8, 0.8, 0.1] + [0.0] * 995)  # 1000 drive-days
    thr = threshold_for_budget(scores, budget_per_1000=2)       # budget 2 alerts; 0.8 ties would give 4
    assert (scores >= thr).sum() <= 2
    assert thr == 0.9


def test_drive_day_metrics_hand_example():
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    s = np.array([0.9, 0.2, 0.8, 0.1, 0, 0, 0, 0, 0, 0])
    m = drive_day_metrics(y, s, threshold=0.5)
    assert m["recall"] == 0.5 and m["precision"] == 0.5
    assert m["alerts_per_1000"] == pytest.approx(200) and m["false_alarms_per_1000"] == pytest.approx(100)


def test_drive_level_lead_time():
    test = pd.DataFrame({
        "serial_number": ["F"] * 5 + ["H"] * 3,
        "date": pd.date_range("2025-01-01", periods=5).tolist() + pd.date_range("2025-01-01", periods=3).tolist(),
        "days_to_failure": [4, 3, 2, 1, 0, None, None, None],
    })
    scores = np.array([0, 1, 1, 0, 1, 0, 0, 1])  # failed drive first alerted 3 days ahead; healthy drive alerted once
    out, per = drive_level_metrics(test, scores, threshold=0.5)
    assert per.loc[0, "lead_days"] == 3
    assert out["share_failed_alerted_1d_ahead"] == 1.0 and out["share_failed_alerted_7d_ahead"] == 0.0
    assert out["healthy_drives_alerted"] == 1
