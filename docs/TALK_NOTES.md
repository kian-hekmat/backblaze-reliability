# Talk notes: Drive fleet reliability (10–15 minutes)

Structure: problem → approach → results, then what went wrong, then the connection to reliability engineering.
Every number cites the file it came from. This is a public-data project on hard drives; it claims no medical-device
or surgical-robotics experience.

---

## 1. Problem (~2 min)

- A fleet of the same kind of hardware, ~400k hard drives across 66 models, fails at very different rates by model.
  The decisions are which models to trust, when to replace, and how many spares to stock.
- **Averages aren't enough.** Some models have millions of drive-days and some a few thousand. A raw failure rate from
  one failure in 2,240 drive-days reads as 16%. Decisions need confidence, not just a point estimate.
- **Early warning is only useful if its false-alarm cost is acceptable.** Telemetry (SMART) can flag drives, but every
  alert costs a technician's time and a drive swap.
- Data: Backblaze's public Drive Stats, 2023-07-01 to 2026-06-30: 333,732,420 drive-days, 409,830 drives, 13,255
  failures (`results/scale.json`).

## 2. Approach (~4 min)

- **Pipeline: Databricks, bronze → silver → gold, one quarter per run.**
  - Bronze keeps the files exactly as published, so the pipeline can always be audited back to source.
  - Silver applies documented cleaning rules: types, dedup, model-name normalization, capacity fixes.
  - Gold builds three analysis shapes: one row per drive for survival, per model × quarter for failure rates, per
    drive-day for early warning.
  - Every run checks that rows are conserved and keys are unique, and fails loudly otherwise. Jobs are idempotent and
    resumable because Free Edition has a daily compute quota.
- **Validated against the source of truth.** The pipeline reproduces Backblaze's published Q1 2026 table exactly on all
  33 models: drive counts, drive-days and failures (`results/validation/afr_validation_summary.json`).
- **Survival with right-censoring and left truncation.** Drives that are still running, or left without failing, are
  censored, not counted as survivors. Most drives were already years old when the window opened, so survival by age
  uses delayed entry from power-on hours. Ignoring that biases survival upward (a unit test shows this).
- **Bayesian pooling for sparse models (NumPyro).** Each model's failure rate is drawn from its manufacturer's
  distribution, so a model with a few thousand drive-days borrows strength from similar models; large models are
  dominated by their own data. A quarter-to-quarter drift term was added after the data showed rates aren't fixed
  (see §4).
- **Early warning, split by drive and by time.** A drive is in train or test, never both, and the test year comes after
  the training years. This mimics deploying a model on drives it has never seen, at a later time. Evaluated on the
  full, natural, ~0.1%-positive test distribution, not a balanced sample.
- **The simple rule is the baseline:** "alert when any critical SMART counter is nonzero" is what a team would do
  without a model. The model only matters if it beats that.

## 3. Results (~4 min)

1. **Some models are 8–13× riskier, and Bayesian intervals say how sure we are.** Seagate ST12000NM0007 at 7.15%/yr
   [5.75, 8.94] vs the most reliable high-volume models at 0.57–0.69%
   (`results/phase4/bayes_estimates.csv`). For a one-failure, 2,240-drive-day model, raw AFR is 16.3%; the posterior is
   2.9% [0.8, 10.6], so the honest answer is "we don't know yet" (`bayes_vs_raw_disagreement.csv`).
2. **Past failure rates under-forecast wear-out models.** Fitting two years and predicting the third, 90% intervals
   covered 79.5% of models (`out_of_time_summary.json`). The misses track hazard shape: wear-out models (Weibull k > 1)
   fail more than their trailing rate, and early-life models fewer (Spearman ρ = 0.63, p = 0.001;
   `oot_vs_hazard.json`). Decision: budget spares above trailing AFR for wear-out models.
