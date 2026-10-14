import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dbsql import split_statements  # noqa: E402


def test_split_named_and_unnamed_statements():
    sql = """-- header comment only;
CREATE VIEW a AS SELECT 1;

-- name: q1
-- What is X?
SELECT x
FROM t;
SELECT 2;
"""
    parts = split_statements(sql)
    assert [n for n, _ in parts] == [None, "q1", None]
    assert parts[1][1].endswith("FROM t")
    assert "What is X?" in parts[1][1]
