# Drive Fleet Reliability Pipeline

Which hard-drive models fail most, how risk changes as drives age, how confident we can be when data are sparse,
and how much warning SMART telemetry gives at an acceptable false-alarm cost. Built on three years of Backblaze's
public drive telemetry with Databricks (bronze → silver → gold → SQL serving), Bayesian survival methods, and an
early-warning model evaluated against a simple-rule baseline.

> **Status:** pipeline, analysis, serving layer and documentation are complete and verified. The Tableau Public
> dashboard is being built from the extracts in [`tableau/`](tableau/) ([build spec](tableau/README.md)); its link
> will be added here when published.

## 1. Problem

A fleet of the same kind of hardware fails at different rates by model and by age. A reliability team has to decide:
- which models to trust and which to replace or watch
- how many spares to budget next year
- whether telemetry alerts are worth their false-alarm cost

Two things make this hard:
- **Sparse data:** some models have a few thousand drive-days, where one failure swings the raw rate from 0% to
  over 10%.
- **Changing risk:** risk changes over a drive's life, so last year's rate can mislead.

## 2. Data

- **Source:** [Backblaze Drive Stats](https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data): daily
  SMART readings and failure flags for every drive in Backblaze's data centers. Data courtesy of Backblaze, used under
  its terms (cited; the data itself is not sold).
- **Exact scope** ([`results/scale.json`](results/scale.json)):

| | |
|---|---|
| Date range | 2023-07-01 to 2026-06-30 (12 quarters, Q3 2023 – Q2 2026) |
| Rows | 333,732,420 drive-days |
| Drives | 409,830 (97 models); analyses use data drives ≥ 4 TB: 404,782 drives, 66 models, 329,208,251 drive-days |
| Failures | 13,255 (13,076 on data drives) |

## 3. Architecture

```
Backblaze quarterly ZIPs ──(scripts/download_data.sh: download, upload unchanged, verify sizes)──┐
                                                                                                 ▼
Databricks (Free Edition, serverless) — one quarter per run, idempotent, resumable (ops.quarter_status)
  bronze     all raw columns as strings + lineage       keeps the source exactly as published, for audit
  silver     typed, deduplicated, normalized            one clean row per (date, drive); every dropped row explained
  gold       drive_lifetimes · model_period_stats ·     analysis-ready shapes: survival, failure rates, early warning
             model_age_stats · drive_day_features
  analytics  views + 12 analysis queries (SQL)          the serving layer for analysis and dashboard extracts
       │ Parquet exports                     ▲ results tables (gold.res_*)
       ▼                                     │
  Local modeling: NumPyro, LightGBM, survival code in src/reliability (unit-tested)
       │
       ▼ aggregate CSV extracts (Tableau Public cannot connect live)
  Tableau Public dashboard: fleet reliability · lifetime risk · early warning
```

One platform does both processing and serving. A separate warehouse (Snowflake) was planned and then dropped: at this
data size it added a copy of the data and a reconciliation loop without meeting any need Databricks SQL couldn't
([DECISIONS](docs/DECISIONS.md), 2026-10-14).

## 4. Approach

- **Data quality first.** Every rule (deduplication, model-name normalization, capacity fixes, failure semantics, a
  SMART power-on-hours counter that wraps at 78,188 hours on four Seagate models) is documented in
  [DECISIONS](docs/DECISIONS.md), applied in silver/gold, and checked on every quarter.
- **Survival:**
  - Drives still running or retired without failing are right-censored.
  - Drives already old when the window opens enter at their power-on age (left truncation / delayed entry).
  - Kaplan-Meier curves per model and manufacturer.
  - Weibull hazard shape per model: decreasing (early-life), constant, or increasing (wear-out).
- **Bayesian failure rates (NumPyro):**
  - Poisson failures per model × quarter.
  - Partial pooling by manufacturer, so sparse models borrow strength from similar models.
  - A quarter-drift term, because observed rates vary ~3× more than Poisson allows.
  - Checked against synthetic fleets with known rates, and with an out-of-time test: fit on two years, predict the
    third.
- **Early warning:**
  - Drives are split by serial-number hash and by time: train before 2025-07-01, test after, no drive in both.
  - Logistic regression and LightGBM on rolling SMART features, trained on down-sampled negatives and evaluated on
    the full natural test distribution (0.109% positive).
  - Baseline: "alert when any critical SMART counter (5/187/188/197/198) is nonzero".

## 5. Results

Full write-up with sources: [`docs/RESULTS.md`](docs/RESULTS.md). Dashboard: *link pending*.

- **Validation:** the pipeline reproduces Backblaze's published Q1 2026 table exactly on all 33 models (drive counts,
  drive-days, failures). Q2 2026 matches on counts and drive-days; failures differ by +18 (1.2%), traced to
  Backblaze's manual reclassification ([`afr_validation_summary.json`](results/validation/afr_validation_summary.json)).
- **Riskiest models:** Seagate ST12000NM0007 **7.15%/yr [90% CI 5.75–8.94]**, ST14000NM0138 5.97%, ST10000NM0086
  5.54%. That is about 8–13× the most reliable high-volume models (0.57–0.69%)
  ([`bayes_estimates.csv`](results/phase4/bayes_estimates.csv)).