3. **A model at a chosen alert budget beats the "any SMART error" rule on false-alarm cost.** The rule flags ~10% of
   healthy drives per year. LightGBM at 5 alerts per 1,000 drive-days alerts 64.6% of failing drives at least a week
   ahead (median 68 days) while flagging ~2.5% of healthy drives per year
   (`results/phase5/metrics_30d.csv`). PR-AUC: 0.123 vs 0.0067. 181 of the 183 failures the model never alerts on
   (at the rule's budget) showed no critical SMART signal at all, so they need redundancy, not prediction
   (`undetected_30d.json`).

## 4. What went wrong and what I learned (~2 min)

- **The power-on-hours counter wraps.** I checked my age calculation against Backblaze's published average age per
  model. ST8000DM002 came out at 12 months instead of 115. On four old Seagate models SMART 9 wraps at 78,188 hours
  (~8.9 years). My first fix, "below 30,000 h means wrapped", broke on young replacement drives of the same models.
  The real fix came from another counter, SMART 240 (head flying hours), which doesn't wrap. After that, ages matched
  Backblaze's within 1.5 months for 30/31 and 31/33 models (`results/validation/age_check_*.csv`). Lesson: validate
  derived fields against an independent source, and when a fix works on one quarter, rerun the check on all of them.
- **My first Bayesian model failed its own out-of-time test, and the fix was to remove a component.** The approved
  design had a shared age curve; out-of-time coverage was 55%. Two diagnoses:
  - Quarterly counts were ~3× overdispersed, so I added a drift term (61%).
  - The age curve, learned across models, was confounded with drive generation and predicted wear-out that didn't
    happen within models. Removing it raised coverage to 80% (`oot_age_diagnostic.json`).
  Lesson: an out-of-time check is the test that matters, and when it fails, diagnose before adding parameters.
- Smaller ones: a capacity of −1 on drives' first day silently dropped 480 drives from analysis; lifelines' Weibull
  fitter diverged on new fleets; the original failure-count definition disagreed between two tables. Each was caught
  by a check that compared two independent computations.

## 5. Connection to reliability engineering (~1 min)

Methods that transfer to any hardware reliability team (stated as methods, not domain experience):
- **Right-censoring and left truncation:** units still in service, or retired without failing, carry information;
  units observed only after deployment need delayed entry.
- **Early-life vs. wear-out:** per-population hazard shape (Weibull) separates infant mortality from wear-out and
  explains when a trailing failure rate will mislead a forecast.
- **Failure prediction from telemetry:** judged at an operating point (alerts the team can absorb) on the natural
  failure rate, with honest reporting of what can't be predicted.
- **Bayesian estimation with sparse data:** partial pooling gives usable, honestly uncertain estimates for low-volume
  populations instead of 0% or 16%.

---

## Likely questions, with honest answers

1. **"Why did you use Databricks? Did you need a separate warehouse like Snowflake?"**
   - Databricks: ~140 GB of CSVs, 333M rows, arriving quarterly. That is where incremental, idempotent processing in
     bronze/silver/gold layers pays off.
   - I originally planned Snowflake as a separate serving layer and built the setup and role scripts. I dropped it:
     at this data size it added a full copy of the data and a reconciliation loop without serving any need Databricks
     SQL couldn't, and the trial would have expired. A separate warehouse makes sense when many BI consumers or teams
     need isolation; this project didn't have that.
2. **"How do you know the pipeline is right?"**
   - Exact match with Backblaze's published Q1 2026 table (all 33 models, including failures).
   - Row conservation at every layer; 21/21 query spot-checks against pandas; Spark features match a reference
     implementation on 185,641 sampled rows; ages match Backblaze's published averages.
   - Q2 2026 differs by 18 failures (+1.2%). I traced it to Backblaze's manual reclassification, not the pipeline,
     and documented it rather than tuning it away.
3. **"Isn't a PR-AUC of 0.12 low?"** The base rate is 0.109%, so 0.12 is ~110× random. More importantly, the useful
   comparison is at an operating point: at 5 alerts per 1,000 drive-days it gives two-thirds of failing drives a week
   of warning at a quarter of the rule's false-alarm cost. About a quarter of failing drives show no SMART signal at
   all, which caps any SMART-based model.
4. **"Why Bayesian instead of just a confidence interval on AFR?"** A per-model Poisson interval treats each model in
   isolation. A one-failure model gets an interval from ~0 to ~90%, and a zero-failure model a point estimate of 0.
   Pooling uses what similar models say, which matters exactly where decisions are hardest: new or low-volume models.
   For large models the two agree, which is a useful check.
5. **"What would you do differently with more time or budget?"**
   - Model hazard shape per model inside the Bayesian model (a random age slope per model), so forecasts account for
     wear-out instead of only explaining it afterwards.
   - Repeated drive splits to put intervals on the early-warning metrics.
   - A longer history (more years), so the age range per model covers early life through wear-out.
   - Join operational context (data center, pod, temperature) to separate environment from drive design.
