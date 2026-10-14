import duckdb
import pytest

from reliability.age import WRAP_MODULUS_HOURS, corrected_poh, corrected_poh_sql

M = WRAP_MODULUS_HOURS


@pytest.mark.parametrize("model, poh, hfh, expected", [
    # SMART 240 available (primary rule)
    ("ST8000NM0055", 1_362, 79_504, 1_362 + M),    # wrapped: 240 far above 9 (observed medians, 2026-06-30)
    ("ST8000NM0055", 77_447, 77_361, 77_447),      # not yet wrapped: 240 ~ 9
    ("ST8000NM0055", 10_336, 10_300, 10_336),      # young replacement drive: the old threshold rule got this wrong
    ("ST8000DM002", 6_565, 84_672, 6_565 + M),
    ("ST16000NM001G", 3_379, 3_350, 3_379),        # any model: no wrap when 240 ~ 9
    # SMART 240 missing (fallback for known wrapping models)
    ("ST8000NM0055", 3_379, None, 3_379 + M),
    ("ST8000DM002", 30_000, None, 30_000),
    ("ST6000DX000", 34, None, 34 + M),
    ("ST4000DM000", 12, None, 12 + M),
    ("ST16000NM001G", 3_379, None, 3_379),
    ("ST8000NM0055", None, 5, None),
    ("ST8000NM0055", -5, None, None),
])
def test_corrected_poh(model, poh, hfh, expected):
    assert corrected_poh(model, poh, hfh) == expected


def test_wrap_during_window_stays_monotonic():
    # drive crosses the wrap: 9 goes 78,187 -> 0 while 240 keeps counting
    assert corrected_poh("ST8000NM0055", 0, 78_100) == corrected_poh("ST8000NM0055", 78_187, 78_099) + 1


def test_sql_matches_python():
    cases = [("ST8000NM0055", 3_379, None), ("ST8000NM0055", 75_453, None), ("ST8000DM002", 0, None),
             ("ST16000NM001G", 100, None), ("ST8000NM0055", None, None), ("X", -1, None),
             ("ST8000NM0055", 1_362, 79_504), ("ST8000NM0055", 10_336, 10_300), ("Y", 50, 80_000)]
    con = duckdb.connect()
    for model, poh, hfh in cases:
        got = con.execute(f"SELECT {corrected_poh_sql('m', 'p', 'h')} FROM (SELECT ?::VARCHAR m, ?::BIGINT p, ?::BIGINT h)",
                          [model, poh, hfh]).fetchone()[0]
        assert got == corrected_poh(model, poh, hfh), (model, poh, hfh, got)
