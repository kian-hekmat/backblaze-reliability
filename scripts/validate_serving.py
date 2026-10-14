"""Run databricks/sql/20_validate.sql and fail unless every reconciliation diff is 0.

Writes results/serving_validation.json. Usage: uv run python scripts/validate_serving.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbsql import run, split_statements  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
checks = []
for name, stmt in split_statements((ROOT / "databricks/sql/20_validate.sql").read_text()):
    cols, rows = run(stmt)
    for r in rows:
        d = dict(zip(cols, r))
        checks.append({"query": name, "check": d["check_name"], "diff": float(d["diff"]), "pass": float(d["diff"]) == 0})
ok = all(c["pass"] for c in checks)
(ROOT / "results/serving_validation.json").write_text(json.dumps(
    {"validated_at": datetime.now(timezone.utc).isoformat(), "all_pass": ok, "checks": checks}, indent=2))
for c in checks:
    print(f"[{'PASS' if c['pass'] else 'FAIL'}] {c['check']}: diff={c['diff']}")
sys.exit(0 if ok else 1)
