-- 30_analysis_queries.sql
-- Each query answers one reliability question (stated in its comment). Outputs are saved to results/sql/
-- by: uv run python scripts/dbsql.py -f databricks/sql/30_analysis_queries.sql

-- name: q01_afr_by_model
-- Which drive models fail most often (Backblaze AFR), using Backblaze's quarterly inclusion rule
-- (drive count > 100 and drive-days > 10,000 in the quarter)?
SELECT quarter, manufacturer, model_short, capacity_tb, drive_count, drive_days, failures,
       ROUND(afr_pct, 2) AS afr_pct, ROUND(mean_age_years, 1) AS mean_age_years
FROM backblaze.analytics.model_quarter_afr
WHERE drive_count > 100 AND drive_days > 10000
ORDER BY quarter, afr_pct DESC;

-- name: q02_afr_by_manufacturer_capacity
-- Does failure rate differ by manufacturer and capacity class across the fleet?
SELECT manufacturer, capacity_tb, SUM(drives) AS drives, SUM(drive_days) AS drive_days, SUM(failures) AS failures,
       ROUND(SUM(failures) / (CAST(SUM(drive_days) AS DOUBLE) / 365) * 100, 2) AS afr_pct
FROM backblaze.analytics.model_window_afr
GROUP BY manufacturer, capacity_tb
ORDER BY manufacturer, capacity_tb;

-- name: q03_afr_by_age_year
-- Is there early-life failure or wear-out? AFR by drive age (years of power-on time).
SELECT manufacturer, age_year, drive_days, failures, ROUND(afr_pct, 2) AS afr_pct
FROM backblaze.analytics.age_year_afr
WHERE drive_days >= 10000
ORDER BY manufacturer, age_year;

-- name: q04_warning_lead_time
-- When a critical SMART attribute (5/187/188/197/198) turns nonzero before failure, how many days of warning
-- does it give? Lead-time distribution by manufacturer, including failures with no warning at all.
-- (Uses LAG to find the onset day: the first day the flag goes from 0 to 1.)
WITH flags AS (
  SELECT f.serial_number, f.date, f.any_crit_now,
         LAG(f.any_crit_now) OVER (PARTITION BY f.serial_number ORDER BY f.date) AS prev_flag
  FROM backblaze.gold.drive_day_features f
  JOIN backblaze.gold.drive_lifetimes l USING (serial_number)
  WHERE l.failed = 1
), onset AS (
  SELECT serial_number, MIN(date) AS first_onset
  FROM flags WHERE any_crit_now = 1 AND COALESCE(prev_flag, 0) = 0
  GROUP BY serial_number
)
SELECT l.manufacturer,
       COUNT(*) AS failed_drives,
       SUM(CASE WHEN o.first_onset IS NULL THEN 1 ELSE 0 END) AS no_warning,
       SUM(CASE WHEN DATEDIFF(l.failure_date, o.first_onset) >= 7 THEN 1 ELSE 0 END) AS warned_7d_plus,
       SUM(CASE WHEN DATEDIFF(l.failure_date, o.first_onset) >= 30 THEN 1 ELSE 0 END) AS warned_30d_plus,
       PERCENTILE(DATEDIFF(l.failure_date, o.first_onset), 0.5) AS median_lead_days
FROM backblaze.gold.drive_lifetimes l
LEFT JOIN onset o USING (serial_number)
WHERE l.is_data_drive AND l.failed = 1
GROUP BY l.manufacturer
ORDER BY l.manufacturer;

-- name: q05_fleet_composition
-- How is the fleet composed (manufacturer x capacity), and how is it shifting quarter to quarter?
SELECT quarter, manufacturer, capacity_tb, drives, drive_days, failures
FROM backblaze.analytics.fleet_composition
ORDER BY quarter, manufacturer, capacity_tb;

-- name: q06_bayes_afr_by_model
-- Which drive models are riskiest once small populations are accounted for? Bayesian AFR with 90% intervals,
-- by manufacturer and capacity, with drive-days so the interval width is explainable.
SELECT manufacturer, model, capacity_tb, drive_days, failures, ROUND(raw_afr, 2) AS raw_afr,
       ROUND(bayes_afr, 2) AS bayes_afr, ROUND(bayes_afr_lo, 2) AS bayes_afr_lo, ROUND(bayes_afr_hi, 2) AS bayes_afr_hi
FROM backblaze.analytics.model_risk
ORDER BY bayes_afr DESC;

-- name: q07_raw_vs_bayes_disagreement
-- Where would ranking models on raw AFR mislead us? Models whose raw AFR and posterior differ most.
SELECT model, manufacturer, drive_days, failures, ROUND(raw_afr, 2) AS raw_afr, ROUND(bayes_afr, 2) AS bayes_afr,
       ROUND(bayes_afr_lo, 2) AS lo, ROUND(bayes_afr_hi, 2) AS hi, ROUND(ABS(raw_afr - bayes_afr), 2) AS abs_diff
