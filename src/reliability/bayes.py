"""Hierarchical Bayesian failure rates by drive model (NumPyro).

Main analysis (DECISIONS 2026-10-14, option A): no shared age effect; partial pooling by manufacturer plus model x
quarter overdispersion. The shared age curve (age_effect=True) is kept as an option: on this fleet it is confounded
with drive generation and over-predicted out of time.

Data: one row per (model, age_year) cell with exposure E = drive_days / 365 (drive-years) and failures y.

    y[i,a]      ~ Poisson(E[i,a] * exp(r[i] + beta[a]))
    r[i]        = mu_mfr[m(i)] + sigma_model * z_i            (model log-rate at age 0; partial pooling)
    mu_mfr[m]   = mu0 + tau_mfr * z_m                          (manufacturer means; ~4 groups)
    beta[0] = 0,  beta[a] = beta[a-1] + sigma_age * e_a         (random-walk age effect shared by all models)
    mu0 ~ N(log 0.015, 1)   tau_mfr ~ HalfNormal(0.5)   sigma_model ~ HalfNormal(1)   sigma_age ~ HalfNormal(0.3)

Optional overdispersion (default on): eps[i,q] ~ N(0, sigma_mq) multiplies model i's rate in quarter q, so a
model's failure rate can drift between quarters (observed quarterly counts are ~3x more variable than Poisson;
DECISIONS 2026-10-14). Reported AFRs are long-run means (x exp(sigma_mq^2 / 2)); forecasts draw fresh eps.
sigma_mq ~ HalfNormal(0.5).

Priors: mu0 centres the age-0 rate on ~1.5%/yr (Backblaze's fleet AFR is 1-2%) with a factor-of-e sd.
tau_mfr is tight-ish because only ~4 manufacturers inform it. Non-centred parameterisation throughout.

Reported per model (AFR in %/yr = rate * 100):
- `afr_observed_mix`: expected failures / exposure at the model's own age mix. Directly comparable to raw AFR,
  but shrunk toward similar models when data are thin.
- `afr_fleet_mix`: rate at the fleet-wide age mix, so models can be compared at equal age.
"""

from dataclasses import dataclass

import jax.numpy as jnp
import numpy as np
import numpyro
import numpyro.distributions as dist
import pandas as pd
from jax import random
from numpyro.diagnostics import summary as mcmc_summary
from numpyro.infer import MCMC, NUTS

MAX_AGE_YEAR = 10  # ages >= 10 years share one bucket


def hier_model(model_mfr, cell_model, cell_age, exposure, n_age, n_mfr, cell_mq=None, n_mq=0, failures=None):
    n_model = model_mfr.shape[0]
    mu0 = numpyro.sample("mu0", dist.Normal(jnp.log(0.015), 1.0))
    tau_mfr = numpyro.sample("tau_mfr", dist.HalfNormal(0.5))
    with numpyro.plate("mfr", n_mfr):
        z_m = numpyro.sample("z_mfr", dist.Normal(0, 1))
    mu_mfr = numpyro.deterministic("mu_mfr", mu0 + tau_mfr * z_m)
    sigma_model = numpyro.sample("sigma_model", dist.HalfNormal(1.0))
    with numpyro.plate("models", n_model):
        z_i = numpyro.sample("z_model", dist.Normal(0, 1))
    r = numpyro.deterministic("r", mu_mfr[model_mfr] + sigma_model * z_i)
    if n_age > 1:
        sigma_age = numpyro.sample("sigma_age", dist.HalfNormal(0.3))
        with numpyro.plate("age_steps", n_age - 1):
            e = numpyro.sample("e_age", dist.Normal(0, 1))
        beta = numpyro.deterministic("beta", jnp.concatenate([jnp.zeros(1), jnp.cumsum(sigma_age * e)]))
    else:
        beta = numpyro.deterministic("beta", jnp.zeros(1))
    log_mu = r[cell_model] + beta[cell_age] + jnp.log(exposure)
    if cell_mq is not None:
        sigma_mq = numpyro.sample("sigma_mq", dist.HalfNormal(0.5))
        with numpyro.plate("model_quarters", n_mq):
            z_mq = numpyro.sample("z_mq", dist.Normal(0, 1))
        log_mu = log_mu + sigma_mq * z_mq[cell_mq]
    with numpyro.plate("cells", exposure.shape[0]):
        numpyro.sample("y", dist.Poisson(jnp.exp(log_mu)), obs=failures)


