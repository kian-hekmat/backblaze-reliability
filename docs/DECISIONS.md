# Design Decisions Log

Dated log of design decisions, alternatives considered, and reasons. Decisions fixed in
CLAUDE.md Section 3 are not repeated here unless they needed a concrete value.

---

## 2026-10-13 — Data scope: 12 quarters, Q3 2023 through Q2 2026

- **Decision:** Use the 12 most recent complete quarters on the Backblaze Hard Drive Test Data page
  at project start: Q3 2023, Q4 2023, Q1–Q4 2024, Q1–Q4 2025, Q1 2026, Q2 2026
  (2023-07-01 through 2026-06-30). Q2 2026 is the latest quarter published on the page as of 2026-10-13.
- **Alternatives:** 8 quarters (less Snowflake load), all history since 2013 (far beyond quota).
- **Why:** CLAUDE.md fixes "~3 years of complete quarters"; 12 quarters is exactly 3 years.
- **Files:** `data_<Qn>_<YYYY>.zip` from `https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/`,
  12 ZIPs totalling ~14.9 GB compressed (Q2 2026 alone is 2.09 GB).

## 2026-10-13 — Snowflake environment (SUPERSEDED 2026-10-14: Databricks-only)

- **Account:** the existing `learning` Snowflake CLI connection (account VN04570, AWS us-east-2), confirmed by Kian.
- **Trial end date: 2026-10-27** (confirmed by Kian on 2026-10-13 as "ends in 14 days").
  An earlier inference of 2026-10-22, based on first login 2026-09-22 + 30 days, was wrong.
- **Resource monitor:** `BACKBLAZE_MONITOR`, 20 credits total (approved by Kian), notify at 50/75/90%,
  suspend at 100%, suspend immediately at 110%. Attached to `LOAD_WH` and `BI_WH`.
- **Secondary roles:** this user's `DEFAULT_SECONDARY_ROLES` is `ALL`, so ACCOUNTADMIN privileges leak
  into any `USE ROLE` session. The first role test falsely showed `ANALYST_READER` could insert/drop.
  Role tests now run `USE SECONDARY ROLES NONE`. Any real read-only consumer (e.g. a Tableau user)
  must be a user whose default secondary roles are not `ALL`.

## 2026-10-13 — Ingestion path: download locally, upload ZIPs to a UC volume

- **Decision:** Download the 12 ZIPs to the local machine, upload them unchanged to
  `/Volumes/backblaze/bronze/raw/zips/`, and unzip inside Databricks per quarter.
- **Alternatives:** download from notebooks (needs verified outbound internet); upload unzipped CSVs
  (~140 GB, far slower).
- **Why:** chosen by Kian; independent of notebook internet access; ZIPs are 10x smaller than CSVs.

## 2026-10-13 — Raw schema handling

- **Observed:** two header versions in scope. Q3 2023–Q1 2024: 193 columns. Q2 2024 onward: 197 columns
  (adds `smart_211_*` and `smart_212_*`). Headers are identical across all daily files within a quarter
  (checked with md5 of every header line).
- **Decision:** Bronze reads by header name with union-by-name semantics; missing columns are null.

## 2026-10-13 — Failure semantics (from Backblaze documentation + observed data)

- Backblaze (Q3 2025 Drive Stats post): a failure occurs when a drive leaves the reporting population
  and is confirmed failed through replacement tickets; clone/temporary-replacement targets are not
  failures. Backblaze acknowledges rare "cosmetic" failures (e.g. drives pulled for firmware updates).
- Observed in Q2 2026: 1,522 rows with `failure=1`, one per drive; each is that drive's last
  observed row; no failed drive appears after its failure date.
- Drives that leave without failing (retirement, migration) simply stop appearing with `failure=0`
  throughout. 2,356 drives did so before the end of Q2 2026.
- **Decision:** a drive is `failed=1` iff its last observed row has `failure=1`. Drives that stop
  appearing without a failure row, or still run at the end of the window, are **right-censored**.
  If a serial ever reappears after a failure row, the reappearance is counted and logged per quarter.
  Following Backblaze's "failed until it shows up again" rule, only the failure on the final
  observed row counts.

