# Drive Fleet Reliability

Which hard-drive models fail most, how failure risk changes as drives age, how confident we can be when a model has
little data, and how much warning SMART telemetry gives at an acceptable false-alarm cost. Built on three years of
Backblaze's public drive telemetry.

**Dashboard:** [Drive Fleet Reliability on Tableau Public](https://public.tableau.com/app/profile/kian.hekmatnejad/viz/DriveFleetReliability/Dashboard1)
· **Full results:** [docs/RESULTS.md](docs/RESULTS.md) · **Limitations:** [docs/LIMITATIONS.md](docs/LIMITATIONS.md)

## Problem

A large fleet of the same kind of hardware fails at different rates by model and by age. A reliability team has to
decide which models to trust or replace, how many spares to budget, and whether telemetry alerts are worth their
false-alarm cost. Two things make that hard:
- **Sparse data:** some models have only a few thousand drive-days, where a single failure swings the raw failure
  rate from 0% to over 10%.
- **Changing risk:** risk shifts over a drive's life, so last year's rate can mislead.

## Data

[Backblaze Drive Stats](https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data): daily SMART readings
and failure flags for every drive in Backblaze's data centers. Data courtesy of Backblaze. Exact scope
([`results/scale.json`](results/scale.json)):

| Date range | Drive-days | Drives | Models | Failures |
|---|---|---|---|---|
| 2023-07-01 to 2026-06-30 (12 quarters) | 333,732,420 | 409,830 | 97 | 13,255 |

Analyses use data drives (≥ 4 TB): 329,208,251 drive-days, 404,782 drives, 66 models, 13,076 failures.

## How it's built

```
Backblaze quarterly ZIPs
  → Databricks (one quarter per run; idempotent, resumable)
      bronze     raw files as published, for audit
      silver     typed, deduplicated, normalized; every dropped row explained by a documented rule
      gold       one row per drive (survival) · per model and quarter (failure rates) · per drive-day (early warning)
      analytics  SQL views and 12 analysis queries (serving layer)
  ⇄ local modeling (NumPyro, LightGBM; results loaded back into Databricks)
  → aggregate CSV extracts → Tableau Public dashboard
```

**Checks:**
- Every layer verifies row counts and keys, and fails loudly on a mismatch.
- The pipeline reproduces Backblaze's published Q1 2026 table **exactly**: drive counts, drive-days and failures for
  all 33 models.
- Derived drive ages match Backblaze's published averages within 1.5 months for 61 of 64 model-quarters checked.
- 73 unit tests run in CI.

## Methods

- **Survival with censoring and left truncation.** Drives still running, or retired without failing, are censored,
  not counted as survivors. Drives already old when the window opens enter at their power-on age.
- **Kaplan-Meier and Weibull hazard shape per model:** early-life failures (decreasing hazard), constant risk, or
  wear-out (increasing hazard).
- **Hierarchical Bayesian failure rates (NumPyro):**
  - Each model's rate is partially pooled with its manufacturer's, so sparse models borrow strength from similar ones.
  - A quarter-to-quarter drift term, because observed rates vary ~3× more than a fixed rate allows.
  - Tested on simulated fleets with known rates, and out of time: fit two years, predict the third.
- **Early warning:**
  - Train and test are split by drive *and* by time, so no drive appears in both.
  - Logistic regression and LightGBM on rolling SMART features, evaluated on the full natural test distribution
    (0.109% positive).
  - Baseline: "alert when any critical SMART counter is nonzero".

## Results

| Finding | Number | Source |
|---|---|---|
| Riskiest high-volume model | Seagate ST12000NM0007: **7.15%/yr** [90% CI 5.75–8.94]; most reliable high-volume models are 0.57–0.69% | [`bayes_estimates.csv`](results/phase4/bayes_estimates.csv) |
| Why Bayesian | 1 failure in 2,240 drive-days: raw AFR **16.3%**, posterior **2.9%** [0.8–10.6] | [`bayes_vs_raw_disagreement.csv`](results/phase4/bayes_vs_raw_disagreement.csv) |
| Hazard shape (26 models with ≥ 30 failures) | **11 wear-out**, 11 constant, 4 early-life | [`weibull_by_model.csv`](results/phase4/weibull_by_model.csv) |
| Predicting next year from past rates | 90% intervals covered **79.5%** of models. Misses track hazard shape: wear-out models fail more than their past rate (Spearman ρ = 0.63) | [`out_of_time_summary.json`](results/phase4/out_of_time_summary.json), [`oot_vs_hazard.json`](results/phase4/oot_vs_hazard.json) |
| Early warning, PR-AUC (30-day horizon) | LightGBM **0.123** vs simple rule **0.0067** | [`metrics_30d.json`](results/phase5/metrics_30d.json) |
| Early warning at 5 alerts / 1,000 drive-days | **64.6%** of failing drives alerted ≥ 7 days ahead (median 68 days); ~2.5% of healthy drives falsely alerted per year, vs ~10% for the rule | [`metrics_30d.csv`](results/phase5/metrics_30d.csv) |
| Failures telemetry can't predict | 181 of the 183 failures the model never alerts on showed no critical SMART signal | [`undetected_30d.json`](results/phase5/undetected_30d.json) |

**Reliability decisions:**
1. **Prioritize the high-risk Seagate 10–14 TB models**, and budget spares *above* the trailing failure rate for
   wear-out models.
2. **Don't rank or retire models on raw failure rates from small populations;** use the posterior interval.
3. **Run SMART alerting from a model at a chosen alert budget**, not the "any nonzero" rule, and rely on redundancy
   for failures that give no warning.

## Limitations

- One fleet in one environment: the methods transfer, the specific rates do not.
- Failures are operationally defined; in Q2 2026 Backblaze's curated table shows 18 fewer failures (1.2%) than its
  daily files.
- SMART fields differ by manufacturer, and about a quarter of failing drives show no critical SMART signal.
- Failure rates are non-stationary, so next-year forecasts for wear-out models are low estimates.
- Early-warning metrics come from a single train/test split.

Details: [docs/LIMITATIONS.md](docs/LIMITATIONS.md). Design decisions and data-quality rules: [docs/DECISIONS.md](docs/DECISIONS.md).

## Reproduce

Requires [uv](https://docs.astral.sh/uv/) and the Databricks CLI with a configured profile (`DATABRICKS_PROFILE`).
No credentials are stored in this repo.

```bash
uv sync && uv run pytest                                   # environment + unit tests
bash databricks/run_notebook.sh 00_setup_catalog           # catalog, schemas, volumes, control table
bash scripts/download_data.sh                              # 12 quarterly ZIPs -> Databricks volume (size-verified)
bash scripts/run_full_scope.sh                             # bronze -> silver -> gold -> features -> export (resumable)
uv run python scripts/write_scale.py                       # results/scale.json
uv run python scripts/pull_exports.py                      # gold exports, verified against the manifest
uv run python scripts/validate_vs_backblaze.py Q1_2026 Q2_2026
uv run python scripts/phase4_failure_rates.py              # survival, Weibull, Bayesian, out-of-time check
uv run python scripts/phase4_oot_age_diagnostic.py && uv run python scripts/phase4_oot_vs_hazard.py
bash databricks/run_notebook.sh 41_export_features         # early-warning train/test sets
uv run python scripts/pull_exports.py ew_train ew_test
uv run python scripts/phase5_early_warning.py              # early-warning models and metrics
uv run python scripts/push_results.py && bash databricks/run_notebook.sh 50_load_results
uv run python scripts/dbsql.py -f databricks/sql/10_analytics_views.sql
uv run python scripts/validate_serving.py                  # serving-layer reconciliation
uv run python scripts/dbsql.py -f databricks/sql/30_analysis_queries.sql
uv run python scripts/spotcheck_queries.py                 # every query checked against pandas
uv run python scripts/dbsql.py -f databricks/sql/40_tableau_extracts.sql -o tableau
```

## Repository

```
databricks/        notebooks: setup, bronze, silver, gold, exports, results load · sql/: views, checks, queries, extracts
src/reliability/   pure, unit-tested logic: AFR, normalization, drive age, features, labels, survival, Bayes, early warning
scripts/           download, backfill driver, SQL runner, validation, modeling entry points
results/           the source file for every reported number
tableau/           aggregate dashboard extracts and links
docs/              RESULTS · DECISIONS · DATA_DICTIONARY · LIMITATIONS
```
