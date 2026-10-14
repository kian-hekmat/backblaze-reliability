import numpy as np
import pytest

from reliability.survival import km_curve, weibull_fit, weibull_hazard


def simulate(n=20_000, k=1.8, lam=12.0, window=3.0, seed=0):
    """Fleet observed through a window: drives installed at various times, so they enter observation at
    different ages (left truncation). Drives that failed before the window are never seen. Observation ends
    at failure or window end (right censoring)."""
    rng = np.random.default_rng(seed)
    t = lam * rng.weibull(k, n)                      # true lifetimes
    entry = np.where(rng.random(n) < 0.3, 0.0, rng.uniform(0, 8, n))  # 30% enter new, rest at ages 0-8
    seen = t > entry                                 # truncation: only drives alive at entry are observed
    t, entry = t[seen], entry[seen]
    end = entry + window
    exit = np.minimum(t, end)
    event = (t <= end).astype(int)
    return entry, exit, event


def true_survival(age, k, lam):
    return np.exp(-((age / lam) ** k))


def test_km_with_delayed_entry_recovers_true_survival():
    k, lam = 1.8, 12.0
    entry, exit, event = simulate(k=k, lam=lam)
    grid = np.array([1.0, 3.0, 5.0, 8.0])
    km = km_curve(entry, exit, event, grid=grid)
    np.testing.assert_allclose(km["survival"], true_survival(grid, k, lam), atol=0.02)
    assert (km["ci_lower"] <= km["survival"]).all() and (km["survival"] <= km["ci_upper"]).all()


def test_ignoring_entry_biases_survival_upward():
    """Treating every drive as observed from age 0 overstates survival (why delayed entry matters)."""
    k, lam = 1.8, 12.0
    entry, exit, event = simulate(k=k, lam=lam)
    grid = np.array([5.0, 8.0])
    naive = km_curve(np.zeros_like(entry), exit, event, grid=grid)["survival"].to_numpy()
    assert (naive - true_survival(grid, k, lam) > 0.05).all()


def test_km_all_censored_is_flat_one():
    km = km_curve([0, 0, 1], [2, 3, 4], [0, 0, 0], grid=np.array([1.0, 2.5]))
    assert km["survival"].tolist() == [1.0, 1.0]


def test_km_hand_computed_with_entry():
    # ages: A enters 0 fails 2; B enters 1 censored 3; C enters 0 fails 4.
    # at t=2: risk set {A,B,C} -> S = 2/3.  at t=4: risk set {C} -> S = 2/3 * 0 = 0
    km = km_curve([0, 1, 0], [2, 3, 4], [1, 0, 1], grid=np.array([1.0, 2.0, 3.5, 4.0]))
    np.testing.assert_allclose(km["survival"], [1.0, 2 / 3, 2 / 3, 0.0])
    assert km["at_risk"].tolist() == [2, 3, 1, 1]


@pytest.mark.parametrize("k, expected", [(0.6, "decreasing"), (1.0, "constant"), (2.5, "increasing")])
def test_weibull_recovers_shape_with_truncation_and_censoring(k, expected):
    entry, exit, event = simulate(n=30_000, k=k, lam=10.0, seed=1)
    fit = weibull_fit(entry, exit, event)
    assert fit.shape == pytest.approx(k, rel=0.08)
    assert fit.hazard_shape == expected


def test_weibull_hazard_constant_when_shape_one():
    np.testing.assert_allclose(weibull_hazard([1, 5, 9], 1.0, 4.0), [0.25, 0.25, 0.25])
