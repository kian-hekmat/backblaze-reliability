"""Annualized failure rate, Backblaze's formula: failures / (drive_days / 365) * 100."""

import numpy as np
import pandas as pd


def afr(failures, drive_days, days_per_year: float = 365.0):
    """AFR in percent. Returns NaN where drive_days is 0 (rate undefined, not zero).

    Accepts scalars or array-likes; failures and drive_days must be non-negative.
    """
    f = np.asarray(failures, dtype=float)
    d = np.asarray(drive_days, dtype=float)
    if np.any(f < 0) or np.any(d < 0):
        raise ValueError("failures and drive_days must be non-negative")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(d > 0, f / (d / days_per_year) * 100.0, np.nan)
    return out.item() if out.ndim == 0 else out


def afr_table(daily: pd.DataFrame, group_cols, days_per_year: float = 365.0) -> pd.DataFrame:
    """Per-group drive count, drive days, failures and AFR from drive-day rows.

    `daily` needs columns: serial_number, failure (0/1), plus `group_cols`.
    One row = one drive-day, so drive_days is the row count.
    """
    g = daily.groupby(group_cols, observed=True)
    out = pd.DataFrame({
        "drive_count": g["serial_number"].nunique(),
        "drive_days": g.size(),
        "failures": g["failure"].sum(),
    }).reset_index()
    out["afr_pct"] = afr(out["failures"], out["drive_days"], days_per_year)
    return out
