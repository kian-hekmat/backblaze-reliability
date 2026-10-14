-- 30_validate.sql
-- Reconciliation metrics computed in Snowflake after every load. scripts/validate_snowflake.py runs
-- this file and compares each metric with the Databricks export manifest (_manifest.json); the
-- comparison is saved under results/. Output: one row per (table_name, metric, value).

USE ROLE ANALYST_READER;
USE SECONDARY ROLES NONE;
USE WAREHOUSE BI_WH;
USE SCHEMA BACKBLAZE.GOLD;

SELECT 'drive_lifetimes' AS table_name, 'rows' AS metric, COUNT(*)::NUMBER AS value FROM DRIVE_LIFETIMES
UNION ALL SELECT 'drive_lifetimes', 'sum_failed', SUM(FAILED) FROM DRIVE_LIFETIMES
UNION ALL SELECT 'drive_lifetimes', 'sum_n_obs_days', SUM(N_OBS_DAYS) FROM DRIVE_LIFETIMES
UNION ALL SELECT 'drive_lifetimes', 'duplicate_serials', COUNT(*) - COUNT(DISTINCT SERIAL_NUMBER) FROM DRIVE_LIFETIMES
UNION ALL SELECT 'model_period_stats', 'rows', COUNT(*) FROM MODEL_PERIOD_STATS
UNION ALL SELECT 'model_period_stats', 'sum_drive_days', SUM(DRIVE_DAYS) FROM MODEL_PERIOD_STATS
UNION ALL SELECT 'model_period_stats', 'sum_failures', SUM(FAILURES) FROM MODEL_PERIOD_STATS
UNION ALL SELECT 'model_age_stats', 'rows', COUNT(*) FROM MODEL_AGE_STATS
UNION ALL SELECT 'model_age_stats', 'sum_drive_days', SUM(DRIVE_DAYS) FROM MODEL_AGE_STATS
UNION ALL SELECT 'model_age_stats', 'sum_failures', SUM(FAILURES) FROM MODEL_AGE_STATS
-- cross-table consistency inside Snowflake: lifetimes drive-days and failures equal model stats totals
UNION ALL SELECT 'cross_check', 'lifetimes_minus_stats_drive_days',
  (SELECT SUM(N_OBS_DAYS) FROM DRIVE_LIFETIMES) - (SELECT SUM(DRIVE_DAYS) FROM MODEL_PERIOD_STATS)
UNION ALL SELECT 'cross_check', 'lifetimes_minus_stats_failures',
  (SELECT SUM(FAILED) FROM DRIVE_LIFETIMES) - (SELECT SUM(FAILURES) FROM MODEL_PERIOD_STATS)
ORDER BY 1, 2;
