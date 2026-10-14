-- 10_analytics_views.sql
-- Serving views in backblaze.analytics for analysis queries and Tableau extracts.
-- Re-runnable (CREATE OR REPLACE). Data drives only (>= 4 TB) unless a view says otherwise.
-- Results-table views read backblaze.gold.res_* (loaded by databricks/50_load_results.py).
-- Run: uv run python scripts/dbsql.py -f databricks/sql/10_analytics_views.sql

-- Per model per quarter: AFR inputs and Backblaze-formula AFR.
CREATE OR REPLACE VIEW backblaze.analytics.model_quarter_afr AS
SELECT quarter, manufacturer, model, model_short, capacity_bytes,
       ROUND(capacity_bytes / 1e12) AS capacity_tb,
       drive_count, drive_days, failures,
       failures / (CAST(drive_days AS DOUBLE) / 365) * 100 AS afr_pct,
       mean_age_days / 365.25 AS mean_age_years
FROM backblaze.gold.model_period_stats
WHERE is_data_drive;

-- Per model over the whole loaded window: drives, drive-days, failures, AFR, age.
CREATE OR REPLACE VIEW backblaze.analytics.model_window_afr AS
SELECT s.manufacturer, s.model, s.model_short, s.capacity_bytes, ROUND(s.capacity_bytes / 1e12) AS capacity_tb,
       l.drives, s.drive_days, s.failures,
       s.failures / (CAST(s.drive_days AS DOUBLE) / 365) * 100 AS afr_pct,
       s.mean_age_years
FROM (SELECT manufacturer, model, model_short, capacity_bytes, SUM(drive_days) AS drive_days, SUM(failures) AS failures,
             SUM(mean_age_days * drive_days) / SUM(drive_days) / 365.25 AS mean_age_years
      FROM backblaze.gold.model_period_stats WHERE is_data_drive
      GROUP BY ALL) s
JOIN (SELECT model, COUNT(*) AS drives FROM backblaze.gold.drive_lifetimes WHERE is_data_drive GROUP BY model) l
  USING (model);

-- Per age year (from wraparound-corrected SMART 9) per manufacturer: early-life vs. wear-out view.
CREATE OR REPLACE VIEW backblaze.analytics.age_year_afr AS
SELECT manufacturer, age_year, SUM(drive_days) AS drive_days, SUM(failures) AS failures,
       SUM(failures) / (CAST(SUM(drive_days) AS DOUBLE) / 365) * 100 AS afr_pct
FROM backblaze.gold.model_age_stats
WHERE is_data_drive AND age_year >= 0
GROUP BY manufacturer, age_year;

-- Fleet composition per quarter: drives and drive-days by manufacturer and capacity.
CREATE OR REPLACE VIEW backblaze.analytics.fleet_composition AS
SELECT quarter, manufacturer, ROUND(capacity_bytes / 1e12) AS capacity_tb,
       SUM(drive_count) AS drives, SUM(drive_days) AS drive_days, SUM(failures) AS failures
FROM backblaze.gold.model_period_stats
WHERE is_data_drive
GROUP BY ALL;

-- One row per failed data drive: first day any critical SMART attribute (5/187/188/197/198) was nonzero
-- before failure, and the warning lead time in days (null = no warning from this rule).
CREATE OR REPLACE VIEW backblaze.analytics.failed_drive_warning AS
SELECT l.serial_number, l.manufacturer, l.model, l.failure_date,
       w.first_warning_date,
       DATEDIFF(l.failure_date, w.first_warning_date) AS warning_lead_days
FROM backblaze.gold.drive_lifetimes l
LEFT JOIN (SELECT serial_number, MIN(date) AS first_warning_date
           FROM backblaze.gold.drive_day_features WHERE any_crit_now = 1 GROUP BY serial_number) w
  USING (serial_number)
WHERE l.is_data_drive AND l.failed = 1;

-- Per model: raw AFR, Bayesian posterior AFR with 90% interval, and Weibull hazard shape (where >= 30 failures).
CREATE OR REPLACE VIEW backblaze.analytics.model_risk AS
SELECT b.model, b.manufacturer, w.capacity_tb, b.drive_days, b.failures, w.drives,
       b.raw_afr, b.afr_observed_mix_median AS bayes_afr, b.afr_observed_mix_lo AS bayes_afr_lo,
       b.afr_observed_mix_hi AS bayes_afr_hi, b.afr_observed_mix_hi - b.afr_observed_mix_lo AS interval_width,
       h.shape_k, h.shape_lo95, h.shape_hi95, h.hazard_shape
FROM backblaze.gold.res_bayes_estimates b
LEFT JOIN backblaze.analytics.model_window_afr w USING (model)
LEFT JOIN backblaze.gold.res_weibull_by_model h USING (model);

-- Kaplan-Meier survival by age (years), per model and per manufacturer (delayed entry, >= 100 at risk start).
CREATE OR REPLACE VIEW backblaze.analytics.survival_curves AS
SELECT 'model' AS level, model AS name, manufacturer, age, survival, ci_lower, ci_upper, at_risk, start_age, drives, failures
FROM backblaze.gold.res_km_by_model
UNION ALL
SELECT 'manufacturer', manufacturer, manufacturer, age, survival, ci_lower, ci_upper, at_risk, start_age, drives, failures
FROM backblaze.gold.res_km_by_manufacturer;

-- Early-warning trade-off: alerts per 1,000 drive-days vs share of failure-days caught (test period, natural distribution).
CREATE OR REPLACE VIEW backblaze.analytics.ew_tradeoff AS
SELECT model AS alert_model, budget_per_1000, recall, precision, false_alarms_per_1000
FROM backblaze.gold.res_ew_tradeoff_30d;

-- Test-period drive-day scores with the LightGBM alert at the 5 / 1,000 operating point.
CREATE OR REPLACE VIEW backblaze.analytics.ew_daily_alerts AS
SELECT s.serial_number, s.date, s.manufacturer, s.days_to_failure, s.fail_30d, s.score_lightgbm, s.rule_alert,
       CAST(s.score_lightgbm >= t.threshold AS INT) AS lgbm_alert_5_per_1000
FROM backblaze.gold.res_ew_test_scores_30d s
CROSS JOIN (SELECT threshold FROM backblaze.gold.res_ew_metrics_30d
            WHERE model = 'lightgbm' AND budget_per_1000 = 5.0) t;
