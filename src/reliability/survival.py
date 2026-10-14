"""Survival by drive age with right-censoring and left truncation (delayed entry).

Drives enter observation at `entry` age (power-on age when first seen in the window), and leave at `exit`
age by failing (event=1) or being censored (event=0). A drive is in the risk set at age t only if
entry < t <= exit. Ignoring entry (treating every drive as observed from age 0) biases survival upward,
because drives that failed before the window are invisible.

Kaplan-Meier is implemented here (product-limit with a minimum-risk-set start, which lifelines lacks);
the Weibull MLE is implemented here on the log scale (lifelines' fitter diverged on real fleets). Times are in years.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def km_curve(entry, exit, event, grid=None, min_at_risk: int = 1, label="km") -> pd.DataFrame:
    """Kaplan-Meier survival with delayed entry (product-limit; Greenwood variance, log-log 95% CI).

    With delayed entry, the risk set at young ages can be tiny (few drives observed new), and one early
    failure among 1-2 drives would send S(t) to ~0 for every later age. The curve therefore starts at
    `start_age`, the first event age where at least `min_at_risk` drives are at risk, and is reported as
    survival *conditional on reaching start_age*. Ages below start_age get NaN.

    Returns columns: age, survival, ci_lower, ci_upper, at_risk, start_age.
    """
    entry, exit, event = (np.asarray(x, dtype=float) for x in (entry, exit, event))
    entry_sorted, exit_sorted = np.sort(entry), np.sort(exit)

    def at_risk(t):  # drives with entry < t <= exit
        t = np.asarray(t, dtype=float)
        return np.searchsorted(entry_sorted, t, side="left") - np.searchsorted(exit_sorted, t, side="left")

    times, d = np.unique(exit[event == 1], return_counts=True)
    n = at_risk(times)
    ok = n >= min_at_risk
    start = times[ok][0] if ok.any() else np.inf
    keep = times >= start
    times, d, n = times[keep], d[keep], n[keep]
    surv = np.cumprod(1 - d / n)
    with np.errstate(divide="ignore", invalid="ignore"):
        green = np.cumsum(d / (n * (n - d)))
        # log-log CI: S^exp(+-z*se), se = sqrt(green) / |log S|
        se = np.sqrt(green) / np.abs(np.log(surv))
        lo = surv ** np.exp(1.96 * se)
        hi = surv ** np.exp(-1.96 * se)
    lo = np.where(surv >= 1, 1.0, np.where(surv <= 0, 0.0, lo))
    hi = np.where(surv >= 1, 1.0, np.where(surv <= 0, 0.0, hi))

    if grid is None:
        grid = np.linspace(0, exit.max(), 101)
    grid = np.asarray(grid, dtype=float)
    idx = np.searchsorted(times, grid, side="right") - 1      # last event time <= age
    s_g = np.where(idx >= 0, surv[np.clip(idx, 0, None)] if len(surv) else 1.0, 1.0)
    lo_g = np.where(idx >= 0, lo[np.clip(idx, 0, None)] if len(lo) else 1.0, 1.0)
    hi_g = np.where(idx >= 0, hi[np.clip(idx, 0, None)] if len(hi) else 1.0, 1.0)
    before = grid < start if np.isfinite(start) and min_at_risk > 1 else np.zeros(len(grid), bool)
    s_g, lo_g, hi_g = (np.where(before, np.nan, x) for x in (s_g, lo_g, hi_g))
    return pd.DataFrame({"age": grid, "survival": s_g, "ci_lower": lo_g, "ci_upper": hi_g,
                         "at_risk": at_risk(grid), "start_age": start if np.isfinite(start) else np.nan})


@dataclass
class WeibullFit:
    shape: float          # k: < 1 decreasing hazard (early life), ~1 constant, > 1 increasing (wear-out)
    shape_ci: tuple       # 95% CI for k
    scale: float          # lambda (years)
    n: int
    events: int
    hazard_shape: str     # "decreasing" | "constant" | "increasing" (CI-based)


def weibull_fit(entry, exit, event) -> WeibullFit:
    """Weibull MLE with right-censoring and delayed entry. Hazard h(t) = (k/lam) (t/lam)^(k-1).

    Log-likelihood: sum_i [ d_i log h(t_i) - ((t_i/lam)^k - (e_i/lam)^k) ], maximised over (log k, log lam), so both
    stay positive; 95% CI for k from the inverse Hessian on the log scale. (lifelines' fitter optimises on the natural
    scale and diverged to k ~ 0 on real fleets with many drives entering near age 0.)
    """
    e, t, d = (np.asarray(x, dtype=float) for x in (entry, exit, event))
    t = np.maximum(t, 1e-9)

    def nll(theta):
        logk, loglam = theta
        k, lam = np.exp(logk), np.exp(loglam)
        log_h = logk - loglam + (k - 1) * (np.log(t) - loglam)
        cum = (t / lam) ** k - (e / lam) ** k
        return -(np.sum(d * log_h) - np.sum(cum))

    # start at the exponential fit (k = 1, lam = exposure / events)
    lam0 = max((t - e).sum() / max(d.sum(), 1), 1e-6)
    res = minimize(nll, x0=[0.0, np.log(lam0)], method="BFGS")
    if not res.success:
        res = minimize(nll, x0=res.x, method="Nelder-Mead", options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 20000})
    logk, loglam = res.x
    H = _hessian(nll, res.x)
    se_logk = float(np.sqrt(np.linalg.inv(H)[0, 0])) if np.all(np.isfinite(H)) else float("nan")
    k = float(np.exp(logk))
    lo, hi = float(np.exp(logk - 1.96 * se_logk)), float(np.exp(logk + 1.96 * se_logk))
    shape = "increasing" if lo > 1 else "decreasing" if hi < 1 else "constant"
    return WeibullFit(k, (lo, hi), float(np.exp(loglam)), len(t), int(d.sum()), shape)


def _hessian(f, x, h=1e-4):
    x = np.asarray(x, dtype=float)
    n = len(x)
    H = np.zeros((n, n))
    for a in range(n):
        for b in range(n):
            ea, eb = np.eye(n)[a] * h, np.eye(n)[b] * h
            H[a, b] = (f(x + ea + eb) - f(x + ea - eb) - f(x - ea + eb) + f(x - ea - eb)) / (4 * h * h)
    return H


def weibull_hazard(age, shape, scale):
    """Weibull hazard rate per year at the given age(s)."""
    age = np.asarray(age, dtype=float)
    return (shape / scale) * (age / scale) ** (shape - 1)
