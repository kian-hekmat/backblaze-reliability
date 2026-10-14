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
- **Profiled so far (Q2 2026 only)**, from [`results/profiling/Q2_2026/summary.json`](results/profiling/Q2_2026/summary.json):
  31,968,003 drive-day rows, 359,101 drives, 81 raw model strings, 1,522 failure rows. The drive count
  matches the 359,101 in Backblaze's Q2 2026 report.

## Architecture (planned; see Progress for what exists)

```
Backblaze quarterly ZIPs
        │  downloaded locally, uploaded to a Unity Catalog volume
        ▼
Databricks (Free Edition, serverless)          one quarter per run, idempotent, resumable
  bronze  raw strings + lineage columns         ── keeps the source exactly as published
  silver  typed, deduplicated, normalized       ── one clean row per (date, drive)
  gold    drive_lifetimes, model_period_stats,  ── analysis-ready shapes
          drive_day_features
        │  Parquet exports
        ▼
Snowflake (trial)  BACKBLAZE.GOLD / ANALYTICS   ── serving layer: SQL analysis + aggregate extracts
        │  CSV extracts (aggregates only)
        ▼
Tableau Public dashboard                        ── fleet reliability, lifetime risk, early warning
```

Modeling (Kaplan-Meier, Weibull, hierarchical Bayesian rates in NumPyro, LightGBM early warning) lives
in `src/reliability/` as plain, unit-tested Python.

## Progress

| Phase | Status | Evidence |
|---|---|---|
| 0. Setup: repo, Python env, Snowflake objects and roles, Databricks catalog | **Done** | [`results/phase0_role_check.txt`](results/phase0_role_check.txt): reader role can select but not create, insert or drop |
| 1. Data profiling (Q2 2026) and data-quality rules | **Done** | [`results/profiling/Q2_2026/`](results/profiling/Q2_2026/), [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md), [`docs/DECISIONS.md`](docs/DECISIONS.md) |
| 2. Vertical slice: one quarter through bronze, silver, gold, Snowflake, Tableau | In progress | AFR and model-normalization logic unit-tested; bronze/silver notebooks written |
| 3. Full-scope Databricks pipeline (12 quarters) | Not started | Raw ZIPs being uploaded to the Databricks volume |
| 4. Survival and Bayesian failure rates | Not started | |
| 5. Early-warning prediction | Not started | |
| 6. Snowflake serving layer and analysis queries | Not started | |
| 7. Tableau Public dashboard | Not started | |

## Repository layout

```
databricks/      notebooks: 00 setup, 10 bronze, 20 silver, 3x gold, 40 export; run_notebook.sh
src/reliability/ pure Python: afr, normalize (survival, bayes, features, labels, early_warning to come)
snowflake/       00_setup.sql (env), 01_verify_roles.sh, then tables / load / validate / queries / extracts
scripts/         local profiling and documentation helpers
tests/           pytest unit tests
results/         saved outputs backing every reported number
docs/            DECISIONS, DATA_DICTIONARY (RESULTS, LIMITATIONS, TALK_NOTES to come)
```

## Reproducing what exists so far

Prerequisites: [uv](https://docs.astral.sh/uv/), Snowflake CLI with a default connection, and Databricks
CLI with a configured profile (`DATABRICKS_PROFILE`, default `kianhekmatnejad`). No credentials are stored
in this repo.

```bash
uv sync                                  # Python 3.12 environment
uv run pytest                            # unit tests
snow sql -f snowflake/00_setup.sql       # Snowflake database, schemas, warehouses, roles, monitor (re-runnable)
bash snowflake/01_verify_roles.sh        # role permission checks
bash databricks/run_notebook.sh 00_setup_catalog   # Databricks catalog, schemas, volumes
uv run python scripts/profile_quarter.py data/raw/csv/Q2_2026/data_Q2_2026 Q2_2026   # profiling
```

A data download script and full pipeline commands will be added as those phases complete.

## Key decisions

See [`docs/DECISIONS.md`](docs/DECISIONS.md). Highlights so far:
- Failures follow Backblaze's semantics: `failure=1` on a drive's last day. Drives that leave without a
  failure row, or survive the window, are right-censored, not counted as non-failures.
- Drive age comes from SMART 9 (power-on hours), so survival curves account for drives that were already
  old when the window opens (left truncation).
- Analyses use data drives only (≥ 4 TB). Boot drives and SSDs are excluded, as in Backblaze's reports.
