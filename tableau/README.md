# Tableau

Aggregate-only CSV extracts exported from Databricks SQL (`databricks/sql/40_tableau_extracts.sql`):

```bash
uv run python scripts/dbsql.py -f databricks/sql/40_tableau_extracts.sql -o tableau
```

Tableau Public cannot connect live to Databricks, so every view is built from these files. Kian builds and
publishes the dashboard using the **Phase 7 build spec** below. Every number on the dashboard comes from these
extracts, which come from `results/` (see `docs/RESULTS.md`).

| File | Rows | Used in |
|---|---|---|
| `extract_fleet_reliability.csv` | 66 | View 1 |
| `extract_survival_curves.csv` | 743 | View 2 |
| `extract_ew_tradeoff.csv` | 25 | View 3a |
| `extract_ew_lead_times.csv` | 1,459 | View 3b |
| `extract_model_quarter_afr.csv` | 602 | Supporting (Phase 2 test view) |

---

## Phase 2: rough slice view (one quarter, raw AFR by model)

**Purpose:** prove the extract → Tableau Public path works. It doesn't need to look good.
**Time:** about 15 minutes.

### 1. Install and open
1. Install **Tableau Public** (free desktop app): https://public.tableau.com/app/discover → "Create" → download.
2. Sign in, or create a free Tableau Public account. Saving requires it, and workbooks are public.

### 2. Connect to the extract
1. Start page → **Connect → To a File → Text file**.
2. Choose `tableau/extract_model_quarter_afr.csv` from this repo.
3. On the Data Source page, check the column types (click the type icon above a column to change it):
   - `quarter`, `manufacturer`, `model`: String (Abc)
   - `capacity_tb`: change it to a **Dimension** later (right-click the field → Convert to Dimension)
   - `drive_count`, `drive_days`, `failures`, `afr_pct`, `mean_age_years`: Number
4. Click **Sheet 1** at the bottom left.

### 3. Create the AFR calculation (do not sum `afr_pct`)
Summing or averaging per-row AFRs is wrong once more than one quarter is in the data. Compute AFR from the
summed inputs instead, which matches Backblaze's formula:

1. **Analysis → Create Calculated Field…**
2. Name: `AFR %`
3. Formula:
   ```
   SUM([failures]) / (SUM([drive_days]) / 365) * 100
   ```
4. OK.

### 4. Build the bar chart
1. Drag `model` to **Rows**.
2. Drag `AFR %` to **Columns**.
3. Drag `manufacturer` to **Color** on the Marks card.
4. Drag `drive_days`, `drive_count` and `failures` to **Tooltip** on the Marks card.
5. Sort descending: hover over the `AFR %` axis and click the sort icon (or toolbar → Sort Descending).
6. Drag `quarter` to **Filters** → select only **Q2_2026** (the extract now holds all 12 quarters).
   Then apply Backblaze's quarterly inclusion rule so tiny populations don't dominate:
   - Drag `drive_count` to **Filters** → choose **Sum** → set **At least** to `101` → OK.
   - Drag `drive_days` to **Filters** → **Sum** → **At least** `10001` → OK.
7. Drag `AFR %` onto **Label** on the Marks card to show values. Right-click the label → Format → Numbers →
   Number (Custom), 2 decimal places.
8. Rename the sheet (double-click the tab): `AFR by model, Q2 2026 (raw)`.

### 5. Check the numbers (required)
With the filters on, you should see **31 models**. The top three should be:

| model | AFR % | drive_count | failures |
|---|---|---|---|
| ST10000NM0086 | 9.75 | 965 | 23 |
| ST14000NM0138 | 8.26 | 1,235 | 25 |
| HUH721212ALN604 | 7.63 | 9,694 | 180 |

These come from `results/sql/q01_afr_by_model.csv`. If Tableau shows different values, the calculated field or
a filter is wrong. Don't adjust anything to force a match; tell Claude what you see.

(ST10000NM0086 shows 9.75% here; Backblaze's published table shows 9.33% with 22 failures instead of 23.
Phase 4 investigates differences like this one.)

### 6. Save
1. **File → Save to Tableau Public As…** → name: `Backblaze drive reliability — slice test`.
2. It opens in the browser. Copy the URL into `tableau/LINKS.md` (or send it to Claude).

This view is throwaway; the real dashboard is built in Phase 7.


---

## Phase 7: the dashboard (three views + captions)

**Time:** about 1.5–2 hours. Build each view as its own sheet, then combine them on one dashboard. Each step ends with
values to check. If a value doesn't match, stop and tell Claude what you see; don't adjust anything to force a match.

### Connect all four data sources
Data → New Data Source → Text file, once per file: `extract_fleet_reliability.csv`, `extract_survival_curves.csv`,
`extract_ew_tradeoff.csv`, `extract_ew_lead_times.csv`. Keep them as separate data sources (no joins needed).

### View 1: Fleet reliability (sheet name: `Failure rate by drive model`)
Data source: `extract_fleet_reliability`.
1. Filter: drag `drive_days` to Filters → All values (not Sum) → Range of values → **At least 1,000,000**.
   This keeps the 26 high-volume models; small models are covered in the caption.
2. Drag `model` to **Rows**. Drag `bayes_afr` to **Columns** (it should show as SUM; since there is one row per model,
   SUM is fine here).
3. Change the mark type to **Circle**.
4. **Interval bars:** drag `bayes_afr_lo` onto the `bayes_afr` axis until a double-green-ruler icon appears (this
   creates Measure Values), then add `bayes_afr_hi`. Alternative: Analysis → Create Calculated Field `interval`:
   `[bayes_afr_hi] - [bayes_afr_lo]`. Then put `bayes_afr_lo` on Columns, mark type **Gantt Bar**, and drag `interval`
   to **Size**. Either way, each model shows a line from lo to hi with a dot at the median.
