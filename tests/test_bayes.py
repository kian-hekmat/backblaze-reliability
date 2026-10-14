"""Bayesian failure-rate model on synthetic fleets with known true rates."""

import numpy as np
import pandas as pd
import pytest

from reliability.bayes import age_effect, diagnostics, fit, model_estimates, predict_counts, prepare

QUARTERS = [f"Q{i}" for i in range(8)]


def synth_fleet(seed, n_per_mfr=(8, 8, 6, 4), sigma_mq=0.0, quarters=QUARTERS, true_beta=None):
    """Fleet drawn from the model's generative structure with fixed true parameters.

    sigma_mq > 0 adds true quarter-to-quarter drift of each model's rate (overdispersion).
    Returns (cells, truth AFR per model = long-run mean at its observed age mix, true_beta)."""
    rng = np.random.default_rng(seed)
    if true_beta is None:
        true_beta = np.log([1.0, 0.8, 0.8, 0.9, 1.0, 1.3, 1.7, 2.2, 2.8, 3.4, 4.0])
    mu_mfr = np.log(0.015) + rng.normal(0, 0.4, len(n_per_mfr))
    rows, truth = [], {}
    for m, n in enumerate(n_per_mfr):
        for j in range(n):
            name = f"M{m}_{j}"
            r = mu_mfr[m] + rng.normal(0, 0.5)
            size = rng.choice([2_000, 20_000, 300_000, 2_000_000])  # drive-days per quarter
            ages = rng.choice(11, size=3, replace=False)
            E_tot = lam_mean_tot = 0.0
            for q in quarters:
                eps = rng.normal(0, sigma_mq) if sigma_mq else 0.0
                for a in ages:
                    dd = int(size / 3)
                    lam = dd / 365 * np.exp(r + true_beta[a] + eps)
                    rows.append({"model": name, "manufacturer": f"mfr{m}", "quarter": q, "age_year": int(a),
                                 "drive_days": dd, "failures": int(rng.poisson(lam))})
                    E_tot += dd / 365
                    lam_mean_tot += dd / 365 * np.exp(r + true_beta[a] + sigma_mq ** 2 / 2)
            truth[name] = lam_mean_tot / E_tot * 100
    return pd.DataFrame(rows), truth, true_beta


@pytest.fixture(scope="module")
def one_fit():
    df, truth, beta = synth_fleet(0, quarters=QUARTERS[:4])
    prep = prepare(df, overdispersion=False, age_effect=True)
    mcmc = fit(prep, num_warmup=500, num_samples=500, num_chains=2, seed=0)
    return df, truth, beta, prep, mcmc


def test_diagnostics_clean(one_fit):
    *_, mcmc = one_fit
    d = diagnostics(mcmc)
    assert d["max_r_hat"] < 1.05
    assert d["divergences"] == 0
    assert d["min_ess"] > 100


@pytest.mark.parametrize("overdispersion, sigma_mq", [(False, 0.0), (True, 0.3)])
def test_interval_coverage_across_simulations(overdispersion, sigma_mq):
    """90% intervals should contain the true long-run per-model AFR roughly 90% of the time."""
    hits = total = 0
    for seed in range(5):
        df, truth, _ = synth_fleet(100 + seed, sigma_mq=sigma_mq, quarters=QUARTERS[:4])
        prep = prepare(df, overdispersion=overdispersion, age_effect=True)
        est = model_estimates(prep, fit(prep, num_warmup=400, num_samples=400, num_chains=1, seed=seed))
        for r in est.itertuples():
            hits += r.afr_observed_mix_lo <= truth[r.model] <= r.afr_observed_mix_hi
            total += 1
    assert 0.78 <= hits / total <= 0.99, hits / total


def test_overdispersed_forecasts_cover_where_poisson_does_not():
    """On data with real quarter-to-quarter drift, Poisson-only forecasts are overconfident; the overdispersed
    model's 90% predictive intervals for held-out quarters cover close to nominal."""
    cover = {False: [], True: []}
    for seed in range(3):
        df, _, _ = synth_fleet(200 + seed, sigma_mq=0.35)
        train, test = df[df["quarter"].isin(QUARTERS[:5])], df[df["quarter"].isin(QUARTERS[5:])]
        for od in (False, True):
            prep = prepare(train, overdispersion=od, age_effect=True)
            pred = predict_counts(prep, fit(prep, num_warmup=400, num_samples=400, num_chains=1, seed=seed), test)
            cover[od].extend(pred["covered"].tolist())
    assert np.mean(cover[True]) >= 0.8
    assert np.mean(cover[False]) < np.mean(cover[True]) - 0.1


def test_small_model_shrinks_toward_its_manufacturer(one_fit):
    """A tiny model with 0 failures gets a positive, finite estimate (raw AFR 0 is not credible)."""
    df, truth, beta, prep, mcmc = one_fit
    est = model_estimates(prep, mcmc)
    tiny = est[(est["drive_days"] <= 10_000) & (est["failures"] == 0)]
    if tiny.empty:
        pytest.skip("no zero-failure tiny model in this synthetic draw")
    assert (tiny["afr_observed_mix_median"] > 0).all()
    assert (tiny["afr_observed_mix_hi"] > 1.0).all()  # wide interval, honest about little data


def test_age_effect_recovers_wearout_direction(one_fit):
    *_, beta, prep, mcmc = one_fit
    ae = age_effect(mcmc)
    # true multiplier at age 10 vs age 0 is 4.0: posterior median should clearly exceed 2
    assert ae.loc[10, "multiplier_median"] > 2.0


def test_predict_counts_output_shape(one_fit):
    df, truth, beta, prep, mcmc = one_fit
    pred = predict_counts(prep, mcmc, df)
    assert set(pred.columns) >= {"pred_lo", "pred_median", "pred_hi", "actual", "covered"}
    assert len(pred) == df["model"].nunique()


def test_no_age_effect_model_covers_rates_at_observed_age_mix():
    """Main-analysis variant: no shared age curve. Its per-model rate is the long-run rate at the model's observed
    age mix, so 90% intervals should still cover that truth."""
    hits = total = 0
    for seed in range(4):
        df, truth, _ = synth_fleet(300 + seed, sigma_mq=0.3, quarters=QUARTERS[:4])
        prep = prepare(df, overdispersion=True, age_effect=False)
        assert prep.n_age == 1
        est = model_estimates(prep, fit(prep, num_warmup=400, num_samples=400, num_chains=1, seed=seed))
        for r in est.itertuples():
            hits += r.afr_observed_mix_lo <= truth[r.model] <= r.afr_observed_mix_hi
            total += 1
    assert 0.78 <= hits / total <= 0.99, hits / total


def test_diagnostics_finite_without_age_effect():
    df, _, _ = synth_fleet(5, sigma_mq=0.3, quarters=QUARTERS[:3])
    prep = prepare(df, overdispersion=True, age_effect=False)
    d = diagnostics(fit(prep, num_warmup=300, num_samples=300, num_chains=2, seed=0))
    assert np.isfinite(d["max_r_hat"]) and np.isfinite(d["min_ess"])
