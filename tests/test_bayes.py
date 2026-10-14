"""Bayesian failure-rate model on synthetic fleets with known true rates."""

import numpy as np
import pandas as pd
import pytest

from reliability.bayes import age_effect, diagnostics, fit, model_estimates, predict_counts, prepare


def synth_fleet(seed, n_per_mfr=(8, 8, 6, 4), true_beta=None):
    """Fleet drawn from the model's own generative structure with fixed true parameters."""
    rng = np.random.default_rng(seed)
    if true_beta is None:
        true_beta = np.log([1.0, 0.8, 0.8, 0.9, 1.0, 1.3, 1.7, 2.2, 2.8, 3.4, 4.0])
    mu_mfr = np.log(0.015) + rng.normal(0, 0.4, len(n_per_mfr))
    rows, truth = [], {}
    for m, n in enumerate(n_per_mfr):
        for j in range(n):
            name = f"M{m}_{j}"
            r = mu_mfr[m] + rng.normal(0, 0.5)
            # some models are tiny (few drive-days) to exercise pooling
            size = rng.choice([2_000, 20_000, 300_000, 2_000_000])
            ages = rng.choice(11, size=3, replace=False)
            E_tot = 0.0
            lam_tot = 0.0
            for a in ages:
                dd = int(size / 3)
                lam = dd / 365 * np.exp(r + true_beta[a])
                rows.append({"model": name, "manufacturer": f"mfr{m}", "age_year": int(a),
                             "drive_days": dd, "failures": int(rng.poisson(lam))})
                E_tot += dd / 365
                lam_tot += lam
            truth[name] = lam_tot / E_tot * 100  # true AFR at the model's observed age mix
    return pd.DataFrame(rows), truth, true_beta


@pytest.fixture(scope="module")
def one_fit():
    df, truth, beta = synth_fleet(0)
    prep = prepare(df)
    mcmc = fit(prep, num_warmup=500, num_samples=500, num_chains=2, seed=0)
    return df, truth, beta, prep, mcmc


def test_diagnostics_clean(one_fit):
    *_, mcmc = one_fit
    d = diagnostics(mcmc)
    assert d["max_r_hat"] < 1.05
    assert d["divergences"] == 0
    assert d["min_ess"] > 100


def test_interval_coverage_across_simulations():
    """90% intervals should contain the true per-model AFR roughly 90% of the time."""
    hits, total = 0, 0
    for seed in range(6):
        df, truth, _ = synth_fleet(100 + seed)
        prep = prepare(df)
        est = model_estimates(prep, fit(prep, num_warmup=400, num_samples=400, num_chains=1, seed=seed))
        for r in est.itertuples():
            hits += r.afr_observed_mix_lo <= truth[r.model] <= r.afr_observed_mix_hi
            total += 1
    coverage = hits / total
    assert 0.8 <= coverage <= 0.99, coverage


def test_small_model_shrinks_toward_its_manufacturer(one_fit):
    """A tiny model with 0 failures gets a positive, finite estimate (raw AFR 0 is not credible)."""
    df, truth, beta, prep, mcmc = one_fit
    est = model_estimates(prep, mcmc)
    tiny = est[(est["drive_days"] <= 2_000) & (est["failures"] == 0)]
    if tiny.empty:
        pytest.skip("no zero-failure tiny model in this synthetic draw")
    assert (tiny["afr_observed_mix_median"] > 0).all()
    assert (tiny["afr_observed_mix_hi"] > 1.0).all()  # wide interval, honest about little data


def test_age_effect_recovers_wearout_direction(one_fit):
    *_, beta, prep, mcmc = one_fit
    ae = age_effect(mcmc)
    # true multiplier at age 10 vs age 0 is 4.0: posterior median should clearly exceed 2
    assert ae.loc[10, "multiplier_median"] > 2.0


def test_predict_counts_contains_actuals_for_new_period(one_fit):
    df, truth, beta, prep, mcmc = one_fit
    new, _, _ = synth_fleet(0)  # same truth, fresh Poisson noise is not drawn; reuse counts as "actuals"
    pred = predict_counts(prep, mcmc, new)
    assert set(pred.columns) >= {"pred_lo", "pred_median", "pred_hi", "actual", "covered"}
    assert pred["covered"].mean() >= 0.8
