-- 30_analysis_queries.sql
-- Each query answers one reliability question (stated in its comment). Outputs are saved to results/sql/
-- by: uv run python scripts/dbsql.py -f databricks/sql/30_analysis_queries.sql
-- Queries over Bayesian / survival / early-warning results are added in Phase 6.

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
