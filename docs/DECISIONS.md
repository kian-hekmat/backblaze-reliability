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

## 2026-10-13 — Snowflake environment

- **Account:** the existing `learning` Snowflake CLI connection (account VN04570, AWS us-east-2), confirmed by Kian.
- **Trial end date: 2026-10-22 (inferred, not confirmed).** The account's first login was
  2026-09-22 (`snowflake.account_usage.login_history`); a standard trial lasts 30 days. Kian to
  confirm from the Snowsight banner.
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
- `snowflake/01_verify_roles.sh`: Phase 0 role verification (statements that must fail can't share one SQL file).
