# Results

Every number below comes from a file in `results/`, produced by code in this repo. The file is linked next to
each result. AFR = failures / (drive-days / 365) × 100. All analyses use data drives (≥ 4 TB) unless stated.

## 1. Scale

Source: [`results/scale.json`](../results/scale.json).

| | |
|---|---|
| Date range | 2023-07-01 to 2026-06-30 (12 quarters, Q3 2023 – Q2 2026) |
| Drive-day rows (all drives) | 333,732,420 |
| Drives (all) | 409,830 serial numbers, 97 normalized models |
| Counted failures (all drives) | 13,255 (raw `failure=1` flags: 13,582; the difference is drives that reappeared after a flag) |
| Data drives (≥ 4 TB) | 329,208,251 drive-days, 404,782 drives, 66 models, 13,076 failures |
| Daily feature rows | 329,208,251. Spark features match the reference implementation on 185,641 sampled rows with 0 mismatches |

## 2. Validation against Backblaze's published tables

Source: [`results/validation/afr_validation_summary.json`](../results/validation/afr_validation_summary.json),
per-model detail in `afr_validation_Q1_2026.csv` and `afr_validation_Q2_2026.csv`.

| Quarter | Published models | Drive count exact | Drive-days exact | Failures exact | Failures (Backblaze vs pipeline) |
|---|---|---|---|---|---|
| Q1 2026 | 33 | 33 | 33 | **33** | 1,030 vs 1,030 |
| Q2 2026 | 31 | 31 | 31 | 21 | 1,498 vs 1,516 (+18, +1.2%) |

- Q1 2026 reproduces Backblaze's table exactly.
- The Q2 2026 gap is always in the same direction (the daily files contain more failures) and spread over 10 models.
  - It is not the pipeline: the same code matches Q1 2026 exactly.
  - It is not a later data revision: the Q2 2026 ZIP was uploaded four weeks before the blog post.
  - Probable cause: Backblaze's manual quarter-end reclassification (clone / temporary-replacement tickets), which
    the published daily flags don't reflect.
- **Drive age** (SMART 9, wraparound-corrected): mean age per model is within 1.5 months of Backblaze's published
  average for 30/31 models in Q2 2026 and 31/33 in Q1 2026
  ([`age_check_Q2_2026.csv`](../results/validation/age_check_Q2_2026.csv),
  [`age_check_Q1_2026.csv`](../results/validation/age_check_Q1_2026.csv)).

## 3. Core result: failure rates with honest uncertainty

### 3.1 Bayesian failure rates per model

Source: [`results/phase4/bayes_estimates.csv`](../results/phase4/bayes_estimates.csv). The model is Poisson with partial
pooling by manufacturer and quarter-to-quarter drift per model; there is no shared age curve (see 3.3). Diagnostics:
0 divergences, R-hat 1.012, min ESS 511 ([`bayes_diagnostics.json`](../results/phase4/bayes_diagnostics.json)).
Posterior median AFR (%/yr), 90% credible interval, full window:

| Large models (≥ 1M drive-days), riskiest | Raw AFR | Posterior median [90% CI] | Drive-days |
|---|---|---|---|
| Seagate ST12000NM0007 | 7.46 | **7.15** [5.75, 8.94] | 1,159,758 |
| Seagate ST14000NM0138 | 5.92 | **5.97** [4.79, 7.40] | 1,449,274 |
| Seagate ST10000NM0086 | 5.50 | **5.54** [4.38, 6.93] | 1,135,013 |
| HGST HUH721212ALN604 | 4.46 | **4.34** [3.58, 5.33] | 11,103,473 |

| Large models, most reliable | Raw AFR | Posterior median [90% CI] | Drive-days |
|---|---|---|---|
| HGST HMS5C4040BLE640 | 0.22 | **0.27** [0.18, 0.39] | 5,460,758 |
| WDC WUH721816ALE6L4 | 0.59 | **0.57** [0.47, 0.70] | 27,195,955 |
| Seagate ST16000NM001G | 0.59 | **0.65** [0.53, 0.79] | 35,394,586 |
| WDC WUH722222ALE6L4 | 0.57 | **0.69** [0.55, 0.86] | 26,618,059 |

### 3.2 Where pooling changes the conclusion (the "why Bayesian" result)

Source: [`results/phase4/bayes_vs_raw_disagreement.csv`](../results/phase4/bayes_vs_raw_disagreement.csv).

| Model | Drive-days | Failures | Raw AFR | Posterior median [90% CI] |
|---|---|---|---|---|
| Seagate ST16000NM002H | 2,240 | 1 | 16.29 | 2.87 [0.83, 10.62] |
| WDC WUH722016CLE6L4 | 3,630 | 1 | 10.06 | 1.94 [0.49, 7.42] |
| Seagate ST12000NM0117 | 7,874 | 2 | 9.27 | 3.61 [1.13, 10.40] |
| Seagate ST4000DM004 | 4,243 | 0 | 0.00 | 1.51 [0.36, 5.47] |

