# Limitations

Updated as the project progresses. Each item states what is limited, its likely effect, and the evidence.

## Data scope

- **Window:** 12 quarters, 2023-07-01 to 2026-06-30. Drive behaviour before the window is seen only through
  SMART counters (e.g. power-on hours); failures before the window are not observed.
- **One fleet, one environment:** Backblaze runs drives in its own storage pods and data centers, with its
  own workloads, temperatures and replacement practices. Failure rates here describe drives *in Backblaze's
  environment* and do not transfer directly to other fleets or to other kinds of hardware.
- **Failure definition is operational:** a "failure" is a drive removed and confirmed failed by Backblaze's
  processes. Backblaze documents rare "cosmetic" failures, e.g. MG08ACA16TEY drives pulled for firmware
  updates in Q3 2025. Raw failure counts per model in the daily files can differ slightly from Backblaze's
  published tables (seen in Q2 2026; investigated in Phase 4 validation).

## Data-drive / boot-drive split

- Backblaze's boot-drive list is internal. Drives below 4 TB are treated as boot drives or SSDs: 3,959 drives
  in Q2 2026, vs. 3,881 boot drives in Backblaze's report. Per-model figures are unaffected, because every
  model in Backblaze's quarterly table is ≥ 4 TB.

## Drive age

- Age comes from SMART 9 (power-on hours), corrected for a wraparound at 78,188 h on ST8000NM0055 and
  ST8000DM002 (DECISIONS, 2026-10-14). After correction, mean age per model is within 1.5 months of
  Backblaze's published average for 30 of 31 models in Q2 2026. MG08ACA16TA is +3.1 months
  (`results/validation/age_check_Q2_2026.csv`).
- Power-on hours count powered time, not calendar time since installation. Drives powered off for long
  periods look younger than their deployment age.
- Drives with missing or implausible SMART 9 have unknown age and are excluded from age-based analyses.

## SMART telemetry

- SMART attributes and raw encodings vary by manufacturer. SMART 187/188 are reported almost only by Seagate
  drives (Q2 2026 coverage: Seagate 98%, others ≤ 0.4%), so the simple "critical attribute nonzero" rule
  watches fewer signals on Toshiba, WDC and HGST drives. Early-warning results are reported per manufacturer
  for this reason.

## Platform constraints

- Snowflake was a trial account ending 2026-10-27. Tableau extracts are exported to `tableau/` before then, so
  the dashboard does not depend on the trial.
- Daily per-drive features (~355k drives/day) are kept in Databricks. Snowflake receives a reduced extract
  (DECISIONS, approved change 6).
