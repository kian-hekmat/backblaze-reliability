"""Age check on the PIPELINE's silver table (any quarter; counterpart of check_age_vs_published.py, which reads raw files): mean corrected SMART 9 age at each drive's last day in a quarter vs Backblaze's
published average age. Writes results/validation/age_check_<quarter>.csv.
Usage: uv run python scripts/check_age_vs_published_db.py Q1_2026
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from dbsql import run  # noqa: E402
from reliability.age import corrected_poh_sql  # noqa: E402

q = sys.argv[1]
cols, rows = run(f"""
  SELECT model_short, count(*) n, avg(poh_c) / 24 / 30.4375 AS corrected_age_months, avg(poh) / 24 / 30.4375 AS raw_age_months
  FROM (SELECT model_short, max_by({corrected_poh_sql('model_short', 'smart_9_raw', 'smart_240_raw')}, date) poh_c,
               max_by(smart_9_raw, date) poh
        FROM backblaze.silver.drive_stats WHERE quarter = '{q}' AND is_data_drive GROUP BY serial_number, model_short)
  GROUP BY model_short""")
ages = pd.DataFrame(rows, columns=cols).astype({"n": int, "corrected_age_months": float, "raw_age_months": float})
pub = pd.read_csv(ROOT / f"results/validation/backblaze_published_{q.lower()}.csv")
m = pub.merge(ages, on="model_short", how="left")
m["diff_raw"] = m["raw_age_months"] - m["avg_age_months"]
m["diff_corrected"] = m["corrected_age_months"] - m["avg_age_months"]
m.round(2).to_csv(ROOT / f"results/validation/age_check_{q}.csv", index=False)
print(m[["model_short", "avg_age_months", "raw_age_months", "corrected_age_months", "diff_corrected"]].round(1).to_string(index=False))
print("within 1.5 months:", int((m["diff_corrected"].abs() <= 1.5).sum()), "of", len(m))
