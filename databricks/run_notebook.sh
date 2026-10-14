#!/usr/bin/env bash
# Sync databricks/ notebooks to the workspace and run one as a serverless one-time job.
# Usage: bash databricks/run_notebook.sh <notebook_name_without_.py> [json_params]
#   e.g. bash databricks/run_notebook.sh 10_ingest_bronze '{"quarter":"Q2_2026"}'
# Profile is taken from $DATABRICKS_PROFILE (default: kianhekmatnejad). No credentials live in this repo.
set -euo pipefail
PROFILE="${DATABRICKS_PROFILE:-kianhekmatnejad}"
NB="$1"; PARAMS="${2:-}"; [ -z "$PARAMS" ] && PARAMS='{}'
ME=$(databricks -p "$PROFILE" current-user me --output json | python3 -c 'import json,sys; print(json.load(sys.stdin)["userName"])')
DEST="/Users/$ME/backblaze-reliability/databricks"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
databricks -p "$PROFILE" workspace import-dir "$ROOT/databricks" "$DEST" --overwrite >/dev/null
# src/reliability is pure Python shared with notebooks; sync it as workspace files
databricks -p "$PROFILE" workspace import-dir "$ROOT/src" "/Users/$ME/backblaze-reliability/src" --overwrite >/dev/null
SUBMIT=$(mktemp)
cat > "$SUBMIT" <<JSON
{"run_name": "bb-$NB", "tasks": [{"task_key": "main",
  "notebook_task": {"notebook_path": "$DEST/$NB", "base_parameters": $PARAMS}}]}
JSON
databricks -p "$PROFILE" jobs submit --json @"$SUBMIT" --timeout 120m --output json \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); s=r["state"]; print(r.get("run_page_url","")); print(s.get("result_state"), "-", s.get("state_message",""))'
rm -f "$SUBMIT"
