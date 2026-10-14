# Limitations

Each item states what is limited, its likely effect, and the evidence. Numbers trace to `results/`.

## Data scope

- **Window:** 12 quarters, 2023-07-01 to 2026-06-30 (`results/scale.json`). This is the full planned scope, not a
  quota-forced subset. Failures before the window are not observed; drive history before it is seen only through
  SMART counters such as power-on hours.
- **One fleet, one environment:** Backblaze runs consumer- and enterprise-class drives in its own storage pods and
  data centers, with its own workloads, temperatures, vibration, and replacement practices. The rates here describe
  drives *in Backblaze's environment* and do not transfer directly to other fleets or other kinds of hardware. The
  methods transfer; the numbers do not.
- **Data drives only:** drives below 4 TB (boot drives and SSDs) are excluded, as in Backblaze's reports. Backblaze's
  boot-drive list is internal; the 4 TB cutoff gives 3,959 non-data drives in Q2 2026 vs Backblaze's 3,881 boot
  drives. Per-model figures are unaffected (every published model is ≥ 4 TB).

## Failure definition

- A "failure" is a drive Backblaze removed and confirmed failed. This is an operational definition, not a physical
  root cause.
- **Daily flags vs. Backblaze's curated tables:** Q1 2026 matches exactly. In Q2 2026 the daily files contain 18 more
  failures (+1.2%) than the published table, probably due to Backblaze's quarter-end manual reclassification
  (`results/validation/afr_validation_summary.json`). AFRs from the daily files can run slightly above Backblaze's
  curated figures.
- **Episodic, non-mechanical failures:** MG08ACA16TEY recorded 209 failures in Q3 2025, attributed by Backblaze to
  drives pulled for firmware updates. They are kept, because the public data can't separate them per drive. The
  Bayesian model's quarter-drift term absorbs most of the spike; a sensitivity run without that quarter moves other
  models' estimates by at most 0.13 points (`results/phase4/sensitivity_mg08aca16tey.json`).
- **File-production change:** drives reappearing after a failure flag occur 10–47 times per quarter through Q4 2024 and
  never from Q1 2025 on. Only a failure on the drive's final row counts (Backblaze's "failed until it shows up again"),
  so both regimes are handled the same way, but the raw files are not perfectly uniform across the window.

## Drive age

- Age comes from SMART 9 (power-on hours). Wraparound at 78,188 h on four old Seagate models is corrected using SMART 240
  (head flying hours), which doesn't wrap. Mean age per model is within 1.5 months of Backblaze's published average for
  30/31 models (Q2 2026) and 31/33 (Q1 2026). MG08ACA16TA is consistently +3.1 months
  (`results/validation/age_check_*.csv`).
- Power-on hours count powered time, not time since deployment. Ages run slightly above Backblaze's (typically +0.2 to
  +1.4 months), consistent with Backblaze measuring from deployment.
- 68 data drives (0.02%) have no usable SMART 9 and are excluded from age-based analyses (`ops.quarter_status`,
  gold_lifetimes).
- **Age vs. drive generation:** a single age curve learned across models can't be separated from design generation
  (older models are also older designs). The Bayesian model therefore has no shared age effect. Age effects are
  estimated within each model (Kaplan-Meier, Weibull) and no "age-adjusted" cross-model comparison is reported
  (DECISIONS 2026-10-14).
- **Survival curves are conditional:** with delayed entry, each Kaplan-Meier curve starts at the first age with at
  least 100 drives at risk and shows survival conditional on reaching it.
- **Weibull** is a single-shape model. It can't represent a full bathtub curve (early-life and wear-out in the same
  model) and summarizes the dominant hazard trend over the ages each model was observed in the window.

## Failure-rate estimates and forecasts

- **Rates are not stationary.** Quarterly counts vary ~2.9× more than Poisson (median dispersion index; up to 24× for
  HGST 12 TB models). The posterior AFR describes a model's average rate over the window, not a fixed property of
  the model.
- **Out-of-time coverage is 79.5%, not 90%** (fit on two years, predict the third; 44 models). Misses track hazard
  shape: wear-out models fail more than their trailing rate predicts, early-life models fewer (Spearman ρ = 0.63).
  This explanation uses Weibull fits over the full window, including the test year, so it is not a validated
  forecasting method. Next-year forecasts for wear-out models should be treated as low estimates
  (`results/phase4/out_of_time_summary.json`, `oot_vs_hazard.json`).
- Priors matter most for the smallest models (a few thousand drive-days): their posteriors are pulled toward the
  manufacturer mean, which reflects the assumption that models from one manufacturer are similar.

## SMART telemetry and early warning

- **SMART fields vary by manufacturer.** SMART 187/188 are reported almost only by Seagate (Q2 2026 coverage: Seagate
  98%, others ≤ 0.4%). The simple rule's false-alarm rate ranges from 28 per 1,000 drive-days (WDC) to 145 (Seagate);
  results are reported per manufacturer (`results/phase5/metrics_by_manufacturer_30d.csv`).
- **Sudden failures:** 346 of 1,459 failed test drives (23.7%) never showed a critical SMART signal (5/187/188/197/198).
  LightGBM still alerted on 165 of them through other features; the other 181 make up almost all (181 of 183) of the
  failures it never alerts on, at the rule's budget. Toshiba is worst: 36% of its failed test drives had no critical
  signal (`results/phase5/undetected_30d.json`, `lead_times_30d.csv`).
- **Test window:** the test period is one year (Q3 2025 – Q2 2026), so lead times longer than the test window are
  truncated, and failures in the last 30 days of the window have unknown 30-day labels and are excluded.
- **Sampling:** training keeps all positive rows and 2% of negative rows. Scores are used only for ranking and
  thresholds set on the natural test distribution, so the sampling doesn't bias the reported metrics, but the
  model's raw probabilities are not calibrated.
- **One split:** results come from a single drive-hash + time split. No repeated splits or confidence intervals on
  PR-AUC were computed.

## Platform constraints

- Databricks Free Edition has a daily compute quota. Pipeline jobs process one quarter per run and resume from
  `backblaze.ops.quarter_status`. The full backfill completed without hitting the quota.
- Bayesian and early-warning models run locally on exported gold data; their outputs are loaded back into Databricks
  as `gold.res_*` tables.
- Tableau Public can't connect to Databricks; the dashboard uses aggregate CSV extracts in `tableau/`.