@dataclass
class Prepared:
    cells: pd.DataFrame          # model, manufacturer, [quarter,] age_bucket, exposure, failures, model_idx, [mq_idx]
    models: pd.DataFrame         # model, manufacturer, model_idx, mfr_idx
    manufacturers: list
    n_age: int
    overdispersion: bool = False
    n_mq: int = 0


def prepare(df: pd.DataFrame, overdispersion: bool = True, age_effect: bool = False) -> Prepared:
    """df: model, manufacturer, age_year (>= 0), drive_days, failures (any granularity; summed to cells).
    With overdispersion, df also needs `quarter`, and cells are kept per quarter.
    age_effect=False (main analysis; DECISIONS 2026-10-14) uses one age bucket: no shared age curve."""
    d = df[df["age_year"] >= 0].copy()
    d["age_bucket"] = d["age_year"].clip(upper=MAX_AGE_YEAR).astype(int) if age_effect else 0
    keys = ["model", "manufacturer", "age_bucket"] + (["quarter"] if overdispersion else [])
    cells = (d.groupby(keys, as_index=False)
             .agg(drive_days=("drive_days", "sum"), failures=("failures", "sum")))
    cells = cells[cells["drive_days"] > 0]
    cells["exposure"] = cells["drive_days"] / 365.0
    mfrs = sorted(cells["manufacturer"].unique())
    models = cells[["model", "manufacturer"]].drop_duplicates().sort_values("model").reset_index(drop=True)
    models["model_idx"] = np.arange(len(models))
    models["mfr_idx"] = models["manufacturer"].map({m: i for i, m in enumerate(mfrs)})
    cells = cells.merge(models[["model", "model_idx"]], on="model")
    n_mq = 0
    if overdispersion:
        mq = cells[["model", "quarter"]].drop_duplicates().reset_index(drop=True)
        mq["mq_idx"] = np.arange(len(mq))
        cells = cells.merge(mq, on=["model", "quarter"])
        n_mq = len(mq)
    return Prepared(cells, models, mfrs, MAX_AGE_YEAR + 1 if age_effect else 1, overdispersion, n_mq)


def fit(prep: Prepared, num_warmup=1000, num_samples=1000, num_chains=4, seed=0, progress_bar=False,
        target_accept=0.95) -> MCMC:
    c = prep.cells
    mcmc = MCMC(NUTS(hier_model, target_accept_prob=target_accept), num_warmup=num_warmup, num_samples=num_samples,
                num_chains=num_chains, chain_method="sequential" if num_chains > 1 else "parallel",
                progress_bar=progress_bar)
    mcmc.run(random.PRNGKey(seed), jnp.asarray(prep.models["mfr_idx"].to_numpy()),
             jnp.asarray(c["model_idx"].to_numpy()), jnp.asarray(c["age_bucket"].to_numpy()),
             jnp.asarray(c["exposure"].to_numpy()), prep.n_age, len(prep.manufacturers),
             cell_mq=jnp.asarray(c["mq_idx"].to_numpy()) if prep.overdispersion else None, n_mq=prep.n_mq,
             failures=jnp.asarray(c["failures"].to_numpy()))
    return mcmc


def diagnostics(mcmc: MCMC) -> dict:
    samples = {k: v for k, v in mcmc.get_samples(group_by_chain=True).items() if k != "z_mq"}  # per-cell effects: thousands
    s = mcmc_summary(samples, prob=0.9)
    # constant deterministic sites (e.g. beta = 0 without an age effect, or beta[0]) have undefined R-hat / ESS
    rhat = {k: float(np.nanmax(v["r_hat"])) for k, v in s.items() if np.isfinite(v["r_hat"]).any()}
    ess = {k: float(np.nanmin(v["n_eff"])) for k, v in s.items() if np.isfinite(v["n_eff"]).any()}
    div = int(np.asarray(mcmc.get_extra_fields()["diverging"]).sum())
    return {"max_r_hat": max(rhat.values()), "min_ess": min(ess.values()), "divergences": div,
            "r_hat_by_param": rhat, "ess_by_param": ess}


def _rates(mcmc: MCMC):
    """Model log-rates (long-run mean, including the quarter-effect variance) and age effects."""
    s = mcmc.get_samples()
    r = np.asarray(s["r"])
    if "sigma_mq" in s:
        r = r + 0.5 * np.asarray(s["sigma_mq"])[:, None] ** 2   # E[exp(eps)] for eps ~ N(0, sigma_mq)
    return r, np.asarray(s["beta"])  # (draws, models), (draws, ages)


