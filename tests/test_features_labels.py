import numpy as np
import pandas as pd
import pytest

from reliability.features import TREND_ATTRS, compute_features
from reliability.labels import compute_labels


def _drive(serial, dates, **attrs):
    df = pd.DataFrame({"serial_number": serial, "date": pd.to_datetime(dates)})
    for a in TREND_ATTRS + [194]:
        df[f"smart_{a}_raw"] = np.nan
    for k, v in attrs.items():
        df[k] = v
    return df


def test_delta_uses_calendar_window_not_rows():
    # day 1: 0, day 5: 2, day 12: 10. On day 12 the 7-day window [5, 12] starts at day 5's value.
    d = _drive("a", ["2024-01-01", "2024-01-05", "2024-01-12"], smart_5_raw=[0, 2, 10])
    f = compute_features(d)
    assert f["s5_d7"].tolist() == [0, 2, 8]
    assert f["s5_d30"].tolist() == [0, 2, 10]


def test_ever_is_cumulative_and_ignores_nulls():
    d = _drive("a", pd.date_range("2024-01-01", periods=5), smart_197_raw=[0, np.nan, 3, 0, np.nan])
    f = compute_features(d)
    assert f["s197_ever"].tolist() == [0, 0, 1, 1, 1]
    assert f["any_crit_ever"].tolist() == [0, 0, 1, 1, 1]
    assert f["any_crit_now"].tolist() == [0, 0, 1, 0, 0]


def test_null_current_value_gives_null_delta():
    d = _drive("a", pd.date_range("2024-01-01", periods=3), smart_5_raw=[1, np.nan, 4])
    f = compute_features(d)
    assert np.isnan(f["s5_d7"].iloc[1])
    assert f["s5_d7"].iloc[2] == 3


def test_temp_max30():
    d = _drive("a", ["2024-01-01", "2024-01-20", "2024-02-15"], smart_194_raw=[40, 35, 30])
    assert compute_features(d)["temp_max30"].tolist() == [40, 40, 35]


def test_drives_do_not_mix():
    d = pd.concat([_drive("a", ["2024-01-01", "2024-01-02"], smart_5_raw=[5, 5]),
                   _drive("b", ["2024-01-01", "2024-01-02"], smart_5_raw=[0, 1])])
    f = compute_features(d).set_index("serial_number")
    assert f.loc["b", "s5_ever"].tolist() == [0, 1]
    assert f.loc["b", "s5_d7"].tolist() == [0, 1]


def test_no_future_data_prefix_invariance():
    """Features for rows on or before a cutoff must not change when later rows are removed."""
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", periods=120)
    dates = dates[rng.random(120) > 0.15]  # random missing days
    attrs = {f"smart_{a}_raw": np.where(rng.random(len(dates)) > 0.1,
                                        np.cumsum(rng.poisson(0.2, len(dates))), np.nan)
             for a in TREND_ATTRS + [194]}
    d = _drive("a", dates, **attrs)
    full = compute_features(d)
    for cut in [10, 45, 80]:
        part = compute_features(d.iloc[:cut])
        pd.testing.assert_frame_equal(full.iloc[:cut].reset_index(drop=True), part.reset_index(drop=True))


# --- labels -------------------------------------------------------------------

def test_labels_horizons_and_known_flags():
    daily = pd.DataFrame({"serial_number": ["f"] * 3 + ["c"] * 2,
                          "date": pd.to_datetime(["2024-01-01", "2024-01-24", "2024-01-30",
                                                  "2024-01-20", "2024-01-29"])})
    fd = pd.Series(pd.to_datetime(["2024-01-30"]), index=["f"])
    lab = compute_labels(daily, fd, window_end="2024-01-31")
    # failed drive f: fails on 2024-01-30
    assert lab["days_to_failure"].tolist()[:3] == [29, 6, 0]
    assert lab["fail_30d"].tolist()[:3] == [1, 1, 1]  # 29 days ahead is within [0, 29]
    assert lab["fail_7d"].tolist()[:3] == [0, 1, 1]
    assert lab["label_7d_known"].tolist()[:3] == [True, True, True]
    # censored drive c near window end: 7-day horizon from 01-29 ends 02-04 > window end -> unknown
    assert lab["fail_7d"].tolist()[3:] == [0, 0]
    assert lab["label_7d_known"].tolist()[3:] == [True, False]
    assert lab["label_30d_known"].tolist()[3:] == [False, False]


def test_labels_never_positive_after_failure_date():
    daily = pd.DataFrame({"serial_number": ["f"], "date": pd.to_datetime(["2024-02-01"])})
    fd = pd.Series(pd.to_datetime(["2024-01-30"]), index=["f"])
    assert compute_labels(daily, fd, "2024-03-01")["fail_30d"].item() == 0
