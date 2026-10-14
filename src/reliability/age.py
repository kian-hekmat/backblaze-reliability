"""Drive age from SMART 9 (power-on hours), with counter wraparound corrected.

Observed (DECISIONS: SMART 9 wraparound): on old Seagate models the SMART 9 raw value drops from 78,187 to ~0,
i.e. it wraps modulo 78,188 hours (~8.9 years): ST8000NM0055, ST8000DM002 (found in Q2 2026), ST6000DX000,
ST4000DM000 (found by the pipeline guard in 2023-2024 data).

Deciding whether a reading has wrapped:
- Primary: SMART 240 (head flying hours) does not wrap on these drives. On wrapped drives it exceeds SMART 9 by
  ~78,100 h; on unwrapped drives the two agree within tens of hours. A reading is wrapped if
  SMART 240 - SMART 9 > WRAP_MODULUS_HOURS / 2.
- Fallback when SMART 240 is missing, for known wrapping models only: a reading below WRAP_AMBIGUITY_HOURS is
  taken as wrapped. A fixed threshold alone was wrong for young replacement drives of these models (DECISIONS),
  which is why it is only a fallback.
"""

WRAP_MODULUS_HOURS = 78_188
WRAP_AMBIGUITY_HOURS = 30_000
WRAP_MODELS = frozenset({"ST8000NM0055", "ST8000DM002", "ST6000DX000", "ST4000DM000"})
# Signature used by the pipeline to detect wraparound in models not listed above (fails loudly):
WRAP_DETECT_BEFORE_MIN = 70_000
WRAP_DETECT_AFTER_MAX = 1_000


def corrected_poh(model: str, poh: float | None, head_flying_hours: float | None = None) -> float | None:
    """Power-on hours with wraparound corrected."""
    if poh is None or poh < 0:
        return None
    if head_flying_hours is not None and head_flying_hours >= 0:
        wrapped = head_flying_hours - poh > WRAP_MODULUS_HOURS / 2
    else:
        wrapped = model in WRAP_MODELS and poh < WRAP_AMBIGUITY_HOURS
    return poh + WRAP_MODULUS_HOURS if wrapped else poh


def corrected_poh_sql(model_col: str = "model_short", poh_col: str = "smart_9_raw", hfh_col: str = "smart_240_raw") -> str:
    """Same rule as a SQL expression (Spark SQL / DuckDB compatible)."""
    models = ", ".join(f"'{m}'" for m in sorted(WRAP_MODELS))
    return (f"CASE WHEN {poh_col} IS NULL OR {poh_col} < 0 THEN NULL "
            f"WHEN {hfh_col} IS NOT NULL AND {hfh_col} >= 0 THEN "
            f"CASE WHEN {hfh_col} - {poh_col} > {WRAP_MODULUS_HOURS // 2} THEN {poh_col} + {WRAP_MODULUS_HOURS} ELSE {poh_col} END "
            f"WHEN {model_col} IN ({models}) AND {poh_col} < {WRAP_AMBIGUITY_HOURS} "
            f"THEN {poh_col} + {WRAP_MODULUS_HOURS} ELSE {poh_col} END")
