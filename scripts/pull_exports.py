"""Download gold Parquet exports from the Databricks volume and verify them against the export manifest.

Usage: uv run python scripts/pull_exports.py [table ...]   (default: drive_lifetimes model_period_stats model_age_stats;
       early-warning sets: ew_train ew_test, verified against ew_manifest.json)
Writes data/exports/<table>/*.parquet and fails if row counts or sums differ from _manifest.json.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.compute as pc

ROOT = Path(__file__).resolve().parents[1]
PROFILE = os.environ.get("DATABRICKS_PROFILE", "kianhekmatnejad")
VOL = "dbfs:/Volumes/backblaze/gold/exports"
tables = sys.argv[1:] or ["drive_lifetimes", "model_period_stats", "model_age_stats"]
out = ROOT / "data/exports"
out.mkdir(parents=True, exist_ok=True)


def cp(src, dst, recursive=False):
    subprocess.run(["databricks", "-p", PROFILE, "fs", "cp", *(["-r"] if recursive else []), src, str(dst), "--overwrite"],
                   check=True, capture_output=True)


manifest = {}
if any(not t.startswith("ew_") for t in tables):
    cp(f"{VOL}/_manifest.json", out / "_manifest.json")
    manifest.update(json.loads((out / "_manifest.json").read_text()))
if any(t.startswith("ew_") for t in tables):  # early-warning sets (notebook 41): verify row counts
    cp(f"{VOL}/ew_manifest.json", out / "ew_manifest.json")
    ew = json.loads((out / "ew_manifest.json").read_text())
    manifest.update({t: {"rows": ew[t]["rows"]} for t in ("ew_train", "ew_test")})
ok = True
for t in tables:
    shutil.rmtree(out / t, ignore_errors=True)
    cp(f"{VOL}/{t}", out / t, recursive=True)
    tbl = ds.dataset(out / t, format="parquet").to_table()
    got = {"rows": tbl.num_rows}
    for col, key in [("drive_days", "sum_drive_days"), ("failures", "sum_failures"),
                     ("failed", "sum_failed"), ("n_obs_days", "sum_n_obs_days")]:
        if col in tbl.column_names:
            got[key] = int(pc.sum(tbl[col]).as_py())
    exp = manifest[t]
    match = all(got.get(k) == v for k, v in exp.items())
    ok &= match
    print(f"[{'OK' if match else 'MISMATCH'}] {t}: local={got} manifest={exp}")
sys.exit(0 if ok else 1)
