#!/usr/bin/env bash
# Pull gold Parquet exports from the Databricks volume, stage them in Snowflake, load, and validate.
# Usage: bash snowflake/load_gold.sh [table ...]   (default: drive_lifetimes model_period_stats model_age_stats)
# Uses the default Snowflake CLI connection and $DATABRICKS_PROFILE (default kianhekmatnejad). No secrets in repo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${DATABRICKS_PROFILE:-kianhekmatnejad}"
[ $# -eq 0 ] && set -- drive_lifetimes model_period_stats model_age_stats
TABLES=("$@")
EXP="$ROOT/data/exports"
rm -rf "$EXP" && mkdir -p "$EXP"

databricks -p "$PROFILE" fs cp dbfs:/Volumes/backblaze/gold/exports/_manifest.json "$EXP/_manifest.json" >/dev/null
for t in "${TABLES[@]}"; do
  databricks -p "$PROFILE" fs cp -r "dbfs:/Volumes/backblaze/gold/exports/$t" "$EXP/$t" >/dev/null
done

snow sql -f "$ROOT/snowflake/10_tables.sql" >/dev/null
snow sql -q "USE ROLE LOADER; USE SECONDARY ROLES NONE; CREATE STAGE IF NOT EXISTS BACKBLAZE.GOLD.EXPORTS_STAGE FILE_FORMAT = (TYPE = PARQUET);" >/dev/null
for t in "${TABLES[@]}"; do
  snow sql -q "USE ROLE LOADER; USE SECONDARY ROLES NONE; REMOVE @BACKBLAZE.GOLD.EXPORTS_STAGE/$t/;" >/dev/null
  snow stage copy "$EXP/$t" "@BACKBLAZE.GOLD.EXPORTS_STAGE/$t/" --recursive --role LOADER >/dev/null
done
# Load (truncate + COPY with MATCH_BY_COLUMN_NAME) via 20_load.sql, then validate against the manifest
snow sql -f "$ROOT/snowflake/20_load.sql"
uv run --project "$ROOT" python "$ROOT/scripts/validate_snowflake.py" "$EXP/_manifest.json" "${TABLES[@]}"