FROM backblaze.analytics.model_risk
ORDER BY abs_diff DESC
LIMIT 15;

-- name: q08_replace_first
-- Which models should be watched or replaced first? Posterior AFR together with hazard shape
-- (wear-out = rising risk with age, so the trailing AFR understates next year).
SELECT model, manufacturer, drive_days, ROUND(bayes_afr, 2) AS bayes_afr, ROUND(bayes_afr_lo, 2) AS lo,
       ROUND(bayes_afr_hi, 2) AS hi, ROUND(shape_k, 2) AS weibull_k, hazard_shape
FROM backblaze.analytics.model_risk
WHERE shape_k IS NOT NULL
ORDER BY CASE WHEN hazard_shape = 'increasing' THEN 0 ELSE 1 END, bayes_afr DESC;

-- name: q09_alerts_per_week
-- How many alerts per week would the team handle? Test period (Q3 2025 - Q2 2026, 30% of drives), LightGBM at the
-- 5 / 1,000 operating point vs the any-nonzero SMART rule, with how many alerted drive-days preceded a failure within 30 days.
SELECT DATE_TRUNC('WEEK', date) AS week,
       COUNT(DISTINCT serial_number) AS drives_reporting,
       SUM(lgbm_alert_5_per_1000) AS lgbm_alert_drive_days,
       SUM(CASE WHEN lgbm_alert_5_per_1000 = 1 AND fail_30d = 1 THEN 1 ELSE 0 END) AS lgbm_true_alert_days,
       SUM(rule_alert) AS rule_alert_drive_days,
       SUM(CASE WHEN rule_alert = 1 AND fail_30d = 1 THEN 1 ELSE 0 END) AS rule_true_alert_days
FROM backblaze.analytics.ew_daily_alerts
GROUP BY 1
ORDER BY 1;

-- name: q10_lgbm_alert_onset_lead_time
-- When the model starts alerting on a drive that later fails, how many days of warning does the first alert onset
-- give? Uses LAG to find 0 -> 1 transitions of the 5 / 1,000 alert; distribution by manufacturer (test period).
WITH flags AS (
  SELECT serial_number, manufacturer, date, days_to_failure, lgbm_alert_5_per_1000 AS a,
         LAG(lgbm_alert_5_per_1000) OVER (PARTITION BY serial_number ORDER BY date) AS prev_a
  FROM backblaze.analytics.ew_daily_alerts
  WHERE days_to_failure IS NOT NULL AND days_to_failure >= 0
), onset AS (
  SELECT serial_number, manufacturer, MAX(days_to_failure) AS lead_days   -- earliest onset = most days before failure
  FROM flags WHERE a = 1 AND COALESCE(prev_a, 0) = 0
  GROUP BY serial_number, manufacturer
), failed AS (
  SELECT DISTINCT serial_number, manufacturer FROM flags
)
SELECT f.manufacturer, COUNT(*) AS failed_drives, COUNT(o.lead_days) AS alerted,
       SUM(CASE WHEN o.lead_days >= 7 THEN 1 ELSE 0 END) AS alerted_7d_plus,
       SUM(CASE WHEN o.lead_days >= 30 THEN 1 ELSE 0 END) AS alerted_30d_plus,
       PERCENTILE(o.lead_days, 0.5) AS median_lead_days
FROM failed f LEFT JOIN onset o USING (serial_number, manufacturer)
GROUP BY f.manufacturer
ORDER BY f.manufacturer;

-- name: q11_forecast_vs_hazard
-- Can last period's failure rate be trusted as next year's budget? Out-of-time forecast vs actual failures,
-- next to each model's hazard shape.
SELECT o.model, o.drive_days, o.pred_lo, o.pred_median, o.pred_hi, o.actual, o.covered,
       ROUND(h.shape_k, 2) AS weibull_k, h.hazard_shape
FROM backblaze.gold.res_out_of_time_predictions o
LEFT JOIN backblaze.gold.res_weibull_by_model h USING (model)
ORDER BY o.drive_days DESC;

-- name: q12_fleet_afr_trend
-- Is the fleet getting more or less reliable quarter to quarter? Fleet-wide AFR (data drives) by quarter.
SELECT quarter, SUM(drive_count) AS drives, SUM(drive_days) AS drive_days, SUM(failures) AS failures,
       ROUND(SUM(failures) / (CAST(SUM(drive_days) AS DOUBLE) / 365) * 100, 2) AS fleet_afr_pct
FROM backblaze.analytics.model_quarter_afr
GROUP BY quarter
ORDER BY quarter;
