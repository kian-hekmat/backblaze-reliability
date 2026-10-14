"""Phase 1 profiling of one raw Backblaze quarter, run locally with DuckDB.

Reads the quarter's daily CSVs directly (all columns as strings, exactly as in the files)
and writes every profiling output to results/profiling/<quarter>/.

Usage:
    uv run python scripts/profile_quarter.py data/raw/csv/Q2_2026/data_Q2_2026 Q2_2026
"""

import json
import sys
from pathlib import Path

import duckdb

csv_dir, quarter = Path(sys.argv[1]), sys.argv[2]
out = Path("results/profiling") / quarter
out.mkdir(parents=True, exist_ok=True)
work = Path("data/work")
work.mkdir(parents=True, exist_ok=True)
pq = work / f"{quarter}_raw.parquet"

con = duckdb.connect()
con.execute("SET memory_limit='12GB'")

# 1. Raw strings -> local Parquet cache (no typing, no filtering). Empty CSV fields become NULL.
if not pq.exists():
    con.execute(f"""
        COPY (SELECT * FROM read_csv('{csv_dir}/*.csv', all_varchar=true, header=true,
                                      union_by_name=true, filename=true))
        TO '{pq}' (FORMAT parquet)
    """)
con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{pq}')")
cols = [r[0] for r in con.execute("DESCRIBE raw").fetchall() if r[0] != "filename"]

summary = {}
q = lambda sql: con.execute(sql).fetchall()

# 2. Basic scale
(summary["rows"], summary["distinct_dates"], summary["min_date"], summary["max_date"],
 summary["distinct_serials"], summary["distinct_models"]) = q("""
    SELECT count(*), count(DISTINCT date), min(date), max(date),
           count(DISTINCT serial_number), count(DISTINCT model) FROM raw""")[0]
summary["failure_values"] = dict(q("SELECT coalesce(failure,'<null>'), count(*) FROM raw GROUP BY 1"))
summary["rows_where_date_ne_filename"] = q(
    "SELECT count(*) FROM raw WHERE date <> regexp_extract(filename, '(\\d{4}-\\d{2}-\\d{2})\\.csv', 1)")[0][0]

# 3. Null rate and inferred type for every column
null_rows = []
for c in cols:
    n_null, n_distinct, n_numeric, sample = q(f"""
        SELECT count(*) - count("{c}"), approx_count_distinct("{c}"),
               count(TRY_CAST("{c}" AS DOUBLE)), any_value("{c}") FROM raw""")[0]
    n_nonnull = summary["rows"] - n_null
    null_rows.append({
        "column": c, "null_rate": n_null / summary["rows"], "approx_distinct": n_distinct,
        "all_nonnull_numeric": n_nonnull > 0 and n_numeric == n_nonnull, "sample": sample})
con.execute("CREATE TABLE nulls AS SELECT * FROM (SELECT unnest($1, recursive := true))", [null_rows])
con.execute(f"COPY nulls TO '{out}/column_profile.csv' (HEADER)")

# 4. Duplicate (date, serial) rows
summary["duplicate_date_serial_groups"], summary["duplicate_extra_rows"] = q("""
    SELECT count(*), coalesce(sum(n - 1), 0) FROM (
      SELECT date, serial_number, count(*) n FROM raw GROUP BY 1, 2 HAVING count(*) > 1)""")[0]
summary["exact_duplicate_extra_rows"] = summary["rows"] - q("SELECT count(*) FROM (SELECT DISTINCT * EXCLUDE (filename) FROM raw)")[0][0]
summary["null_serial_rows"] = q("SELECT count(*) FROM raw WHERE serial_number IS NULL")[0][0]
summary["null_model_rows"] = q("SELECT count(*) FROM raw WHERE model IS NULL")[0][0]

# 5. Per-drive observation pattern: gaps between first and last observed day
con.execute("""
    CREATE TABLE per_drive AS
    SELECT serial_number, min(date::DATE) first_d, max(date::DATE) last_d,
           count(DISTINCT date) n_days, max(failure::INT) failed,
           count(DISTINCT model) n_models, count(DISTINCT capacity_bytes) n_caps,
           count(*) FILTER (WHERE failure = '1') n_failure_rows
    FROM raw GROUP BY 1""")
con.execute(f"""CREATE VIEW per_drive2 AS SELECT *, datediff('day', first_d, last_d) + 1 - n_days AS missing_days
    FROM per_drive""")
summary["drives_with_missing_days"] = q("SELECT count(*) FROM per_drive2 WHERE missing_days > 0")[0][0]
summary["total_missing_drive_days"] = q("SELECT sum(missing_days) FROM per_drive2")[0][0]
summary["missing_days_distribution"] = dict(q("""
    SELECT CASE WHEN missing_days = 0 THEN '0' WHEN missing_days <= 2 THEN '1-2'
                WHEN missing_days <= 7 THEN '3-7' WHEN missing_days <= 30 THEN '8-30' ELSE '>30' END b,
           count(*) FROM per_drive2 GROUP BY 1 ORDER BY 1"""))