- **Why Bayesian:** a model with 1 failure in 2,240 drive-days has a raw AFR of 16.3%; its posterior is 2.9% [0.8–10.6]
  ([`bayes_vs_raw_disagreement.csv`](results/phase4/bayes_vs_raw_disagreement.csv)).
- **Forecasting:** past rates predicted the next year's failures within 90% intervals for 79.5% of models. Misses
  track hazard shape: wear-out models fail more than their trailing rate (Spearman ρ = 0.63)
  ([`out_of_time_summary.json`](results/phase4/out_of_time_summary.json),
  [`oot_vs_hazard.json`](results/phase4/oot_vs_hazard.json)).
- **Hazard shape:** of 26 models with ≥ 30 failures, 11 show wear-out, 11 constant risk, 4 early-life failures
  ([`weibull_by_model.csv`](results/phase4/weibull_by_model.csv)).
- **Early warning:**
  - LightGBM PR-AUC **0.123** vs the simple rule's **0.0067** (30-day horizon).
  - At 5 alerts per 1,000 drive-days, it alerts **64.6%** of failing drives ≥ 7 days ahead (median 68 days) while
    flagging ~2.5% of healthy drives per year; the rule flags ~10%.
  - 181 of the 183 failures the model never alerts on showed no critical SMART signal at all
    ([`metrics_30d.csv`](results/phase5/metrics_30d.csv), [`undetected_30d.json`](results/phase5/undetected_30d.json)).

**Reliability decisions** ([RESULTS §5](docs/RESULTS.md#5-reliability-decisions)):
1. Prioritize the high-risk Seagate 10–14 TB models, and budget spares *above* trailing AFR for wear-out models.
2. Don't rank or retire models on raw AFR from small populations; use the posterior interval.
3. Run SMART alerting from a model at a chosen alert budget, not the any-nonzero rule, and rely on redundancy for the
   failures that give no telemetry warning.

## 6. Limitations

Summary (details in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)):
- One fleet in one environment: the methods transfer, the rates do not.
- Failures are operationally defined, and Backblaze's curated tables differ slightly from the daily flags.
- SMART fields vary by manufacturer (187/188 are effectively Seagate-only), and about a quarter of failing drives show
  no critical SMART signal.
- Failure rates are non-stationary, and the Bayesian model has no shared age curve, so next-year forecasts for wear-out
  models are low estimates.
- Early-warning metrics come from a single split.

## 7. How to reproduce

Prerequisites: [uv](https://docs.astral.sh/uv/), the Databricks CLI with a configured profile (`DATABRICKS_PROFILE`,
default `kianhekmatnejad`), ~20 GB local disk. No credentials are stored in this repo.

```bash
uv sync && uv run pytest                                     # Python env + unit tests (also run in CI)
bash databricks/run_notebook.sh 00_setup_catalog             # catalog, schemas, volumes, control table
bash scripts/download_data.sh                                # 12 quarterly ZIPs -> Unity Catalog volume (size-verified)
bash scripts/run_full_scope.sh                               # bronze -> silver -> gold -> features -> export (resumable)
uv run python scripts/write_scale.py                         # results/scale.json
uv run python scripts/pull_exports.py                        # gold exports, verified against the manifest
uv run python scripts/validate_vs_backblaze.py Q1_2026 Q2_2026
uv run python scripts/phase4_failure_rates.py                # survival, Weibull, Bayesian, out-of-time
uv run python scripts/phase4_oot_age_diagnostic.py && uv run python scripts/phase4_oot_vs_hazard.py
bash databricks/run_notebook.sh 41_export_features           # early-warning train / test sets
uv run python scripts/pull_exports.py ew_train ew_test
uv run python scripts/phase5_early_warning.py                # early-warning models and metrics
uv run python scripts/push_results.py && bash databricks/run_notebook.sh 50_load_results
uv run python scripts/dbsql.py -f databricks/sql/10_analytics_views.sql
uv run python scripts/validate_serving.py                    # serving-layer reconciliation
uv run python scripts/dbsql.py -f databricks/sql/30_analysis_queries.sql
uv run python scripts/spotcheck_queries.py                   # query outputs vs pandas
uv run python scripts/dbsql.py -f databricks/sql/40_tableau_extracts.sql -o tableau
```

For new quarters, the asset bundle runs the per-quarter chain: `databricks bundle deploy && databricks bundle run quarterly_pipeline`.

## Repository layout

```
databricks/        notebooks 00 setup · 10 bronze · 20 silver · 30–32 gold · 40/41 exports · 50 results load
databricks/sql/    analytics views · serving validation · 12 analysis queries · Tableau extracts
databricks.yml     asset bundle: quarterly pipeline job
src/reliability/   afr · normalize · age · features · labels · survival · bayes · early_warning (pure, tested)
scripts/           download, backfill driver, SQL runner, validation, modeling entry points
tests/             pytest unit tests
results/           every reported number's source file
tableau/           aggregate extracts + dashboard build spec
docs/              DECISIONS · DATA_DICTIONARY · RESULTS · LIMITATIONS · TALK_NOTES
```
