"""Compare Snowflake reconciliation metrics (snowflake/30_validate.sql) with the Databricks export manifest.

Writes results/snowflake_validation.json and exits non-zero on any mismatch.
Usage: uv run python scripts/validate_snowflake.py data/exports/_manifest.json drive_lifetimes model_period_stats ...
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads(Path(sys.argv[1]).read_text())
tables = sys.argv[2:]

raw = subprocess.run(["snow", "sql", "-f", str(ROOT / "snowflake/30_validate.sql"), "--format", "json"],
                     check=True, capture_output=True, text=True).stdout
results = json.loads(raw)
rows = next(r for r in reversed(results) if r and "METRIC" in r[0])
sf = {(r["TABLE_NAME"], r["METRIC"]): int(r["VALUE"]) for r in rows}

checks, ok = [], True
for t in tables:
    for metric, expected in manifest[t].items():
        got = sf.get((t, metric))
        match = got == expected
        ok &= match
        checks.append({"table": t, "metric": metric, "databricks": expected, "snowflake": got, "match": match})
for (t, metric), v in sf.items():
    if t == "cross_check" or metric == "duplicate_serials":
        match = v == 0
        ok &= match
        checks.append({"table": t, "metric": metric, "databricks": 0, "snowflake": v, "match": match})

out = {"validated_at": datetime.now(timezone.utc).isoformat(), "all_match": ok, "checks": checks}
(ROOT / "results").mkdir(exist_ok=True)
(ROOT / "results/snowflake_validation.json").write_text(json.dumps(out, indent=2))
for c in checks:
    print(f"[{'OK' if c['match'] else 'MISMATCH'}] {c['table']}.{c['metric']}: databricks={c['databricks']} snowflake={c['snowflake']}")
sys.exit(0 if ok else 1)
