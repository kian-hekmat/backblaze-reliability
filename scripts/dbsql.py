"""Run one SQL statement on the Databricks SQL warehouse and print rows as JSON lines.

Usage: uv run python scripts/dbsql.py "SELECT ..."   (profile: $DATABRICKS_PROFILE, default kianhekmatnejad)
"""
import json
import os
import subprocess
import sys

profile = os.environ.get("DATABRICKS_PROFILE", "kianhekmatnejad")
wh = json.loads(subprocess.run(["databricks", "-p", profile, "warehouses", "list", "--output", "json"],
                               check=True, capture_output=True, text=True).stdout)[0]["id"]
body = {"warehouse_id": wh, "statement": sys.argv[1], "wait_timeout": "50s", "on_wait_timeout": "CONTINUE"}
r = json.loads(subprocess.run(["databricks", "-p", profile, "api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body)],
                              check=True, capture_output=True, text=True).stdout)
while r["status"]["state"] in ("PENDING", "RUNNING"):
    r = json.loads(subprocess.run(["databricks", "-p", profile, "api", "get", f"/api/2.0/sql/statements/{r['statement_id']}"],
                                  check=True, capture_output=True, text=True).stdout)
if r["status"]["state"] != "SUCCEEDED":
    sys.exit(json.dumps(r["status"]))
cols = [c["name"] for c in r["manifest"]["schema"]["columns"]]
for row in r.get("result", {}).get("data_array", []):
    print(json.dumps(dict(zip(cols, row))))
