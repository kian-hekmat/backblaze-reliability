#!/usr/bin/env bash
# Download the 12 Backblaze Drive Stats quarterly ZIPs (Q3 2023 - Q2 2026, ~14.9 GB) and upload them unchanged
# to the Databricks volume /Volumes/backblaze/bronze/raw/zips/, verifying each upload's size (5 retries).
# Data: https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data (cite Backblaze; do not sell the data).
# Usage: bash scripts/download_data.sh            (profile: $DATABRICKS_PROFILE, default kianhekmatnejad)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${DATABRICKS_PROFILE:-kianhekmatnejad}"
BASE=https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data
DEST=dbfs:/Volumes/backblaze/bronze/raw/zips
QUARTERS=(Q3_2023 Q4_2023 Q1_2024 Q2_2024 Q3_2024 Q4_2024 Q1_2025 Q2_2025 Q3_2025 Q4_2025 Q1_2026 Q2_2026)
mkdir -p "$ROOT/data/raw/zips"
databricks -p "$PROFILE" fs mkdir "$DEST" >/dev/null 2>&1 || true
for q in "${QUARTERS[@]}"; do
  f="$ROOT/data/raw/zips/data_$q.zip"
  curl -sSL --retry 5 -C - -o "$f" "$BASE/data_$q.zip"
  size=$(stat -f %z "$f" 2>/dev/null || stat -c %s "$f")
  for attempt in 1 2 3 4 5; do
    databricks -p "$PROFILE" fs cp "$f" "$DEST/data_$q.zip" --overwrite >/dev/null 2>&1 || true
    remote=$(databricks -p "$PROFILE" fs ls -l "$DEST/" 2>/dev/null | awk -v n="data_$q.zip" '$4==n{print $2}')
    [ "$remote" = "$size" ] && { echo "OK $q ($size bytes)"; break; }
    echo "retry $q ($attempt)"; sleep 20
    [ $attempt -eq 5 ] && { echo "FAILED $q"; exit 1; }
  done
done
