-- 20_validate.sql
-- Serving-layer reconciliation: analytics views must reproduce gold totals exactly.
-- Each check returns `diff`; every diff must be 0 (scripts/validate_serving.py enforces this).
-- Results-table checks are appended when results tables exist.

-- name: validate_views
SELECT 'model_quarter_afr drive_days vs gold (data drives)' AS check_name,
       (SELECT SUM(drive_days) FROM backblaze.analytics.model_quarter_afr)
     - (SELECT SUM(drive_days) FROM backblaze.gold.model_period_stats WHERE is_data_drive) AS diff
UNION ALL
SELECT 'model_quarter_afr failures vs gold',
       (SELECT SUM(failures) FROM backblaze.analytics.model_quarter_afr)
     - (SELECT SUM(failures) FROM backblaze.gold.model_period_stats WHERE is_data_drive)
UNION ALL
SELECT 'model_window_afr drive_days vs drive_lifetimes',
       (SELECT SUM(drive_days) FROM backblaze.analytics.model_window_afr)
     - (SELECT SUM(n_obs_days) FROM backblaze.gold.drive_lifetimes WHERE is_data_drive)
UNION ALL
SELECT 'model_window_afr failures vs drive_lifetimes',
       (SELECT SUM(failures) FROM backblaze.analytics.model_window_afr)
     - (SELECT SUM(failed) FROM backblaze.gold.drive_lifetimes WHERE is_data_drive)
UNION ALL
SELECT 'model_window_afr drives vs drive_lifetimes',
       (SELECT SUM(drives) FROM backblaze.analytics.model_window_afr)
     - (SELECT COUNT(*) FROM backblaze.gold.drive_lifetimes WHERE is_data_drive)
UNION ALL
SELECT 'age_year_afr + unknown-age drive_days vs gold',
       (SELECT SUM(drive_days) FROM backblaze.analytics.age_year_afr)
     + (SELECT SUM(drive_days) FROM backblaze.gold.model_age_stats WHERE is_data_drive AND age_year < 0)
     - (SELECT SUM(drive_days) FROM backblaze.gold.model_period_stats WHERE is_data_drive)
UNION ALL
SELECT 'fleet_composition drive_days vs gold',
       (SELECT SUM(drive_days) FROM backblaze.analytics.fleet_composition)
     - (SELECT SUM(drive_days) FROM backblaze.gold.model_period_stats WHERE is_data_drive)
UNION ALL
SELECT 'failed_drive_warning rows vs failed data drives',
       (SELECT COUNT(*) FROM backblaze.analytics.failed_drive_warning)
     - (SELECT SUM(failed) FROM backblaze.gold.drive_lifetimes WHERE is_data_drive)
UNION ALL
SELECT 'model_risk rows vs Bayesian estimates',
       (SELECT COUNT(*) FROM backblaze.analytics.model_risk) - (SELECT COUNT(*) FROM backblaze.gold.res_bayes_estimates)
UNION ALL
SELECT 'Bayesian estimates drive_days vs gold (known-age data drives)',
       (SELECT SUM(drive_days) FROM backblaze.gold.res_bayes_estimates)
     - (SELECT SUM(drive_days) FROM backblaze.gold.model_age_stats WHERE is_data_drive AND age_year >= 0)
UNION ALL
SELECT 'Bayesian estimates failures vs gold (known-age data drives)',
       (SELECT SUM(failures) FROM backblaze.gold.res_bayes_estimates)
     - (SELECT SUM(failures) FROM backblaze.gold.model_age_stats WHERE is_data_drive AND age_year >= 0)
UNION ALL
SELECT 'ew_daily_alerts rows vs scores table',
       (SELECT COUNT(*) FROM backblaze.analytics.ew_daily_alerts) - (SELECT COUNT(*) FROM backblaze.gold.res_ew_test_scores_30d)
UNION ALL
SELECT 'lead-time table failed drives vs scored failed test drives',
       (SELECT COUNT(*) FROM backblaze.gold.res_ew_lead_times_30d)
     - (SELECT COUNT(DISTINCT serial_number) FROM backblaze.gold.res_ew_test_scores_30d WHERE days_to_failure IS NOT NULL);
