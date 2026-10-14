import duckdb
import pytest

from reliability.age import WRAP_MODULUS_HOURS, corrected_poh, corrected_poh_sql


@pytest.mark.parametrize("model, poh, expected", [
    ("ST8000NM0055", 75_453, 75_453),                      # pre-wrap reading kept
    ("ST8000NM0055", 3_379, 3_379 + WRAP_MODULUS_HOURS),   # wrapped reading corrected
    ("ST8000NM0055", 0, WRAP_MODULUS_HOURS),               # exactly at the wrap
    ("ST8000DM002", 29_999, 29_999 + WRAP_MODULUS_HOURS),
    ("ST8000DM002", 30_000, 30_000),
    ("ST6000DX000", 34, 34 + WRAP_MODULUS_HOURS),           # found in 2023-2024 quarters
    ("ST4000DM000", 12, 12 + WRAP_MODULUS_HOURS),
    ("ST16000NM001G", 3_379, 3_379),                       # non-wrapping model untouched
    ("ST8000NM0055", None, None),
    ("ST8000NM0055", -5, None),
])
def test_corrected_poh(model, poh, expected):
    assert corrected_poh(model, poh) == expected


def test_wrap_during_window_stays_monotonic():
    # drive crosses the wrap: 78,187 then 0 the next day -> corrected 78,187 then 78,188
    assert corrected_poh("ST8000NM0055", 0) == corrected_poh("ST8000NM0055", 78_187) + 1


def test_sql_matches_python():
    cases = [("ST8000NM0055", 3_379), ("ST8000NM0055", 75_453), ("ST8000DM002", 0),
             ("ST16000NM001G", 100), ("ST8000NM0055", None), ("X", -1)]
    con = duckdb.connect()
    for model, poh in cases:
        got = con.execute(f"SELECT {corrected_poh_sql('m', 'p')} FROM (SELECT ?::VARCHAR m, ?::BIGINT p)",
                          [model, poh]).fetchone()[0]
        assert got == corrected_poh(model, poh), (model, poh, got)
