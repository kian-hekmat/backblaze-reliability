"""Drive model normalization rules (DECISIONS.md, data-quality rule 3).

Applied in silver by mapping the small set of distinct raw model strings through
`normalize_model`, so the same tested function runs in Databricks and locally.
"""

import re

DATA_DRIVE_MIN_BYTES = 4_000_000_000_000  # DECISIONS rule 7: below 4 TB = boot drive / SSD

_PREFIXES = [  # (raw prefix, manufacturer, prefix to keep in canonical model)
    ("SEAGATE ", "Seagate", "Seagate "),
    ("TOSHIBA ", "Toshiba", "TOSHIBA "),
    ("HGST ", "HGST", "HGST "),
    ("HITACHI ", "HGST", "Hitachi "),
    ("WDC ", "WDC", "WDC "),
    ("WD ", "WDC", "WD "),
]


def normalize_model(raw: str) -> tuple[str, str, str]:
    """Return (model, model_short, manufacturer) for a raw Backblaze model string.

    - model: trimmed, internal whitespace collapsed; a bare WD Ultrastar part number
      (``WUH...``) gets the ``WDC `` prefix that Backblaze uses for the same drives.
    - model_short: model without the manufacturer prefix (matches Backblaze's published tables).
    - manufacturer: Seagate | Toshiba | HGST | WDC | Other.
    """
    model = re.sub(r"\s+", " ", raw.strip())
    if model.upper().startswith("WUH"):
        model = "WDC " + model
    upper = model.upper()
    for prefix, mfr, _ in _PREFIXES:
        if upper.startswith(prefix):
            return model, model[len(prefix):], mfr
    if re.match(r"^ST\d", upper):
        return model, model, "Seagate"
    return model, model, "Other"


def is_data_drive(capacity_bytes: int | None) -> bool:
    """Data drives are >= 4 TB; smaller drives are boot drives or SSDs (DECISIONS rule 7)."""
    return capacity_bytes is not None and capacity_bytes >= DATA_DRIVE_MIN_BYTES