def model_estimates(prep: Prepared, mcmc: MCMC, prob=0.9) -> pd.DataFrame:
    """Posterior AFR (%/yr) per model at its own age mix and at the fleet age mix, with raw AFR alongside."""
    r, beta = _rates(mcmc)
    c = prep.cells
    q = [(1 - prob) / 2, 0.5, 1 - (1 - prob) / 2]
    fleet_w = c.groupby("age_bucket")["exposure"].sum().reindex(range(prep.n_age), fill_value=0).to_numpy()
    fleet_w = fleet_w / fleet_w.sum()
    rows = []
    for m in prep.models.itertuples():
        mc = c[c["model_idx"] == m.model_idx]
        E = np.zeros(prep.n_age)
        np.add.at(E, mc["age_bucket"].to_numpy(), mc["exposure"].to_numpy())
        rate_by_age = np.exp(r[:, m.model_idx][:, None] + beta)            # (draws, ages)
        obs = rate_by_age @ E / E.sum() * 100
        fleet = rate_by_age @ fleet_w * 100
        lo_o, med_o, hi_o = np.quantile(obs, q)
        lo_f, med_f, hi_f = np.quantile(fleet, q)
        row = {
            "model": m.model, "manufacturer": m.manufacturer,
            "drive_days": int(mc["drive_days"].sum()), "failures": int(mc["failures"].sum()),
            "raw_afr": mc["failures"].sum() / E.sum() * 100,
            "afr_observed_mix_median": med_o, "afr_observed_mix_lo": lo_o, "afr_observed_mix_hi": hi_o,
        }
        if prep.n_age > 1:  # fleet-age-mix comparison only exists with an age effect
            row.update(afr_fleet_mix_median=med_f, afr_fleet_mix_lo=lo_f, afr_fleet_mix_hi=hi_f,
                       mean_age_bucket=float((E * np.arange(prep.n_age)).sum() / E.sum()))
        rows.append(row)
    return pd.DataFrame(rows)


def age_effect(mcmc: MCMC, prob=0.9) -> pd.DataFrame:
    """Hazard multiplier exp(beta[a]) relative to age 0, by age bucket."""
    _, beta = _rates(mcmc)
    q = [(1 - prob) / 2, 0.5, 1 - (1 - prob) / 2]
    lo, med, hi = np.quantile(np.exp(beta), q, axis=0)
    return pd.DataFrame({"age_bucket": np.arange(beta.shape[1]), "multiplier_median": med,
                         "multiplier_lo": lo, "multiplier_hi": hi})


def predict_counts(prep: Prepared, mcmc: MCMC, new: pd.DataFrame, prob=0.9, seed=1) -> pd.DataFrame:
    """Posterior predictive failure counts per model for new exposure (model, age_year, drive_days[, quarter, failures]).

    With overdispersion, each new (model, quarter) gets a fresh quarter effect drawn from N(0, sigma_mq).
    Models absent from the fit are skipped (no rate to predict from)."""
    s = mcmc.get_samples()
    r, beta = np.asarray(s["r"]), np.asarray(s["beta"])
    sig = np.asarray(s["sigma_mq"]) if "sigma_mq" in s else None
    rng = np.random.default_rng(seed)
    d = new[new["age_year"] >= 0].copy()
    d["age_bucket"] = d["age_year"].clip(upper=MAX_AGE_YEAR).astype(int) if prep.n_age > 1 else 0
    idx = dict(zip(prep.models["model"], prep.models["model_idx"]))
    q = [(1 - prob) / 2, 0.5, 1 - (1 - prob) / 2]
    rows = []
    for model, g in d.groupby("model"):
        if model not in idx:
            continue
        lam = np.zeros(r.shape[0])
        periods = g.groupby("quarter") if (sig is not None and "quarter" in g) else [(None, g)]
        for _, gq in periods:
            E = np.zeros(prep.n_age)
            np.add.at(E, gq["age_bucket"].to_numpy(), gq["drive_days"].to_numpy() / 365.0)
            eps = rng.normal(0, 1, r.shape[0]) * sig if sig is not None else 0.0
            lam += np.exp(r[:, idx[model]][:, None] + beta) @ E * np.exp(eps)
        draws = rng.poisson(lam)
        lo, med, hi = np.quantile(draws, q)
        row = {"model": model, "drive_days": int(g["drive_days"].sum()), "pred_lo": lo, "pred_median": med, "pred_hi": hi}
        if "failures" in g:
            actual = int(g["failures"].sum())
            row.update(actual=actual, covered=bool(lo <= actual <= hi))
        rows.append(row)
    return pd.DataFrame(rows)