summary["drives_with_multiple_models"] = q("SELECT count(*) FROM per_drive WHERE n_models > 1")[0][0]
summary["drives_with_multiple_capacities"] = q("SELECT count(*) FROM per_drive WHERE n_caps > 1")[0][0]

# 6. Failure semantics
summary["failed_drives"] = q("SELECT count(*) FROM per_drive WHERE failed = 1")[0][0]
summary["drives_with_more_than_one_failure_row"] = q("SELECT count(*) FROM per_drive WHERE n_failure_rows > 1")[0][0]
summary["failed_drives_observed_after_failure_date"] = q("""
    SELECT count(DISTINCT r.serial_number) FROM raw r
    JOIN (SELECT serial_number, min(date) fd FROM raw WHERE failure = '1' GROUP BY 1) f USING (serial_number)
    WHERE r.date > f.fd""")[0][0]
summary["failed_drives_failure_on_last_observed_day"] = q("""
    SELECT count(*) FROM per_drive p
    JOIN (SELECT serial_number, min(date::DATE) fd FROM raw WHERE failure = '1' GROUP BY 1) f USING (serial_number)
    WHERE f.fd = p.last_d""")[0][0]
summary["drives_leaving_before_quarter_end_without_failure"] = q(f"""
    SELECT count(*) FROM per_drive WHERE failed = 0 AND last_d < '{summary['max_date']}'::DATE""")[0][0]
summary["drives_entering_after_quarter_start"] = q(f"""
    SELECT count(*) FROM per_drive WHERE first_d > '{summary['min_date']}'::DATE""")[0][0]

# 7. Model name formats
con.execute(f"""COPY (
    SELECT model, count(DISTINCT serial_number) drives, count(*) drive_days,
           count(*) FILTER (WHERE failure='1') failures,
           model <> trim(model) has_outer_ws, model LIKE '%  %' has_double_space,
           model <> upper(model) has_lowercase, count(DISTINCT capacity_bytes) n_capacities,
           min(capacity_bytes) min_cap, max(capacity_bytes) max_cap
    FROM raw GROUP BY model ORDER BY drives DESC) TO '{out}/models.csv' (HEADER)""")
summary["models_with_outer_whitespace"] = q("SELECT count(DISTINCT model) FROM raw WHERE model <> trim(model)")[0][0]
summary["models_colliding_after_upper_trim_collapse_ws"] = q("""
    SELECT count(*) FROM (SELECT upper(regexp_replace(trim(model), '\\s+', ' ', 'g')) k, count(DISTINCT model) n
                          FROM raw GROUP BY 1 HAVING n > 1)""")[0][0]
summary["capacity_value_counts_nonpositive"] = dict(q("""
    SELECT capacity_bytes, count(*) FROM raw WHERE TRY_CAST(capacity_bytes AS BIGINT) <= 0 GROUP BY 1"""))
summary["first_token_of_model"] = dict(q("""
    SELECT split_part(model, ' ', 1) t, count(DISTINCT model) FROM raw GROUP BY 1 ORDER BY 2 DESC"""))
summary["is_legacy_format_values"] = dict(q("SELECT coalesce(is_legacy_format,'<null>'), count(*) FROM raw GROUP BY 1")) if "is_legacy_format" in cols else None
summary["datacenter_values"] = dict(q("SELECT coalesce(datacenter,'<null>'), count(*) FROM raw GROUP BY 1")) if "datacenter" in cols else None

# 8. SMART null rate per attribute per manufacturer prefix (raw values)
smart_raw = [c for c in cols if c.startswith("smart_") and c.endswith("_raw")]
sel = ", ".join(f'avg(("{c}" IS NULL)::INT) AS "{c}"' for c in smart_raw)
con.execute(f"""COPY (
    SELECT CASE WHEN model LIKE 'ST%' OR model LIKE 'Seagate%' THEN 'Seagate'
                WHEN model LIKE 'TOSHIBA%' THEN 'Toshiba'
                WHEN model LIKE 'HGST%' OR model LIKE 'Hitachi%' THEN 'HGST'
                WHEN model LIKE 'WDC%' OR model LIKE 'WD%' THEN 'WDC'
                ELSE 'other' END AS mfr_guess, count(*) AS n_rows, {sel}
    FROM raw GROUP BY 1 ORDER BY n_rows DESC) TO '{out}/smart_null_rate_by_mfr.csv' (HEADER)""")

(out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
print(json.dumps(summary, indent=2, default=str))
