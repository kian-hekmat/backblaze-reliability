# Drive Fleet Reliability Pipeline — Project Instructions

## 1. Project Overview

An end-to-end reliability analytics project on Backblaze's public hard-drive telemetry: daily SMART health readings and failure flags for every drive in Backblaze's data centers. The pipeline ingests roughly three years of daily data (hundreds of millions of drive-day rows) through Databricks (bronze/silver/gold Delta tables), serves analysis-ready tables and views from Databricks SQL, and publishes a Tableau Public dashboard.

**The project answers two questions, in priority order:**

1. **Survival / failure rates (core result):** How does failure risk differ across drive models and over a drive's lifetime, and how confident can we be in those estimates, especially for drive models with few units or few failures?
2. **Early warning (second result):** Can SMART telemetry flag a drive before it fails, how many days of warning does it give, and at what false-alarm cost?

**Why this project exists:** it is a portfolio piece for a data-team role in a reliability engineering organization (Intuitive Surgical). That team's work is data engineering (tables, queries, subsets) feeding Tableau, and its director emphasizes reliability as a data discipline: data acquisition, automated pipelines, machine learning, Bayesian frameworks, and physics-informed modeling to make earlier, more confident decisions. This project applies those same methods to a public hardware fleet. It must never claim medical-device or surgical-robotics experience.

**The project must be functional, not demonstrative.** Every component exists because the work needs it. Do not add tools, layers, or copies of data only to show familiarity with a technology.

**The audience for the results** is a reliability engineering team. Every result must be framed as a reliability decision someone could act on (which drive models to trust, when to replace drives, how much warning telemetry gives), not as a modeling exercise.

---

## 2. Non-Negotiable Rules

These override anything else in this file.

1. **No unverified claims.** Never report a metric, row count, scale figure, or "done" status that was not produced by code that actually ran, with its output saved under `results/` or shown in a test. If a number exists only in a message, it does not exist.
2. **Report scale exactly.** State the precise date range, number of rows, number of drives, and number of drive models processed. If quotas or time forced a subset, name the subset. Never round up or imply full history.
3. **Report failures and limitations plainly.** If a model fails to beat its baseline, say so. If a result looks too good, investigate for leakage before reporting it. Every limitation goes into `docs/LIMITATIONS.md`.
4. **Never smooth over a bad result.** If something looks wrong, stop, state what looks wrong, and fix the cause. Never tune until the output "looks right" without understanding why it changed.
5. **Git authorship and cadence.** All commits are authored by Kian Hekmatnejad. Do not add a "Co-Authored-By: Claude" trailer or any AI attribution to commit messages. Commit messages describe the change. Commit in small logical units and push to the private GitHub repo after each verified step; if a push is blocked, tell Kian immediately.
6. **Secrets.** Never commit Databricks credentials, tokens, or connection configs. Use the local Databricks CLI profile (`DATABRICKS_PROFILE`) or environment variables, and keep any config file in `.gitignore`.
7. **Ask before irreversible or costly actions:** dropping Databricks tables or volumes that contain loaded data, deleting raw files, or anything likely to exhaust the Databricks Free Edition daily quota.

---

## 3. Fixed Design Decisions

These were decided with Kian. Do not change them without asking. History of changes: `docs/DECISIONS.md`.

| Decision | Choice |
|---|---|
| Central question | Survival/failure rates first (core), early-warning prediction second |
| Data scope | The 12 most recent complete quarters on the Backblaze data page at project start: Q3 2023 – Q2 2026 (recorded in `docs/DECISIONS.md`) |
| Platform | **Databricks only** (Free Edition). Processing: bronze/silver/gold Delta tables, incremental by quarter. Serving: Databricks SQL (`analytics` schema views, analysis queries, Tableau extracts). Snowflake was dropped on 2026-10-14 as unnecessary at this data size (see DECISIONS) |
| Build order | **Vertical slice first:** one quarter through bronze → silver → gold → analytics views → a Tableau extract, then scale to all quarters |
| Visualization | Tableau Public, built from aggregate CSV extracts exported from Databricks SQL (Tableau Public cannot connect live to Databricks) |
| Final deliverables | GitHub README + published Tableau Public dashboard, plus supporting docs (Section 10). No slide deck in this project |
| Bayesian tooling | NumPyro (JAX), run locally on gold exports |
| Early-warning tooling | scikit-learn / LightGBM on sampled training data, run locally; evaluation on the full natural distribution |
| Orchestration | Databricks Asset Bundle (`databricks.yml`) defining the quarterly job |
| CI | GitHub Actions runs pytest on every push |