- With a few thousand drive-days, one failure swings raw AFR between 0% and over 10%. Ranking models on raw AFR
  would flag ST16000NM002H as the riskiest model in the fleet on the strength of one failure.
- The posterior pulls these models toward their manufacturer's typical rate and widens the interval to show how little
  is known. For large models, posterior and raw AFR agree closely; there the data dominate.
- **Episodic failures:** MG08ACA16TEY's raw window AFR is 3.24%, inflated by Q3 2025 (209 failures, a 16.48% quarterly
  AFR, from drives Backblaze pulled for firmware updates). Without that quarter its raw AFR is 2.04%. The model's
  quarter-drift term absorbs most of the spike without dropping data by hand: posterior 2.44% [1.98, 3.02] with the
  quarter, 1.98% without. Excluding it moves other models' medians by at most 0.13 points
  ([`sensitivity_mg08aca16tey.json`](../results/phase4/sensitivity_mg08aca16tey.json)).

### 3.3 Out-of-time check: how well do past rates predict next year?

Fit on Q3 2023 – Q2 2025, predict failure counts per model for Q3 2025 – Q2 2026 given each model's actual drive-days
([`out_of_time_summary.json`](../results/phase4/out_of_time_summary.json)):

| Model variant | 90% interval coverage (44 models) | Below / above | Large models: predicted vs actual |
|---|---|---|---|
| Poisson + shared age curve (original spec) | 54.5% | 14 / 6 | 4,991 vs 4,388 |
| + quarter drift, shared age curve | 61.4% | 11 / 6 | 5,357 vs 4,388 |
| **+ quarter drift, no shared age curve (main)** | **79.5%** | 3 / 6 | 4,099 vs 4,388 |

- **Overdispersion:** within the training years, quarterly failure counts vary 2.9× more than Poisson allows
  (median dispersion index across 20 large models;
  [`overdispersion_train_quarters.csv`](../results/phase4/overdispersion_train_quarters.csv)). A model's failure rate
  is not a fixed number.
- **Age confound:** a single age curve learned across models (older models are also older designs) predicted
  wear-out that did not happen within models ([`oot_age_diagnostic.json`](../results/phase4/oot_age_diagnostic.json)).
- **Remaining misses track hazard shape:** across 24 models, forecast error correlates with each model's Weibull
  shape (Spearman ρ = 0.63, p = 0.001). Under-predicted models have median shape k = 1.72 (wear-out); over-predicted
  models have k = 0.65 (early-life failures declining). The Weibull fits use the full window, so this explains the
  misses rather than forecasting them ([`oot_vs_hazard.json`](../results/phase4/oot_vs_hazard.json)).
- The main model still under-covers (80%, not 90%). Its intervals describe the window's rates well, but next-year
  forecasts for models in a changing-hazard phase need the hazard shape taken into account.

### 3.4 Hazard shape: early-life vs. wear-out

Weibull with right-censoring and delayed entry (age from power-on hours), for the 26 models with ≥ 30 failures
([`weibull_by_model.csv`](../results/phase4/weibull_by_model.csv)): **11 increasing (wear-out), 11 constant,
4 decreasing (early-life)**, classified by whether the 95% CI for shape k lies above 1, includes 1, or lies below 1.

- Strongest wear-out: WDC WUH721816ALE6L0 (k = 3.21), Toshiba MG07ACA14TA (2.67), Toshiba MG08ACA16TEY (2.44),
  Seagate ST10000NM0086 (2.02).
- Early-life phase: WDC WUH722222ALE6L4 (k = 0.62, observed to 3.4 years of age), WDC WUH721414ALE6L4 (0.59),
  Toshiba MG07ACA14TEY (0.66), Seagate ST16000NM001G (0.88).
- Kaplan-Meier curves by model and manufacturer, with a ≥ 100-drives-at-risk start:
  [`km_by_model.csv`](../results/phase4/km_by_model.csv), [`km_by_manufacturer.csv`](../results/phase4/km_by_manufacturer.csv).

### 3.5 Model checks

- Synthetic fleets with known rates and true quarter drift (40 simulations, 1,040 intervals): 90% intervals cover
  89.1% ([`bayes_synthetic_coverage.json`](../results/phase4/bayes_synthetic_coverage.json)). These short single-chain
  runs had divergences in 11 of 40 fits and max R-hat 1.12. The real-data fit uses 4 chains × 1,000 draws after
  3,000 warmup and had none.

## 4. Second result: early warning

*Pending: Phase 5 is running.*

## 5. Reliability decisions

*Written after Phase 5.*
