# Validation references

`backblaze_published_<quarter>.csv` are Backblaze's published quarterly Drive Stats tables, transcribed from:
- Q2 2026: https://www.backblaze.com/blog/backblaze-drive-stats-for-q2-2026/
- Q1 2026: https://www.backblaze.com/blog/backblaze-drive-stats-for-q1-2026/

Transcription check (both tables): per-row drive-days and failures sum exactly to the published totals
(Q2 2026: 31,553,350 / 1,498; Q1 2026: 30,203,180 / 1,030), and every row's AFR recomputes from its
failures and drive-days to within rounding.

Note on Backblaze's own figures: Q1 2026 per-model drive counts sum to 346,596, above the 345,662 drives
reported as monitored at quarter end and the 341,263 "analyzed". The table's drive counts appear to cover
drives seen during the quarter, not at quarter end. For Q2 2026 the table counts sum exactly to the
354,415 analyzed.

`age_check_<quarter>.csv`: mean drive age per model from wraparound-corrected SMART 9 vs Backblaze's
published average age (`scripts/check_age_vs_published.py`).