### Platform constraints to design around

- **Databricks Free Edition** is serverless-only with limited compute size and usage, one 2X-Small SQL warehouse, and at most 5 concurrent job tasks. If the usage quota is exceeded, compute shuts off for the rest of the day. Design every job to process **one quarter per run**, to be **idempotent** (safe to re-run), and to **resume** from the last completed quarter (`backblaze.ops.quarter_status`). Raw quarterly ZIPs are downloaded locally and uploaded to a Unity Catalog volume.
- **Local modeling** (NumPyro, LightGBM) runs on Parquet exports of gold tables pulled from the Databricks volume. Its outputs are saved to `results/` and loaded back into Databricks as results tables so the serving layer has everything in one place.
- **Tableau Public** cannot connect live to Databricks and allows at most 15 million rows per data source. Dashboards use aggregated extracts only.

---

## 4. Repository Structure

```
backblaze-reliability/
├── CLAUDE.md
├── README.md
├── pyproject.toml / uv.lock
├── databricks.yml                   # asset bundle: quarterly pipeline job
├── .github/workflows/tests.yml      # pytest CI
├── databricks/
│   ├── 00_setup_catalog.py          # catalog, schemas (bronze/silver/gold/analytics/ops), volumes, control table
│   ├── 10_ingest_bronze.py          # one quarter -> bronze
│   ├── 20_bronze_to_silver.py       # typing, dedup, normalization
│   ├── 30_gold_drive_lifetimes.py   # one row per drive
│   ├── 31_gold_model_stats.py       # AFR inputs per model per period (+ per age year)
│   ├── 32_gold_features.py          # early-warning features and labels
│   ├── 40_export_gold.py            # Parquet exports for local modeling
│   ├── 50_load_results.py           # local modeling results -> gold results tables
│   ├── run_notebook.sh              # sync + run one notebook as a serverless job
│   └── sql/
│       ├── 10_analytics_views.sql   # views in backblaze.analytics
│       ├── 20_validate.sql          # serving-layer reconciliation checks
│       ├── 30_analysis_queries.sql  # >= 10 queries, each answering a reliability question
│       └── 40_tableau_extracts.sql  # aggregate-only extracts for Tableau
├── src/reliability/                 # pure, testable Python
│   ├── afr.py, normalize.py, age.py
│   ├── survival.py, bayes.py
│   ├── features.py, labels.py
│   └── early_warning.py
├── scripts/                         # local helpers: download, profiling, SQL runner, validation, modeling entry points
├── tests/
├── results/                         # saved outputs backing every reported number
├── tableau/                         # extract CSVs (aggregates only) + dashboard build spec
└── docs/
    ├── DECISIONS.md
    ├── DATA_DICTIONARY.md
    ├── RESULTS.md
    ├── LIMITATIONS.md
    └── TALK_NOTES.md                # interview prep; remove from history before the repo goes public
```

---

## 5. Phases

Work through phases in order. A phase is complete only when every item in its **Verification** list passes and its outputs are saved. Update `docs/DECISIONS.md` whenever a design choice is made.

### Phase 0: Setup

**Steps**
1. Create the repository, Python environment, `.gitignore`, pytest skeleton, and CI workflow.
2. In Databricks: create a catalog, schemas `bronze`, `silver`, `gold`, `analytics`, `ops`, a volume for raw files, a volume for exports, and the quarter control table.

**Verification**
- `00_setup_catalog` runs cleanly and is safe to re-run.
- `uv run pytest` passes locally and in CI.

### Phase 1: Data Profiling (before any pipeline code)

**Steps**
1. Download one recent quarter. Inspect the real file layout and column headers. Do not assume a schema from memory; Backblaze has added columns over the years.
2. Document in `docs/DATA_DICTIONARY.md`: every column, its type, null rates, and meaning. Include at least date, serial number, model, capacity, the failure flag, and the SMART normalized/raw column pairs.
3. Confirm the failure semantics from Backblaze's own documentation: when the failure flag is set, and what happens to a drive's records after failure. Also confirm how drives that leave the fleet without failing appear.
4. Profile data-quality issues: duplicate (date, serial) rows, missing days per drive, inconsistent model name formats, capacity values that change per drive, and the fraction of null SMART values per attribute.
5. Read Backblaze's published methodology for annualized failure rate (AFR) and note the exact formula and exclusions in `docs/DECISIONS.md`.

**Verification**
- Data dictionary written from observed data, with null rates computed, not estimated.
- Each data-quality issue found has a planned handling rule recorded in `docs/DECISIONS.md`.

