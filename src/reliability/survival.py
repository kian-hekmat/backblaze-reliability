"""Survival by drive age with right-censoring and left truncation (delayed entry).

Drives enter observation at `entry` age (power-on age when first seen in the window), and leave at `exit`
age by failing (event=1) or being censored (event=0). A drive is in the risk set at age t only if
entry < t <= exit. Ignoring entry (treating every drive as observed from age 0) biases survival upward,
because drives that failed before the window are invisible.

Kaplan-Meier and Weibull fits use lifelines, which supports delayed entry. Times are in years.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter, WeibullFitter


def km_curve(entry, exit, event, grid=None, label="km") -> pd.DataFrame:
    """Kaplan-Meier survival S(t) with delayed entry.

    S(t) is conditional on surviving to the smallest entry age; with drives entering near age 0 it estimates
    unconditional survival. Returns columns: age, survival, ci_lower, ci_upper, at_risk.
    """
    entry, exit, event = (np.asarray(x, dtype=float) for x in (entry, exit, event))
    kmf = KaplanMeierFitter(label=label)
    kmf.fit(exit, event_observed=event, entry=entry)
    if grid is None:
        grid = np.linspace(0, exit.max(), 101)
    sf = kmf.survival_function_at_times(grid).to_numpy()
    ci = kmf.confidence_interval_survival_function_
    lo = np.interp(grid, ci.index.to_numpy(), ci.iloc[:, 0].to_numpy())
    hi = np.interp(grid, ci.index.to_numpy(), ci.iloc[:, 1].to_numpy())
    at_risk = np.array([np.sum((entry < t) & (exit >= t)) for t in grid])
    return pd.DataFrame({"age": grid, "survival": sf, "ci_lower": lo, "ci_upper": hi, "at_risk": at_risk})


@dataclass
class WeibullFit:
    shape: float          # k: < 1 decreasing hazard (early life), ~1 constant, > 1 increasing (wear-out)
    shape_ci: tuple       # 95% CI for k
    scale: float          # lambda (years)
    n: int
    events: int
    hazard_shape: str     # "decreasing" | "constant" | "increasing" (CI-based)


def weibull_fit(entry, exit, event) -> WeibullFit:
    """Weibull MLE with right-censoring and delayed entry. Hazard h(t) = (k/lam) (t/lam)^(k-1)."""
    entry, exit, event = (np.asarray(x, dtype=float) for x in (entry, exit, event))
    wf = WeibullFitter()
    wf.fit(exit, event_observed=event, entry=entry)
    k = float(wf.rho_)
    lo = float(wf.summary.loc["rho_", "coef lower 95%"])
    hi = float(wf.summary.loc["rho_", "coef upper 95%"])
    shape = "increasing" if lo > 1 else "decreasing" if hi < 1 else "constant"
    return WeibullFit(k, (lo, hi), float(wf.lambda_), len(exit), int(event.sum()), shape)


def weibull_hazard(age, shape, scale):
    """Weibull hazard rate per year at the given age(s)."""
    age = np.asarray(age, dtype=float)
    return (shape / scale) * (age / scale) ** (shape - 1)