## 2026-10-13 — AFR formula and exclusions (Backblaze methodology)

- **Formula:** AFR = failures / (drive_days / 365) × 100. Backblaze uses 366 in leap years; our
  baseline uses 365 per CLAUDE.md. External validation uses Q2 2026 and Q1 2026 (non-leap), so the
  two conventions coincide there.
- **Drive days:** the number of daily rows for the drive in the period (observed days, not calendar span).
- **Backblaze exclusions in quarterly tables:** boot drives removed; models included only if drive
  count > 100 and drive days > 10,000 in the quarter (Q1 2025 onward; older thresholds were 45 and
  later 60 drives). Annual: count > 250 and drive days > 50,000. Lifetime: count > 500 and
  drive days > 100,000.
- **Published Q2 2026 counts used for validation:** 359,101 drives monitored, minus 3,881 boot drives
  and 705 non-qualifying HDDs, gives 354,415 analysed; 31,553,350 drive days; 1,498 failures; AFR 1.73%.

## 2026-10-13 — Data-quality handling rules (from Q2 2026 profiling, `results/profiling/Q2_2026/`)

Every rule is applied in silver, and every quarter logs the count of rows or drives it touches.

| # | Issue | Observed (Q2 2026) | Rule |
|---|---|---|---|
| 1 | Duplicate (date, serial) rows | 0 | Keep one row per (date, serial). Prefer `failure=1`, then the row with most non-null SMART values, then the lowest source file name. Log the dropped count. |
| 2 | Missing days within a drive's span | 19,657 drives, 69,370 missing drive-days (gaps of 1–2 days most common) | Do not impute. Drive-days = observed rows (Backblaze's definition). Gaps neither censor nor end a lifetime. Rolling features use calendar-date windows, not row counts. |
| 3 | Model name formats | `WUH721816ALE6L4` (541 drives) alongside `WDC WUH721816ALE6L4` (26,286). Backblaze's published count (26,827) is their sum | Trim, collapse whitespace. A bare `WUH…` part number is prefixed with `WDC `. `manufacturer` is derived from the prefix: `ST…`/`Seagate` → Seagate, `TOSHIBA` → Toshiba, `HGST`/`Hitachi` → HGST, `WDC`/`WD ` → WDC, else Other. `model_short` (prefix removed) joins to Backblaze's published tables. |
| 4 | Capacity changing within a drive | 0 drives | Per-drive capacity = most frequent positive value. Non-positive capacity → null. Drives with more than one positive capacity are logged. |
| 5 | Model changing within a drive | 0 drives | Keep the most frequent normalized model; log drives with more than one. |
| 6 | Null SMART values | Vary by manufacturer (e.g. SMART 187/188 are Seagate-only) | Keep null in silver; never fill with 0. Features treat null as "not reported". |
| 7 | Boot drives / SSDs mixed with data drives | 3,959 drives below 4 TB, all SSDs or 2.5" boot HDDs; Backblaze reports 3,881 boot drives | `is_data_drive = capacity_bytes >= 4e12`. Analyses use data drives only. The gap of 78 drives versus Backblaze's internal boot list is documented in LIMITATIONS. Every model in Backblaze's tables is ≥ 4 TB. |
| 8 | Rows appearing after a failure | 0 | Log the count. A drive's failed status is taken from its final observed row (see failure semantics). |
| 9 | Drives present before the window starts (left truncation) | 13,363 drives entered after Q2 2026 day 1, so most drives were already running | Survival by age uses age from SMART 9 (power-on hours) at first observation as **delayed entry** (left truncation). Without it, old survivors are counted as young drives and early-life hazard is understated. |

## 2026-10-13 — SMART attributes kept in silver

- **Kept (raw and normalized), 20 attributes:** 1, 3, 4, 5, 7, 9, 10, 12, 187, 188, 192, 193, 194,
  196, 197, 198, 199, 240, 241, 242.