5. Color by `manufacturer`. Sort `model` descending by `bayes_afr`.
6. Tooltip: `drive_days`, `failures`, `raw_afr`, `hazard_shape`. Label the dot with `bayes_afr` (2 decimals).
7. Axis title: `Annualized failure rate (%), posterior median and 90% interval`.

**Check:** 26 models. Top three: ST12000NM0007 **7.15** [5.75, 8.94], ST14000NM0138 **5.97** [4.79, 7.40],
ST10000NM0086 **5.54** [4.38, 6.93]. Lowest: HGST HMS5C4040BLE640 **0.27**.

**Caption (paste under the view):** *Some drive models fail 8–13× as often as the best high-volume models. Intervals
are wider where there are fewer drive-days; small populations are not ranked on raw failure rate alone.*

### View 2: Lifetime risk (sheet name: `Survival by drive age`)
Data source: `extract_survival_curves`.
1. Filter `level` = **manufacturer**.
2. `age` to **Columns** (continuous, green; right-click → Dimension, Continuous if it shows as a measure). `survival`
   to **Rows** (as AVG, since one row per manufacturer × age).
3. Mark type **Line**. Color by `name`.
4. Confidence band (optional): Analysis → Create Calculated Field `band`: `AVG([ci_upper]) - AVG([ci_lower])`. Duplicate
   the sheet, mark type Area with `ci_lower`/`band`, then use it as a dual axis. Skip this if it takes too long; the
   lines alone are enough.
5. Y-axis: edit axis → fixed range 0.80 to 1.00. Title: `Share of drives still running`. X-axis title:
   `Drive age (years of power-on time)`.
6. Second sheet (optional, recommended): same build with `level` = **model** and a `name` filter showing a few
   contrasting models: TOSHIBA MG07ACA14TA (wear-out), WDC WUH722222ALE6L4 (early-life), Seagate ST12000NM0008 (flat).

**Check (level = manufacturer, age = 5.0):** HGST **0.890**, Seagate **0.936**, Toshiba **0.946**, WDC **0.961**.
Curves start at age 0.25 (the first age with at least 100 drives at risk).

**Caption:** *Survival is shown conditional on reaching the first age with at least 100 drives observed. Of the 26
models with at least 30 failures, 11 show rising risk with age (wear-out), 4 show early-life failures that fade, and 11 are
roughly flat.*

### View 3a: Early warning trade-off (sheet name: `Alerts vs failures caught`)
Data source: `extract_ew_tradeoff`.
1. Filter `alert_model` to **lightgbm** and **simple_rule** (exclude logistic, to keep it simple).
2. `false_alarms_per_1000` to **Columns**, `recall` to **Rows** (both as AVG or SUM; one row per point).
3. Mark type **Line** for lightgbm; the simple rule is one point. Put `alert_model` on Color and on Shape.
   (Tableau draws the single rule point as a dot automatically.)
4. X-axis: logarithmic scale (edit axis → Logarithmic), title `False alarms per 1,000 drive-days`.
   Y-axis title `Share of failure-days alerted (within 30 days of failure)`, format as percent.
5. Label the points at budgets 1, 5 and 10 (right-click a mark → Mark Label → Always show).

**Check:** LightGBM at budget 5: recall **0.449**, false alarms **4.51**. Simple rule: recall **0.681**,
false alarms **79.6**.

### View 3b: Warning lead time (sheet name: `Days of warning before failure`)
Data source: `extract_ew_lead_times`.
1. `lead_bucket` to **Columns**, `Number of Records` (or CNT(`manufacturer`)) to **Rows**. Mark type **Bar**.
2. Sort buckets manually: `30+ days`, `7-29 days`, `0-6 days`, `not alerted`.
3. Color by `lead_bucket`; label with the count and percent of total (Quick Table Calculation → Percent of Total).

**Check:** 30+ days **713**, 7–29 days **229**, 0–6 days **93**, not alerted **424**; total **1,459** failed test drives.

**Caption for 3a + 3b:** *At 5 alerts per 1,000 drive-days, the model warns on about two-thirds of failing drives at
least a week ahead while flagging about 2.5% of healthy drives per year; the "any SMART error" rule flags about 10%.
About 1 in 8 failures is never flagged, almost always because the drive showed no SMART warning signs.*

### Dashboard
1. New Dashboard, size **Automatic** (or Desktop 1200 × 1600).
2. Title: `Which drives fail, when, and how much warning do we get? (Backblaze fleet, Jul 2023 – Jun 2026)`.
3. Layout: View 1 on top (full width), View 2 bottom-left, Views 3a and 3b stacked bottom-right. Add each caption as a
   Text object directly under its view.
4. Footer text: `Data: Backblaze Drive Stats (backblaze.com/cloud-storage/resources/hard-drive-test-data). 333.7M
   drive-days, 409,830 drives, Q3 2023 – Q2 2026. Methods and sources: github.com/kian-hekmat/backblaze-reliability`
   (only include the GitHub link once the repo is public).
5. **File → Save to Tableau Public As…** → `Drive Fleet Reliability`. Put the URL in `tableau/LINKS.md`.

### Viewer check (required by CLAUDE.md, Phase 7)
Show the dashboard to someone who hasn't seen the project. Without explanation, ask:
1. "Which drive models are riskiest?" They should point to the top of View 1 (Seagate 10–14 TB models).
2. "Roughly how much warning does the telemetry give?" They should say something like "about two-thirds get a week or
   more; some get none."
Record their answers (no names needed) in `tableau/LINKS.md`. If they can't answer, note what confused them and tell
Claude; the captions or layout get revised.
