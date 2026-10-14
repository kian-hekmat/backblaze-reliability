#!/usr/bin/env bash
# Backfill all 12 quarters through the Databricks pipeline, resumably.
#   1. bronze + silver per quarter, oldest first (skips stages already complete in ops.quarter_status)
#   2. drive_lifetimes + model stats once over all silver
#   3. features per quarter, oldest first ("ever" flags carry forward from the previous quarter). A quarter's
#      features are rebuilt if missing or older than the previous quarter's (e.g. Q2_2026, first built alone)
#   4. Parquet export
# Stops at the first failed run (e.g. Free Edition daily quota); re-run the script to resume.
# Usage: bash scripts/run_full_scope.sh 2>&1 | tee -a data/full_scope.log
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUARTERS=(Q3_2023 Q4_2023 Q1_2024 Q2_2024 Q3_2024 Q4_2024 Q1_2025 Q2_2025 Q3_2025 Q4_2025 Q1_2026 Q2_2026)

done_stage() {  # $1 stage, $2 quarter -> exit 0 if complete
  uv run --project "$ROOT" python "$ROOT/scripts/dbsql.py" \
    "SELECT 1 FROM backblaze.ops.quarter_status WHERE stage='$1' AND quarter='$2' AND status='complete'" | grep -q 1
}
run() {  # $1 notebook, $2 params json
  echo "$(date '+%F %T') START $1 ${2:-}"
  out=$(bash "$ROOT/databricks/run_notebook.sh" "$1" "${2:-}" 2>&1 | grep -v aitools)
  echo "$out" | sed 's/^/    /'
  if ! echo "$out" | grep -q "^SUCCESS"; then echo "$(date '+%F %T') FAILED $1 ${2:-} -- stopping"; exit 1; fi
  echo "$(date '+%F %T') DONE  $1 ${2:-}"
}

for q in "${QUARTERS[@]}"; do
  done_stage bronze "$q" || run 10_ingest_bronze "{\"quarter\":\"$q\"}"
  done_stage silver "$q" || run 20_bronze_to_silver "{\"quarter\":\"$q\"}"
done
# lifetimes/model stats: rebuild once if their window does not cover all silver
cover=$(uv run --project "$ROOT" python "$ROOT/scripts/dbsql.py" \
  "SELECT (SELECT max(window_end) FROM backblaze.gold.drive_lifetimes) = (SELECT max(date) FROM backblaze.silver.drive_stats)
          AND (SELECT min(window_start) FROM backblaze.gold.drive_lifetimes) = (SELECT min(date) FROM backblaze.silver.drive_stats) AS ok")
echo "$cover" | grep -q '"ok": "true"' || { run 30_gold_drive_lifetimes; run 31_gold_model_stats; }
features_stale() {  # $1 quarter, $2 previous quarter -> exit 0 if features must be (re)built
  done_stage features "$1" || return 0
  [ -z "$2" ] && return 1
  uv run --project "$ROOT" python "$ROOT/scripts/dbsql.py" \
    "SELECT (SELECT max(completed_at) FROM backblaze.ops.quarter_status WHERE stage='features' AND quarter='$1')
          < (SELECT max(completed_at) FROM backblaze.ops.quarter_status WHERE stage='features' AND quarter='$2') AS stale" \
    | grep -q '"stale": "true"'
}
prev=""
for q in "${QUARTERS[@]}"; do
  features_stale "$q" "$prev" && run 32_gold_features "{\"quarter\":\"$q\"}"
  prev="$q"
done
run 40_export_gold
echo "$(date '+%F %T') FULL SCOPE COMPLETE"
