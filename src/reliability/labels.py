"""Failure-horizon labels per drive-day.

``fail_{h}d`` = 1 if the drive's failure date falls in [date, date + h - 1], i.e. the drive fails
within the next h days counting today. Labels use only *future* failure information by design;
features (features.py) use only the past.

``label_{h}d_known`` is False when the answer cannot be known from the data window: the drive has
not failed within the window and date + h - 1 is after the window end (DECISIONS: boundary-safe labels).
Drives that leave the fleet without failing before the window end are known non-failures.
"""

import pandas as pd

HORIZONS = (7, 30)


def compute_labels(daily: pd.DataFrame, failure_dates: pd.Series, window_end) -> pd.DataFrame:
    """daily: serial_number, date. failure_dates: Series indexed by serial_number (failed drives only)."""
    window_end = pd.Timestamp(window_end)
    out = daily[["serial_number", "date"]].copy()
    fd = out["serial_number"].map(failure_dates)
    days_to_fail = (fd - out["date"]).dt.days
    out["days_to_failure"] = days_to_fail.astype("Int64")
    for h in HORIZONS:
        out[f"fail_{h}d"] = ((days_to_fail >= 0) & (days_to_fail <= h - 1)).astype(int)
        horizon_end = out["date"] + pd.to_timedelta(h - 1, unit="D")
        out[f"label_{h}d_known"] = fd.notna() | (horizon_end <= window_end)
    return out
