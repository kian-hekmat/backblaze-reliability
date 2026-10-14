# Drive Fleet Reliability Pipeline

Reliability analytics on Backblaze's public hard-drive telemetry: daily SMART health readings and
failure flags for every drive in Backblaze's data centers.

> **Status: in progress.** This README is updated as work completes. Anything not marked done in
> [Progress](#progress) has not been built or verified yet, and no results are reported until they are
> produced by code in this repo and saved under `results/`.

## Questions

1. **Failure rates and survival (core):** How does failure risk differ across drive models and over a
   drive's lifetime, and how confident can we be, especially for models with few drives or few failures?
2. **Early warning (second):** Can SMART telemetry flag a drive before it fails? How many days of warning
   does it give, and at what false-alarm cost?

Each result is framed as a reliability decision: which drive models to trust, when to replace drives,
and how much warning telemetry buys at what alert load.

## Data

- **Source:** [Backblaze Hard Drive Test Data](https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data)
  (Drive Stats). Data courtesy of Backblaze; used under its terms (cite Backblaze; the data itself is not sold).
- **Scope:** 12 quarters, Q3 2023 through Q2 2026 (2023-07-01 to 2026-06-30). The exact row, drive, model
  and failure counts for the full scope will come from `results/scale.json` once the pipeline has
  processed it. They are not stated here yet.
- **Processed so far: Q2 2026 only.** 31,968,003 drive-day rows, 359,101 drives (355,142 data drives ≥ 4 TB),
  80 normalized models, 1,522 failures. Sources: [`results/profiling/Q2_2026/summary.json`](results/profiling/Q2_2026/summary.json)
  and the pipeline checks. The drive count matches the 359,101 in Backblaze's Q2 2026 report.

## Architecture

```
Backblaze quarterly ZIPs
        │  downloaded locally, uploaded unchanged to a Unity Catalog volume
        ▼
Databricks (Free Edition, serverless)                 one quarter per run, idempotent, resumable
  bronze     raw strings + lineage columns            ── keeps the source exactly as published
  silver     typed, deduplicated, normalized          ── one clean row per (date, drive)
  gold       drive_lifetimes, model_period_stats,     ── analysis-ready shapes for survival,
             model_age_stats, drive_day_features         failure rates and early warning
  analytics  views + SQL on the SQL warehouse         ── serving layer for analysis and Tableau extracts
        │                          ▲
        │ Parquet exports          │ results tables (Bayesian rates, survival curves, alert scores)
        ▼                          │
Local modeling (NumPyro, lifelines, LightGBM) ── src/reliability, unit-tested
        │
        ▼  aggregate CSV extracts (Tableau Public cannot connect live)
Tableau Public dashboard                              ── fleet reliability, lifetime risk, early warning
```

One platform serves the data. A separate warehouse (Snowflake) was planned, then dropped: at this size
it added a copy of the data and a reconciliation step without meeting any need Databricks SQL couldn't
(see [`docs/DECISIONS.md`](docs/DECISIONS.md), 2026-10-14).

## Progress

| Phase | Status | Evidence |
|---|---|---|
| 0. Setup: repo, Python env, CI, Databricks catalog/schemas/volumes | **Done** | `databricks/00_setup_catalog.py`; pytest CI |
| 1. Data profiling (Q2 2026) and data-quality rules | **Done** | [`results/profiling/Q2_2026/`](results/profiling/Q2_2026/), [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md), [`docs/DECISIONS.md`](docs/DECISIONS.md) |
| 2. Vertical slice: Q2 2026 through bronze, silver, gold, analytics views, Tableau extract | **Pipeline verified**; rough Tableau view pending (Kian) | Reconciliation below; [`results/phase2_afr_reconciliation.json`](results/phase2_afr_reconciliation.json), [`results/serving_validation.json`](results/serving_validation.json), [`tableau/extract_model_quarter_afr.csv`](tableau/extract_model_quarter_afr.csv) |
| 3. Full-scope pipeline (12 quarters) | **Running** | `scripts/run_full_scope.sh` (resumable backfill). Q3 2023 surfaced two new data-quality issues, both handled (DECISIONS 2026-10-14) |
| 4. Survival and Bayesian failure rates | Code + tests done; awaiting full data | KM/Weibull with delayed entry, hierarchical Bayes with age effect. Synthetic 90%-interval coverage 88.6% over 40 fleets ([`results/phase4/bayes_synthetic_coverage.json`](results/phase4/bayes_synthetic_coverage.json)). External validation on Q2 2026: drive counts and drive-days exact for 31/31 published models; failures exact for 21/31 ([`results/validation/afr_validation_summary.json`](results/validation/afr_validation_summary.json)) |
| 5. Early-warning prediction | Code + tests done; awaiting full data | Drive + time split, simple-rule baseline, logistic / LightGBM, drive-day and drive-level metrics |
| 6. Serving layer (Databricks SQL) and analysis queries | Not started | |
| 7. Tableau Public dashboard | Not started | |

**Q2 2026 slice: reconciliation so far** (from the pipeline's checks in `backblaze.ops.quarter_status`):
- Raw CSV data lines = bronze = silver = 31,968,003 rows (0 duplicate (date, serial) rows; silver key unique).
- `drive_lifetimes`: 359,101 drives, one row each, drive-days summing to 31,968,003; all 1,522 failed drives
  have `failed = 1`.
- `model_period_stats` / `model_age_stats` totals equal silver (31,968,003 drive-days, 1,522 failures).
- `drive_day_features`: 31,613,498 rows (exactly the data-drive rows). Spark features match the reference
  implementation on 200 sampled drives with 0 mismatches (the no-future-data check).
- Serving views in `backblaze.analytics` reconcile with gold (8 checks, all diffs 0).
- Independent pandas AFR on the raw quarter matches the serving view for all 80 models: drive counts,
  drive-days and failures exactly, AFR to 1e-9.
- Drive ages from SMART 9, after correcting a counter wraparound on two Seagate 8 TB models, are within
  1.5 months of Backblaze's published average age for 30 of 31 models
  ([`results/validation/age_check_Q2_2026.csv`](results/validation/age_check_Q2_2026.csv)).

## Repository layout

```
databricks/        notebooks: 00 setup, 10 bronze, 20 silver, 30–32 gold, 40 export, 50 results load; run_notebook.sh
databricks/sql/    analytics views, validation, analysis queries, Tableau extracts
databricks.yml     asset bundle: the quarterly pipeline job
src/reliability/   pure Python: afr, normalize, age, features, labels, survival, bayes, early_warning
scripts/           local helpers: profiling, Databricks SQL runner, validation checks
tests/             pytest unit tests (run in CI on every push)
results/           saved outputs backing every reported number
docs/              DECISIONS, DATA_DICTIONARY, LIMITATIONS (RESULTS, TALK_NOTES to come)
```

## Reproducing what exists so far

Prerequisites: [uv](https://docs.astral.sh/uv/) and the Databricks CLI with a configured profile
(`DATABRICKS_PROFILE`, default `kianhekmatnejad`). No credentials are stored in this repo.

```bash
uv sync && uv run pytest                                  # environment + unit tests
bash databricks/run_notebook.sh 00_setup_catalog          # catalog, schemas, volumes, control table
# upload data_<Qn>_<YYYY>.zip files to /Volumes/backblaze/bronze/raw/zips/ (download script to come)
bash databricks/run_notebook.sh 10_ingest_bronze '{"quarter":"Q2_2026"}'
bash databricks/run_notebook.sh 20_bronze_to_silver '{"quarter":"Q2_2026"}'
bash databricks/run_notebook.sh 30_gold_drive_lifetimes
bash databricks/run_notebook.sh 31_gold_model_stats
bash databricks/run_notebook.sh 32_gold_features '{"quarter":"Q2_2026"}'
bash databricks/run_notebook.sh 40_export_gold
uv run python scripts/dbsql.py -f databricks/sql/10_analytics_views.sql          # serving views
uv run python scripts/validate_serving.py                                         # reconciliation
uv run python scripts/dbsql.py -f databricks/sql/30_analysis_queries.sql         # -> results/sql/
uv run python scripts/dbsql.py -f databricks/sql/40_tableau_extracts.sql -o tableau
# or the whole chain for the next unprocessed quarter:
databricks bundle deploy && databricks bundle run quarterly_pipeline
```

## Key decisions

See [`docs/DECISIONS.md`](docs/DECISIONS.md). Highlights so far:
- Failures follow Backblaze's semantics: `failure=1` on a drive's last day. Drives that leave without a
  failure row, or survive the window, are right-censored, not counted as non-failures.
- Drive age comes from SMART 9 (power-on hours), with a counter wraparound on ST8000NM0055/ST8000DM002 corrected.
  Survival by age uses delayed entry, because most drives are already old when the window opens.
- Analyses use data drives only (≥ 4 TB). Boot drives and SSDs are excluded, as in Backblaze's reports.
- Databricks-only: Snowflake was dropped as a serving layer (2026-10-14).
