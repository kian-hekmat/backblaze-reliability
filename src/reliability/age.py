"""Drive age from SMART 9 (power-on hours), with known counter wraparound corrected.

Observed in Q2 2026 (DECISIONS: SMART 9 wraparound): on ST8000NM0055 and ST8000DM002 the SMART 9 raw
value drops from 78,187 to ~0, i.e. the counter wraps modulo 78,188 hours (~8.9 years). Most of these
drives are 8-10 years old, so a wrapped reading would make an old drive look new.

Correction: for a wrapping model, a reading below WRAP_AMBIGUITY_HOURS is taken as wrapped once and
WRAP_MODULUS_HOURS is added. Readings between that threshold and the modulus are taken as-is. Valid
because these models were all installed years before the window (Backblaze reports average ages of
~105-115 months); the result is checked against Backblaze's published average age per model.
"""

WRAP_MODULUS_HOURS = 78_188
WRAP_AMBIGUITY_HOURS = 30_000
WRAP_MODELS = frozenset({"ST8000NM0055", "ST8000DM002"})
# Signature used by the pipeline to detect wraparound in models not listed above (fails loudly):
WRAP_DETECT_BEFORE_MIN = 70_000
WRAP_DETECT_AFTER_MAX = 1_000


def corrected_poh(model: str, poh: float | None) -> float | None:
    """Power-on hours with wraparound corrected for known wrapping models."""
    if poh is None or poh < 0:
        return None
    if model in WRAP_MODELS and poh < WRAP_AMBIGUITY_HOURS:
        return poh + WRAP_MODULUS_HOURS
    return poh


def corrected_poh_sql(model_col: str = "model", poh_col: str = "smart_9_raw") -> str:
    """Same rule as a SQL expression (Spark SQL / DuckDB / Snowflake compatible)."""
    models = ", ".join(f"'{m}'" for m in sorted(WRAP_MODELS))
    return (f"CASE WHEN {poh_col} IS NULL OR {poh_col} < 0 THEN NULL "
            f"WHEN {model_col} IN ({models}) AND {poh_col} < {WRAP_AMBIGUITY_HOURS} "
            f"THEN {poh_col} + {WRAP_MODULUS_HOURS} ELSE {poh_col} END")
