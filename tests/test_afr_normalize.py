import math

import numpy as np
import pandas as pd
import pytest

from reliability.afr import afr, afr_table
from reliability.normalize import is_data_drive, normalize_model


# --- AFR: hand-computed examples ---------------------------------------------

def test_afr_one_failure_one_drive_year():
    assert afr(1, 365) == pytest.approx(100.0)


def test_afr_published_backblaze_total_q2_2026():
    # Backblaze Q2 2026 totals: 1,498 failures over 31,553,350 drive days -> 1.73%
    assert round(afr(1498, 31_553_350), 2) == 1.73


def test_afr_zero_failures_is_zero():
    assert afr(0, 10_000) == 0.0


def test_afr_zero_drive_days_is_nan_not_zero():
    assert math.isnan(afr(0, 0))


def test_afr_single_drive_failed_on_first_day():
    # one drive observed one day and failed that day: 1 / (1/365) * 100
    assert afr(1, 1) == pytest.approx(36_500.0)


def test_afr_leap_year_convention():
    assert afr(2, 732, days_per_year=366) == pytest.approx(100.0)


def test_afr_vectorized():
    np.testing.assert_allclose(afr([1, 0, 3], [365, 100, 730]), [100.0, 0.0, 150.0])


def test_afr_rejects_negative():
    with pytest.raises(ValueError):
        afr(-1, 10)


def test_afr_table_counts_drive_days_as_rows():
    daily = pd.DataFrame({
        "model": ["A"] * 5 + ["B"] * 2,
        "serial_number": ["a1", "a1", "a1", "a2", "a2", "b1", "b1"],
        "failure": [0, 0, 1, 0, 0, 0, 0],
    })
    t = afr_table(daily, ["model"]).set_index("model")
    assert t.loc["A", "drive_count"] == 2
    assert t.loc["A", "drive_days"] == 5
    assert t.loc["A", "failures"] == 1
    assert t.loc["A", "afr_pct"] == pytest.approx(1 / (5 / 365) * 100)
    assert t.loc["B", "afr_pct"] == 0.0


# --- Model normalization -----------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("WDC WUH721816ALE6L4", ("WDC WUH721816ALE6L4", "WUH721816ALE6L4", "WDC")),
    ("WUH721816ALE6L4", ("WDC WUH721816ALE6L4", "WUH721816ALE6L4", "WDC")),  # observed bare variant
    ("TOSHIBA MG07ACA14TA", ("TOSHIBA MG07ACA14TA", "MG07ACA14TA", "Toshiba")),
    ("HGST HUH721212ALE604", ("HGST HUH721212ALE604", "HUH721212ALE604", "HGST")),
    ("ST16000NM001G", ("ST16000NM001G", "ST16000NM001G", "Seagate")),
    ("Seagate BarraCuda SSD ZA250CM10002", ("Seagate BarraCuda SSD ZA250CM10002", "BarraCuda SSD ZA250CM10002", "Seagate")),
    ("  ST12000NM0008  ", ("ST12000NM0008", "ST12000NM0008", "Seagate")),
    ("TOSHIBA  MG08ACA16TA", ("TOSHIBA MG08ACA16TA", "MG08ACA16TA", "Toshiba")),
    ("WD Blue SA510 2.5 250GB", ("WD Blue SA510 2.5 250GB", "Blue SA510 2.5 250GB", "WDC")),
    ("CT250MX500SSD1", ("CT250MX500SSD1", "CT250MX500SSD1", "Other")),
    ("DELLBOSS VD", ("DELLBOSS VD", "DELLBOSS VD", "Other")),
])
def test_normalize_model(raw, expected):
    assert normalize_model(raw) == expected


def test_bare_and_prefixed_variants_collapse_to_one_model():
    assert normalize_model("WUH721816ALE6L4")[0] == normalize_model("WDC WUH721816ALE6L4")[0]


def test_is_data_drive_threshold():
    assert is_data_drive(4_000_787_030_016)       # 4 TB HGST data drive
    assert is_data_drive(24_000_277_250_048)
    assert not is_data_drive(500_107_862_016)    # 2.5" boot HDD
    assert not is_data_drive(2_048_408_248_320)  # 2 TB SSD
    assert not is_data_drive(None)
