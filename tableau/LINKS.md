# Published visualizations

- **Dashboard:** [Drive Fleet Reliability](https://public.tableau.com/app/profile/kian.hekmatnejad/viz/DriveFleetReliability/Dashboard1)
  (Tableau Public). Built from the aggregate extracts in this folder, which are produced by
  `databricks/sql/40_tableau_extracts.sql` from the results in `results/`.
- **Pipeline slice test (Phase 2):** [Backblaze drive reliability: slice test](https://public.tableau.com/app/profile/kian.hekmatnejad/viz/Backblazedrivereliability-slicetest/Sheet1),
  raw AFR by model for Q2 2026 only. It was used to prove the extract → Tableau path before scaling.

| Extract | Rows | Dashboard view |
|---|---|---|
| `extract_fleet_reliability.csv` | 66 | Failure rate by drive model (Bayesian AFR, 90% interval) |
| `extract_survival_curves.csv` | 743 | Survival by drive age |
| `extract_ew_tradeoff.csv` | 25 | Alerts vs failures caught |
| `extract_ew_lead_times.csv` | 1,459 | Days of warning before failure |
| `extract_model_quarter_afr.csv` | 602 | Slice test (raw AFR per model per quarter) |

## Checks

- **Displayed numbers:** confirmed by Kian (2026-10-15) to match the check values computed from `results/`. Examples:
  top model ST12000NM0007 7.15 [5.75, 8.94]; warning-lead buckets 713 / 229 / 93 / 424 of 1,459 failed test drives.
- **Independent viewer check:** waived by Kian (2026-10-15); not performed.