- **Why:**
  - Backblaze's commonly cited failure-predictive set is 5, 187, 188, 197, 198.
  - 9 (power-on hours) gives drive age.
  - The others are reported for at least 90% of rows for at least two of the four major
    manufacturers in Q2 2026 (`results/profiling/Q2_2026/smart_null_rate_by_mfr.csv`):
    error rates (1, 7), spin/start counters (3, 4, 10, 12), head/load counters (192, 193, 240),
    temperature (194), reallocation events (196), interface CRC errors (199), and workload (241, 242).
- **Caveat:** 187/188 (and 240–242 for most non-Seagate drives) are effectively Seagate-only. A
  feature on them is partly a manufacturer indicator. LIMITATIONS covers this.
- **Dropped:** SSD-specific attributes (160–183, 230–235, 244–252), helium/vendor-specific
  attributes reported by a single manufacturer, and attributes with no coverage.

## 2026-10-13 — Cross-quarter data-quality checks deferred to the pipeline

- Full profiling ran on Q2 2026 only (CLAUDE.md Phase 1: "one recent quarter"). The silver job applies
  every rule above to each quarter and logs per-quarter counts to `backblaze.ops.quarter_status`, so
  issues appearing only in older quarters surface there and get added here.

## 2026-10-13 — Repository additions not in the CLAUDE.md layout

- `scripts/`: local helper scripts (profiling, dictionary generation) that write to `results/`.
- `databricks/run_notebook.sh`: syncs notebooks to the workspace and runs one as a serverless one-time job.
- *(Removed 2026-10-14)* `snowflake/01_verify_roles.sh`.

## 2026-10-13 — Repository visibility

- The GitHub repo `kian-hekmat/backblaze-reliability` is **private** (Kian). `CLAUDE.md` and
  `docs/TALK_NOTES.md` contain interview-specific context. Before the repo is made public, remove them
  from the working tree **and from git history**; they have been committed since the first commit.

## 2026-10-13 — Plan changes approved by Kian (deviations from CLAUDE.md)

Kian approved these on 2026-10-13. They take precedence over the corresponding CLAUDE.md text.

1. **Age with left truncation.** `drive_lifetimes` adds age from SMART 9 (power-on hours) at first and
   last observation. Kaplan-Meier and Weibull fits by age use delayed entry, because most drives are
   already old when the window opens. Observed in-window duration is kept as a separate column.
2. **Age-aware Bayesian model.** Failures per model × age bucket ~ Poisson(rate × drive-years). The model
   has a shared age effect and partial pooling of model rates by manufacturer, with a weakly informative
   prior at the manufacturer level (only ~4 groups). Raw AFR and age-adjusted posterior rates are reported
   side by side.
3. **Boundary-safe labels.** When quarter q+1 is processed, the labels for the last 30 days of quarter q
   are recomputed. Rows in the final 30 days of the window (or 7 days, for the 7-day label) have unknown
   labels, are flagged, and are excluded from training and evaluation.
4. **External validation criterion.** Exact match of drive counts and drive-days per model; failure-count
   differences must be listed and explained (Backblaze reclassifies some failures after publishing). Add a
   sensitivity check on the known cosmetic-failure episode (MG08ACA16TEY, Q3 2025).
5. *(Superseded 2026-10-14: Databricks-only.)* **Snowflake timeline.** Gold tables load as soon as full scope is built; results tables load as
   produced; all Tableau extracts are exported to `tableau/` by ~2026-10-24, before the trial ends.
6. **Feature table scope.** `drive_day_features` covers data drives only. *(The Snowflake part is superseded 2026-10-14.)*
   Early-warning daily scores are loaded into Databricks results tables for the test period only.
7. **Per-manufacturer reporting** of early-warning metrics, because SMART 187/188 are effectively
   Seagate-only.
8. **Drive-level early-warning metrics** in addition to drive-day metrics: fraction of failed drives
   alerted at least N days ahead; false-alarmed healthy drives per 1,000 drives per year.
9. **Databricks Asset Bundle** (`databricks.yml`) defines the job instead of loose JSON in `databricks/jobs/`.
10. **GitHub Actions** runs pytest on every push.
11. **Human-only steps** (Kian): building and publishing the Tableau Public dashboard from the prepared
    extracts and build spec, and the viewer test.

## 2026-10-14 — SMART 9 (power-on hours) wraparound correction

