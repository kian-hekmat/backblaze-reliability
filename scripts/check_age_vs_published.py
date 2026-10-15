"""Independent check from the RAW files (no pipeline involved): compare mean drive age per model (corrected SMART 9 at each drive's last observation in the quarter)
with Backblaze's published average age. Writes results/validation/age_check_<quarter>.csv.

Counterpart: scripts/check_age_vs_published_db.py runs the same check on the pipeline's silver table for any quarter.
Usage: uv run python scripts/check_age_vs_published.py data/work/Q2_2026_raw.parquet Q2_2026
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reliability.age import corrected_poh_sql  # noqa: E402
from reliability.normalize import normalize_model  # noqa: E402

path, quarter = sys.argv[1], sys.argv[2]
con = duckdb.connect()
last = con.execute(f"""
    SELECT model, max_by(smart_9_raw::BIGINT, date) poh, max_by(smart_240_raw::BIGINT, date) hfh
    FROM read_parquet('{path}') GROUP BY serial_number, model""").df()
last["model_short"] = last["model"].map(lambda m: normalize_model(m)[1])
last["model_norm"] = last["model"].map(lambda m: normalize_model(m)[0])
con.register("last", last)
ages = con.execute(f"""SELECT model_short, count(*) n,
      avg(poh) / 24 / 30.4375 AS raw_age_months,
      avg({corrected_poh_sql('model_short', 'poh', 'hfh')}) / 24 / 30.4375 AS corrected_age_months
    FROM last GROUP BY 1""").df()
pub = pd.read_csv(ROOT / f"results/validation/backblaze_published_{quarter.lower()}.csv")
m = pub.merge(ages, on="model_short", how="left")
m["diff_raw"] = m["raw_age_months"] - m["avg_age_months"]
m["diff_corrected"] = m["corrected_age_months"] - m["avg_age_months"]
m.round(2).to_csv(ROOT / f"results/validation/age_check_{quarter}.csv", index=False)
print(m[["model_short", "avg_age_months", "raw_age_months", "corrected_age_months", "diff_raw", "diff_corrected"]].round(1).to_string(index=False))
