"""Early-warning features per drive-day, using only data on or before each row's date.

This is the reference implementation. `databricks/32_gold_features.py` computes the same features
in Spark and checks its output against this function on a sample of real drives.

Definitions (calendar-day windows, not row counts, because drives have missing days):
- ``{a}``          current raw value of SMART attribute a (null if not reported that day)
- ``{a}_d7``       current value minus the earliest non-null value within [date-7, date]
- ``{a}_d30``      same over [date-30, date]
- ``{a}_ever``     1 if the attribute was ever > 0 on or before date (since the window start), else 0
- ``temp_max30``   max SMART 194 raw over [date-30, date]
- ``any_crit_now`` 1 if any critical attribute (5, 187, 188, 197, 198) is > 0 today
- ``any_crit_ever`` 1 if any critical attribute was ever > 0 on or before date
"""

import numpy as np
import pandas as pd

CRITICAL = [5, 187, 188, 197, 198]
TREND_ATTRS = [5, 187, 188, 197, 198, 199, 10, 192, 193, 12]


def _col(a: int) -> str:
    return f"smart_{a}_raw"


def compute_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Compute features for one or more drives.

    `daily` columns: serial_number, date (datetime64), and smart_{a}_raw for a in TREND_ATTRS + [194].
    Returns one row per input row with serial_number, date and the feature columns.
    """
    df = daily.sort_values(["serial_number", "date"]).reset_index(drop=True)
    out = df[["serial_number", "date"]].copy()
    for a in TREND_ATTRS:
        out[f"s{a}"] = df[_col(a)]
        out[f"s{a}_d7"] = np.nan
        out[f"s{a}_d30"] = np.nan
        out[f"s{a}_ever"] = 0
    out["temp_max30"] = np.nan

    for _, idx in df.groupby("serial_number", sort=False).indices.items():
        g = df.iloc[idx]
        t = g["date"].to_numpy("datetime64[D]").astype(np.int64)
        for a in TREND_ATTRS:
            v = g[_col(a)].to_numpy(dtype=float)
            for w in (7, 30):
                res = np.full(len(v), np.nan)
                for i in range(len(v)):
                    if np.isnan(v[i]):
                        continue
                    lo = np.searchsorted(t, t[i] - w, side="left")
                    win = v[lo:i + 1]
                    first = win[~np.isnan(win)][0]
                    res[i] = v[i] - first
                out.loc[idx, f"s{a}_d{w}"] = res
            pos = np.where(np.isnan(v), 0.0, (v > 0).astype(float))
            out.loc[idx, f"s{a}_ever"] = np.maximum.accumulate(pos).astype(int)
        temp = g[_col(194)].to_numpy(dtype=float)
        tm = np.full(len(temp), np.nan)
        for i in range(len(temp)):
            lo = np.searchsorted(t, t[i] - 30, side="left")
            win = temp[lo:i + 1]
            if (~np.isnan(win)).any():
                tm[i] = np.nanmax(win)
        out.loc[idx, "temp_max30"] = tm

    crit_now = np.column_stack([out[f"s{a}"].fillna(0).to_numpy() > 0 for a in CRITICAL])
    out["any_crit_now"] = crit_now.any(axis=1).astype(int)
    out["any_crit_ever"] = out[[f"s{a}_ever" for a in CRITICAL]].max(axis=1).astype(int)
    return out
