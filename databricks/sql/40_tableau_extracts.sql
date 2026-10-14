-- 40_tableau_extracts.sql
-- Aggregate-only extracts for Tableau Public (no drive-level rows; far below the 15M-row limit).
-- Export: uv run python scripts/dbsql.py -f databricks/sql/40_tableau_extracts.sql -o tableau
-- Extracts for Bayesian intervals, survival curves and early-warning trade-offs are added in Phase 6.

-- name: extract_model_quarter_afr
-- Fleet reliability view (raw AFR, before Bayesian intervals): one row per data-drive model per quarter.
SELECT quarter, manufacturer, model_short AS model, capacity_tb, drive_count, drive_days, failures,
       afr_pct, mean_age_years
FROM backblaze.analytics.model_quarter_afr
ORDER BY quarter, manufacturer, model;
