"""Write results/scale.json: the exact processed scope, from the Databricks pipeline's own tables and checks.
These are the only scale numbers allowed in the README. Usage: uv run python scripts/write_scale.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dbsql import run  # noqa: E402


def one(sql):
    cols, rows = run(sql)
    return dict(zip(cols, rows[0]))


s = one("""SELECT min(date) min_date, max(date) max_date, count(*) drive_day_rows, count(DISTINCT serial_number) drives,
                  count(DISTINCT model) models, sum(failure) failure_flags,
                  count(DISTINCT quarter) quarters FROM backblaze.silver.drive_stats""")
d = one("""SELECT count(*) data_drives, sum(n_obs_days) data_drive_days, sum(failed) data_drive_failures,
                  count(DISTINCT model) data_drive_models FROM backblaze.gold.drive_lifetimes WHERE is_data_drive""")
a = one("SELECT count(*) all_drives, sum(failed) counted_failures FROM backblaze.gold.drive_lifetimes")
f = one("SELECT count(*) feature_rows FROM backblaze.gold.drive_day_features")
cols, rows = run("SELECT quarter, row_count FROM backblaze.ops.quarter_status WHERE stage = 'silver' ORDER BY quarter")
qs = {q: int(n) for q, n in rows}
cols, rows = run("SELECT quarter, details FROM backblaze.ops.quarter_status WHERE stage = 'features'")
feat = {q: json.loads(det) for q, det in rows}
out = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": "Backblaze Drive Stats quarterly files, https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data",
    "date_range": [s["min_date"], s["max_date"]],
    "quarters": sorted(qs, key=lambda q: (q[3:], q[1])),
    "rows_per_quarter": qs,
    "all_drives": {"drive_day_rows": int(s["drive_day_rows"]), "drives": int(s["drives"]),
                   "models": int(s["models"]), "counted_failures": int(a["counted_failures"]),
                   "raw_failure_flags": int(s["failure_flags"])},
    "data_drives_ge_4tb": {"drive_day_rows": int(d["data_drive_days"]), "drives": int(d["data_drives"]),
                           "models": int(d["data_drive_models"]), "failures": int(d["data_drive_failures"])},
    "drive_day_feature_rows": int(f["feature_rows"]),
    "feature_reference_check": {"rows_compared": sum(v["reference_check_rows"] for v in feat.values()),
                                "mismatches": sum(len(v["reference_mismatches"]) for v in feat.values())},
}
assert int(s["quarters"]) == 12 and sum(qs.values()) == out["all_drives"]["drive_day_rows"]
(ROOT / "results/scale.json").write_text(json.dumps(out, indent=2))
print(json.dumps({k: v for k, v in out.items() if k not in ("rows_per_quarter", "quarters")}, indent=2))
