-- 40_tableau_extracts.sql
-- Aggregate-only extracts for Tableau Public (no drive-level identifiers; all far below the 15M-row limit).
-- Export: uv run python scripts/dbsql.py -f databricks/sql/40_tableau_extracts.sql -o tableau

-- name: extract_fleet_reliability
-- View 1 (fleet reliability): Bayesian AFR with 90% interval per data-drive model, with drive-days so the
-- interval width is explainable, plus raw AFR and hazard shape.
SELECT model, manufacturer, capacity_tb, drives, drive_days, failures,
       raw_afr, bayes_afr, bayes_afr_lo, bayes_afr_hi, interval_width, shape_k, hazard_shape
FROM backblaze.analytics.model_risk
ORDER BY bayes_afr DESC;

-- name: extract_survival_curves
-- View 2 (lifetime risk): Kaplan-Meier survival by age in years, per model (>= 500 drives) and per manufacturer.
SELECT level, name, manufacturer, age, survival, ci_lower, ci_upper, at_risk, start_age, drives, failures
FROM backblaze.analytics.survival_curves
ORDER BY level, name, age;

-- name: extract_ew_tradeoff
-- View 3a (early warning): alerts per 1,000 drive-days vs share of failure-days caught, test period.
SELECT alert_model, budget_per_1000, recall, precision, false_alarms_per_1000
FROM backblaze.analytics.ew_tradeoff
ORDER BY alert_model, budget_per_1000;

-- name: extract_ew_lead_times
-- View 3b (early warning): days of warning for each failed test drive at the LightGBM 5 / 1,000 operating point
-- (first alert onset; null = never alerted). One row per failed test drive, no serial numbers.
WITH flags AS (
  SELECT serial_number, manufacturer, days_to_failure, lgbm_alert_5_per_1000 AS a,
         LAG(lgbm_alert_5_per_1000) OVER (PARTITION BY serial_number ORDER BY date) AS prev_a
  FROM backblaze.analytics.ew_daily_alerts
  WHERE days_to_failure IS NOT NULL AND days_to_failure >= 0
)
SELECT manufacturer,
       MAX(CASE WHEN a = 1 AND COALESCE(prev_a, 0) = 0 THEN days_to_failure END) AS lead_days,
       CASE WHEN MAX(CASE WHEN a = 1 AND COALESCE(prev_a, 0) = 0 THEN days_to_failure END) IS NULL THEN 'not alerted'
            WHEN MAX(CASE WHEN a = 1 AND COALESCE(prev_a, 0) = 0 THEN days_to_failure END) >= 30 THEN '30+ days'
            WHEN MAX(CASE WHEN a = 1 AND COALESCE(prev_a, 0) = 0 THEN days_to_failure END) >= 7 THEN '7-29 days'
            ELSE '0-6 days' END AS lead_bucket
FROM flags
GROUP BY serial_number, manufacturer;

-- name: extract_model_quarter_afr
-- Supporting: raw AFR per data-drive model per quarter (Backblaze formula).
SELECT quarter, manufacturer, model_short AS model, capacity_tb, drive_count, drive_days, failures,
       afr_pct, mean_age_years
FROM backblaze.analytics.model_quarter_afr
ORDER BY quarter, manufacturer, model;
