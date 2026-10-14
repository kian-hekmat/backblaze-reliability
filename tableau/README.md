# Tableau

Aggregate-only CSV extracts exported from Databricks SQL (`databricks/sql/40_tableau_extracts.sql`):

```bash
uv run python scripts/dbsql.py -f databricks/sql/40_tableau_extracts.sql -o tableau
```

Tableau Public cannot connect live to Databricks, so every view is built from these files. Kian builds and
publishes the dashboard; the build spec for the final three-view dashboard is added here in Phase 7, once the
Bayesian, survival and early-warning extracts exist.

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
6. Apply Backblaze's quarterly inclusion rule so tiny populations don't dominate:
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