- **Found:** in the first `drive_lifetimes` build, 4,543 ST8000NM0055 drives had power-on hours that
  *decreased* during Q2 2026. On ST8000NM0055 and ST8000DM002, SMART 9 drops from 78,187 to ~0: the
  counter wraps modulo 78,188 hours (~8.9 years). Most ST8000DM002 drives (6,640 of 6,903) had already
  wrapped before the quarter. Their raw readings looked young and *increasing*, so the plausibility
  check could not catch them. Raw mean age for ST8000DM002 was 12.4 months; Backblaze publishes 114.8.
- **Rule (`src/reliability/age.py`):** for those two models, readings below 30,000 h get +78,188 h.
  These models were all installed years before the window. Any other data-drive model showing the wrap
  signature (a day-over-day drop from ≥ 70,000 h to ≤ 1,000 h) fails the gold job, so new cases cannot
  slip through silently. SSDs wrap at 65,535 but are excluded from analysis.
- **Validation:** after correction, mean age per model at the end of Q2 2026 is within 1.5 months of
  Backblaze's published average age for 30 of 31 models (ST8000DM002: 115.4 vs 114.8). The outlier is
  MG08ACA16TA at +3.1 months (`results/validation/age_check_Q2_2026.csv`).
- **Alternatives:** dropping these drives' ages (loses the oldest, most wear-out-relevant models);
  using first-seen date as age (left truncation makes that wrong for every drive installed before the window).

## 2026-10-14 — Databricks-only: Snowflake dropped as the serving layer

- **Decision (Kian):** serve everything from Databricks. The serving layer is Databricks SQL on the Free Edition
  SQL warehouse:
  - views in a new `backblaze.analytics` schema
  - analysis queries and Tableau extract queries in `databricks/sql/`
  - local modeling results (Bayesian, survival, early warning) loaded back into `backblaze.gold` results
    tables by `50_load_results.py`
- **Why:**
  - Tableau Public cannot connect live to either platform, so the dashboard uses CSV extracts regardless.
  - The served gold tables are small: ~360k drives per quarter of lifetimes, hundreds of model rows.
    Separating processing from serving solves concurrency and cost-isolation problems this project doesn't have.
  - A second platform added a full data copy, an export/stage/load/reconcile loop, a credit budget, and a
    trial that expires on 2026-10-27, after which the serving layer would no longer exist.
  - Kian's direction: the project should be functional, not demonstrative.
- **Alternatives:** keep Snowflake as the serving layer (original plan); keep a Snowflake loader as an optional
  extra (only worthwhile if a target role names Snowflake).
- **What changed:**
  - Removed `snowflake/` (setup, role check, tables, load, validate scripts), `scripts/validate_snowflake.py`
    and `results/phase0_role_check.txt` (they remain in git history).
  - Phase 6 is now a Databricks SQL serving layer.
  - CLAUDE.md, README and LIMITATIONS are rewritten to match.
- **Snowflake account objects** created on 2026-10-13 (database `BACKBLAZE`, warehouses `LOAD_WH`/`BI_WH`,
  roles, resource monitor) hold no data and are left to expire with the trial unless Kian asks to drop them.
- **Parquet export (`40_export_gold.py`) is kept**, now to feed local modeling (NumPyro, LightGBM) and the
  independent pandas checks.

## 2026-10-14 — Data-quality findings from the first backfilled quarter (Q3 2023)

- **Capacity -1 on a drive's only row in the quarter:** 480 WUH722222ALE6L4 drives appear once in Q3 2023
  (their first day) with `capacity_bytes = -1`. The per-drive rule (most frequent positive value in the
  quarter) left them null, which made them non-data drives and dropped that day from features.
  **Rule 4 extended:** a drive with no positive capacity in the quarter takes its model's most frequent
  positive capacity. Every model has exactly one capacity in the quarter (`models_with_multiple_capacities = 0`,
  logged per quarter), so the fill is unambiguous. Q3 2023 after the fix: 0 null capacities;
  265,065 data drives (was 264,585).