### Phase 2: Vertical Slice (one quarter, end to end)

**Goal:** prove the full path works on one quarter before scaling.

**Steps**
1. Run bronze → silver → gold for one quarter only.
2. Create the `analytics` views and run three or four analysis queries against the slice on the SQL warehouse.
3. Export one aggregate extract and build a rough Tableau Public view from it.

**Verification**
- Row counts reconcile at every hop: raw file → bronze → silver (minus documented dedup/exclusions) → gold → analytics views.
- The slice's per-model AFR matches the same calculation done independently in pandas on the raw quarter.

### Phase 3: Databricks Pipeline at Full Scope

**Bronze** (`10_ingest_bronze.py`)
- Ingest one quarter per run into a Delta table with all columns kept as raw strings, plus `source_file`, `ingested_at`, and `quarter` columns.
- Idempotent: re-running a quarter replaces that quarter's data, never duplicates it. Track completed quarters in a control table.

**Silver** (`20_bronze_to_silver.py`)
- Cast types, parse dates, normalize model names using rules from Phase 1, and deduplicate on (date, serial_number).
- Keep only the SMART attributes chosen in `docs/DECISIONS.md` (justify the selection from Phase 1 profiling and Backblaze's own commonly used attributes).
- Partition by date. Use `MERGE` for incremental quarters.

**Gold**
- `drive_lifetimes`: one row per drive with first and last observed date, model, capacity, observed duration, `failed` flag, and censoring status. A drive that is still running at the end of the window, or that left the fleet without failing, is **right-censored**, not a non-failure. Drive **age** comes from SMART 9 (power-on hours, wraparound-corrected) so survival by age uses **delayed entry** (left truncation): most drives are already old when the window opens.
- `model_period_stats`: per model per quarter, drive count, drive-days, and failures (AFR inputs). `model_age_stats`: the same per model × quarter × age year (input to the age-aware Bayesian model).
- `drive_day_features` (data drives only): per drive per day, rolling-window SMART features (current value, change over 7/30 days, whether the attribute ever became nonzero) and labels for failure within the next 7 and 30 days. Labels whose horizon runs past the window end are flagged unknown and excluded; when a new quarter is processed, the previous quarter's last 30 days are relabeled.

**Orchestration:** the asset-bundle job runs bronze → silver → gold for the next unprocessed quarter, sequentially (within the 5-concurrent-task limit).

**Verification**
- Row-count conservation from bronze to silver is checked on every quarter, with every dropped row explained by a documented rule.
- (date, serial_number) is unique in silver (tested).
- Every failed drive in silver appears exactly once in `drive_lifetimes` with `failed = 1`.
- **No future data in features:** a unit test confirms the reference feature code is prefix-invariant, and each quarter's Spark features must equal the reference on sampled drives.
- Drive ages agree with Backblaze's published average age per model.
- Full scope recorded in `results/scale.json`: date range, quarters, total rows, distinct drives, distinct models, total failures. These are the only scale numbers allowed in the README.

### Phase 4: Survival and Bayesian Failure Rates (core result)

**Steps**
1. **Baseline AFR per drive model** using Backblaze's formula: failures ÷ (drive-days ÷ 365) × 100.
2. **External validation:** reproduce Backblaze's published quarterly tables for at least two quarters inside the data window. Pass criterion: drive counts and drive-days match exactly per model; any failure-count differences are listed and explained (Backblaze reclassifies some failures after publishing). Include a sensitivity check on the known cosmetic-failure episode (MG08ACA16TEY, Q3 2025).
3. **Kaplan-Meier survival curves** per drive model, by drive age, handling right-censoring and left truncation (delayed entry) correctly.
4. **Hierarchical Bayesian failure rates (NumPyro):**
   - Failures per model × quarter ~ Poisson(rate × drive-years), with a model × quarter random effect (overdispersion:
     observed quarterly counts vary ~3× more than Poisson).
   - Per-model rates drawn from a shared distribution by manufacturer (partial pooling), with a weakly informative prior
     at the manufacturer level (only ~4 groups), so models with few drive-days borrow strength from similar models.
   - **No shared age curve** (decided with Kian 2026-10-14, option A): a cross-model age curve is confounded with drive
     generation and over-predicted out of time. Age effects are estimated within each model (step 3 and step 5).
   - Report posterior medians and 90% credible intervals for every model next to raw AFR.
5. **Hazard shape:** fit a Weibull lifetime model with right-censoring and delayed entry for the drive models with enough failures, and report whether the hazard is decreasing (early-life failures), roughly constant, or increasing (wear-out).

**Verification**
- AFR unit tests on hand-computed small examples, including zero-failure and single-drive cases.
- Survival code tested on synthetic data with a known survival function, including censoring and delayed entry.
- Bayesian model tested on synthetic data with known true rates: posterior intervals must contain the true rates at roughly their nominal rate across repeated simulations.
- MCMC diagnostics saved (R-hat close to 1, effective sample sizes, no divergences); any problem is fixed or documented.
- **Out-of-time check:** fit on the first two years, predict failure counts per model for the final year (given its observed drive-days), and report how often the 90% intervals contain the actual counts.
- Show where Bayesian and raw AFR disagree most (models with few drive-days) and explain why. This is the main "why Bayesian" result.

### Phase 5: Early-Warning Prediction (second result)

**Steps**
1. **Splits:** split by drive (serial number), never by row, and also hold out the most recent period in time. A drive must never appear in both training and test. Rows with unknown labels are excluded.
2. **Simple baseline:** flag a drive when any of the critical SMART raw values (5, 187, 188, 197, 198) becomes nonzero. The ML model must be compared against this rule.
3. **Models:** logistic regression, then LightGBM. Train on data with non-failure rows sampled down; evaluate on the full, natural, highly imbalanced test distribution.
4. **Metrics (on the natural distribution), overall and per manufacturer** (SMART 187/188 are effectively Seagate-only):
   - Precision-recall AUC (not ROC AUC as the headline; failures are rare)
   - Recall at a fixed alert budget, e.g. alerts per 1,000 drive-days
   - Lead time: for caught failures, days between first alert and failure
   - False alarms per 1,000 drive-days
   - Drive-level: fraction of failed drives alerted at least N days ahead; healthy drives falsely alerted per 1,000 drives per year
5. Report which SMART features drive the predictions, and which failures are never caught (sudden failures with no prior signal).

**Verification**
- Tests confirm no serial number overlaps across train and test.
- Tests confirm labels use only future failure information and features use only past data.
- If the ML model does not clearly beat the simple rule, report that as the result. Do not hide it.
- If PR-AUC looks surprisingly high, run a leakage investigation before reporting.

### Phase 6: Serving Layer (Databricks SQL)

**Steps**
1. Load the results tables (Bayesian estimates, survival curves, Weibull fits, early-warning scores and summaries) into `backblaze.gold` with `50_load_results.py`. Early-warning daily scores are loaded for the test period only.
2. Create views in `backblaze.analytics` for dashboard and analysis use (`sql/10_analytics_views.sql`).
3. Write at least ten analysis queries in `sql/30_analysis_queries.sql`, each with a comment stating the reliability question it answers. Include:
   - AFR by model, manufacturer, and capacity, with Bayesian intervals
   - Failure rate by drive age bucket (early-life vs. wear-out)
   - Drive models whose raw AFR and Bayesian estimate differ most
   - Days from first SMART warning to failure, using `LAG`/window functions
   - Fleet composition over time
   - Alerts that would fire per week at a given threshold
4. Write `sql/40_tableau_extracts.sql` producing aggregate-only extracts, exported to `tableau/` as CSV.

**Verification** (`sql/20_validate.sql`, run after every results load)
- Each results table's row count equals its source file in `results/`.
- Views reconcile with gold: total drive-days and failures per model match `model_period_stats`.
- Each analysis query's output is spot-checked against the same number computed in pandas, and the comparison is saved to `results/`.

### Phase 7: Tableau Public Dashboard

Build one dashboard from the Databricks extracts, with three views:

1. **Fleet reliability:** AFR by drive model with Bayesian credible intervals, sorted, with drive-day counts visible so a viewer can see why some intervals are wide.
2. **Lifetime risk:** survival curves by drive model or manufacturer, showing early-life vs. wear-out behavior.
3. **Early warning:** the trade-off between alerts per 1,000 drive-days and failures caught, plus the lead-time distribution.

Each view gets a one-sentence caption stating the takeaway in plain language. Claude prepares the extracts and a build spec in `tableau/`; **Kian builds and publishes the dashboard** in Tableau Public and runs the viewer check.

**Verification**
- Show the dashboard to at least one person who hasn't seen the project. Without explanation, they should be able to say which drive models are riskiest and roughly how much warning telemetry gives. If they can't, revise.
- Every number shown on the dashboard traces to a saved file in `results/`.

---

## 6. Testing Standards (all phases)

- Pure logic (AFR, normalization, age, survival, labeling, feature windows, Bayesian model) lives in `src/reliability/` and is unit-tested with pytest on small hand-built or synthetic data with known answers.
- Pipeline data-quality checks (row counts, uniqueness, null rates, no future leakage) run as part of each job and fail loudly.
- Every number reported anywhere comes from a saved artifact in `results/` (JSON, CSV, or figure) produced by code in the repo.
- Tests must pass before any phase is marked complete. Never weaken or delete a test to make it pass; fix the code or document why the test was wrong.

---

## 7. Results Requirements

`docs/RESULTS.md` must contain, each with a pointer to the file that produced it:

- **Scale:** exact date range, rows, drives, models, failures (from `results/scale.json`).
- **Validation:** agreement with Backblaze's published quarterly tables (drive counts, drive-days, failures, average age).
- **Core result:** Bayesian failure-rate estimates with intervals, the models where pooling changed conclusions most, out-of-time interval coverage, and hazard-shape findings.
- **Second result:** early-warning model vs. simple-rule baseline on PR-AUC, recall at a fixed alert budget, false alarms, lead time, and which failures go undetected, overall and per manufacturer.
- **Reliability decisions:** two or three concrete, defensible statements a reliability team could act on (for example, which models warrant earlier replacement, or what alert threshold gives a useful warning window at an acceptable false-alarm rate).

---

## 8. Documentation Requirements

- **README.md** (kept current as work completes; final version must match what was actually built):
  1. Problem statement: the reliability questions and why they matter
  2. Data: source, exact scope, and attribution to Backblaze
  3. Architecture: diagram of Databricks bronze/silver/gold → Databricks SQL (analytics views) → Tableau, with one sentence on why each layer exists
  4. Approach: survival and Bayesian methods; early-warning setup and baselines
  5. Results: headline numbers with links to `docs/RESULTS.md` and the dashboard
  6. Limitations: summary linking to `docs/LIMITATIONS.md`
  7. How to reproduce: commands to rebuild everything from scratch
  - No planned or aspirational features described as done.
- **docs/DECISIONS.md:** a dated log of each design decision, the alternatives considered, and why.
- **docs/DATA_DICTIONARY.md:** every table at every layer, with columns and meaning.
- **docs/LIMITATIONS.md:** at least: the subset used and why; Backblaze's environment differs from other fleets; SMART fields vary by manufacturer; sudden failures without warning; anything platform quotas forced.
- **Attribution:** cite Backblaze as the data source and follow the usage terms on its data page.

---

## 9. Presentation Expectations

The connection at Intuitive said interviews typically include a 30–45 minute talk about yourself and your work, structured as **problem statement → approach → results** for each project. This project will be one section (about 10–15 minutes) of that talk, built later from these materials.

`docs/TALK_NOTES.md` must contain an outline in that structure:

1. **Problem:** a fleet of hardware fails at different rates; data is sparse for some models; decisions need confidence, not just averages. Early warning from telemetry is only useful if its false-alarm cost is acceptable.
2. **Approach:** why the pipeline has bronze/silver/gold layers; why Bayesian pooling for sparse models; why splits are by drive and over time; why the simple rule is the baseline.
3. **Results:** the two or three strongest findings, each with a number and its source file.
4. **What went wrong and what I learned:** at least one real problem encountered and how it was diagnosed (e.g. the SMART 9 wraparound found by checking ages against Backblaze's published averages).
5. **Connection to reliability engineering:** right-censoring and left truncation, early-life vs. wear-out, failure prediction from telemetry, and Bayesian estimation with sparse data, stated as methods transferable to a hardware reliability team, with no claims of domain experience Kian doesn't have.

Also include five likely questions with honest answers, including "Why Databricks, and why not a separate warehouse like Snowflake?" (answer: data size and incremental quarterly ingestion justify Databricks; a second serving platform was planned, then dropped because at this size it added a copy of the data and a reconciliation step without serving any need Databricks SQL couldn't) and "What would you do differently with more time or budget?"

---

## 10. Definition of Done

- [ ] Pipeline rebuilds from scratch with documented commands (data download, Databricks bundle job, SQL scripts, local modeling scripts)
- [ ] All tests pass (locally and in CI)
- [ ] Every number in README, RESULTS, TALK_NOTES, and the dashboard traces to a file in `results/`
- [ ] External validation against Backblaze's published tables recorded
- [ ] Tableau Public dashboard published (Kian) and passes the non-technical viewer check
- [ ] README, DECISIONS, DATA_DICTIONARY, RESULTS, LIMITATIONS, TALK_NOTES complete and accurate
- [ ] Exact scope stated everywhere scale is mentioned
