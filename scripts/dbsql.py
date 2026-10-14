"""Run SQL on the Databricks SQL warehouse via the Statement Execution API (Databricks CLI auth).

    uv run python scripts/dbsql.py "SELECT ..."                       # one statement, rows as JSON lines
    uv run python scripts/dbsql.py -f databricks/sql/x.sql [-o DIR]   # a file of statements

In a file, statements end with ';' at end of line. A statement preceded by a `-- name: <id>` line has its
result saved to <DIR>/<id>.csv (DIR defaults to results/sql). `-- ` comment lines are kept with the statement.
Profile: $DATABRICKS_PROFILE (default kianhekmatnejad). No credentials are stored in the repo.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROFILE = os.environ.get("DATABRICKS_PROFILE", "kianhekmatnejad")


def _cli(*args):
    return json.loads(subprocess.run(["databricks", "-p", PROFILE, *args],
                                     check=True, capture_output=True, text=True).stdout)


def run(statement: str) -> tuple[list[str], list[list]]:
    """Execute one statement; return (column names, rows as lists of strings/None)."""
    wh = _cli("warehouses", "list", "--output", "json")[0]["id"]
    body = {"warehouse_id": wh, "statement": statement, "wait_timeout": "50s",
            "on_wait_timeout": "CONTINUE", "disposition": "INLINE", "format": "JSON_ARRAY"}
    r = _cli("api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body))
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        r = _cli("api", "get", f"/api/2.0/sql/statements/{r['statement_id']}")
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(json.dumps(r["status"]))
    cols = [c["name"] for c in r.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = list(r.get("result", {}).get("data_array", []) or [])
    nxt = r.get("result", {}).get("next_chunk_internal_link")
    while nxt:
        chunk = _cli("api", "get", nxt)
        rows += chunk.get("data_array", []) or []
        nxt = chunk.get("next_chunk_internal_link")
    return cols, rows


def split_statements(sql: str) -> list[tuple[str | None, str]]:
    """Split a SQL file into (name, statement) pairs."""
    out, buf, name = [], [], None
    for line in sql.splitlines():
        m = re.match(r"^\s*--\s*name:\s*(\S+)", line)
        if m:
            name = m.group(1)
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";")
            if re.sub(r"--[^\n]*", "", stmt).strip():
                out.append((name, stmt))
            buf, name = [], None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("statement", nargs="?")
    ap.add_argument("-f", "--file")
    ap.add_argument("-o", "--outdir", default="results/sql")
    a = ap.parse_args()
    if a.statement:
        cols, rows = run(a.statement)
        for row in rows:
            print(json.dumps(dict(zip(cols, row))))
        return
    out = Path(a.outdir)
    for name, stmt in split_statements(Path(a.file).read_text()):
        cols, rows = run(stmt)
        if name:
            out.mkdir(parents=True, exist_ok=True)
            with open(out / f"{name}.csv", "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                w.writerows(rows)
            print(f"[ok] {name}: {len(rows)} rows -> {out / (name + '.csv')}")
        else:
            print(f"[ok] {stmt.splitlines()[-1][:80]}")


if __name__ == "__main__":
    sys.exit(main())