- **Drives reappearing after a failure row:** 10 in Q3 2023 (0 in Q2 2026). Handled by the existing rule:
  only a failure on the drive's final observed row counts (Backblaze: "failed until it shows up again").
  Counted per quarter in silver and in `drive_lifetimes` (`reappeared_after_failure`).

## 2026-10-14 — Backfill audit across all 12 quarters (silver, `backblaze.ops.quarter_status`)

- Duplicate (date, serial) rows: 0 in every quarter. Null capacity after the model fallback: 0 in every quarter.
- Drives reappearing after a failure row: 10, 17, 23, 47, 32, 41 in Q3 2023 – Q4 2024, then **0 in every
  quarter from Q1 2025**. This looks like a change in how Backblaze produces the files (failure flags
  reconciled before publication). The final-row rule handles both regimes; LIMITATIONS notes that failure
  semantics are not perfectly uniform across the window.
- Capacity inconsistencies: one ST4000DM000 drive reported 137,438,952,960 bytes on 2 of its days in Q3 2024
  (a bad reading); the per-drive most-frequent rule assigns it 4 TB. Two rows in Q3 2024 used the model fallback.

## 2026-10-14 — SMART 9 wraparound: two more models found by the pipeline guard

- The `drive_lifetimes` guard failed the first full-scope build, as designed: ST6000DX000 (850 drives) and
  ST4000DM000 (4 drives) wrap at the same point, 78,187 → ~0 h, as ST8000NM0055/ST8000DM002. The wrap is a
  Seagate counter behavior on these older models, not model-specific.
- Both models are long-discontinued and present only in 2023–2024 quarters. Corrected mean ages, sampled on
  2023-07-01, 2024-01-01 and 2024-07-01: ST4000DM000 7.85 years (17,899 drives); ST6000DX000 8.44 years
  (883 drives). Both were added to `WRAP_MODELS`. Backblaze's published tables for those quarters were not
  transcribed, so these two models' ages are checked for plausibility only, not against published averages.

## 2026-10-14 — Full-scope age and failure-count fixes (found after the first full gold build)

- **Unknown age jumped to 37,935 data drives (9.4%)** in the first full-scope `drive_lifetimes`, from 134 in the
  Q2 2026 slice. Two causes:
  1. **Missing SMART on a drive's first row** (~36k drives, mostly new WUH722222ALE6L4, MG08ACA16TA,
     WUH721816ALE6L4, MG10ACA20TE). Age now anchors on the drive's first and last **non-null** SMART 9 readings,
     back-dated to the first observed day (`entry_age_days = poh_first/24 - days(first reading - first day)`).
  2. **Young replacement drives of wrapping models** (782 ST8000NM0055/ST8000DM002 drives starting ~10k h). The
     fixed rule "below 30,000 h means wrapped" added 78,188 h to them by mistake. **New rule:** SMART 240 (head
     flying hours) does not wrap on these drives. On wrapped drives it exceeds SMART 9 by ~78,100 h (median); on
     unwrapped drives the two agree within ~100 h (2026-06-30 snapshot). A reading is wrapped iff
     `SMART 240 - SMART 9 > 39,094` (half the modulus). The fixed threshold is kept only as a fallback when
     SMART 240 is missing.
  - Validation after both fixes: mean age per model within 1.5 months of Backblaze's published average for
    30/31 models (Q2 2026) and 31/33 (Q1 2026). Persistent outliers are MG08ACA16TA (+3.1 months in both
    quarters) and HMS5C4040BLE640 (+2.4, Q1 2026). Our ages run slightly high overall (typically +0.2 to
    +1.4 months), consistent with Backblaze measuring age differently, e.g. from deployment date
    (`results/validation/age_check_Q1_2026.csv`, `age_check_Q2_2026.csv`).
- **Failure counts aligned across gold tables:** `model_period_stats.failures` counted every raw `failure=1`
  row (13,582) while `drive_lifetimes` counted final-row failures (13,255). The difference is the drives that
  reappeared after a failure flag, which Backblaze's own rule treats as not failed. `failures` now uses the
  final-row rule in both tables; raw flags are kept in a new `failure_flags` column. Validation against
  Backblaze's Q1/Q2 2026 tables is unaffected: no reappearances occur from Q1 2025 on.
