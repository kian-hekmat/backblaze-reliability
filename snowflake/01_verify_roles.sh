#!/usr/bin/env bash
# Verifies Phase 0 role design: ANALYST_READER can read GOLD but cannot create or modify.
# Secondary roles are disabled per statement: this user defaults to DEFAULT_SECONDARY_ROLES=ALL,
# which would otherwise let ACCOUNTADMIN privileges leak into the test and mask failures.
# Each check runs as its own statement so an expected failure doesn't stop the rest.
# Usage: bash snowflake/01_verify_roles.sh > results/phase0_role_check.txt
set -u
run() {  # $1 = label, $2 = expectation (OK|FAIL), $3 = sql
  out=$(snow sql -q "$3" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then got=OK; else got=FAIL; fi
  status=$([ "$got" = "$2" ] && echo PASS || echo UNEXPECTED)
  echo "[$status] $1 (expected $2, got $got)"
  [ "$got" = FAIL ] && echo "$out" | grep -E "^\│ [0-9]{6}|not authorized|Insufficient|does not exist" | head -2
}
run "LOADER creates probe table in GOLD" OK \
  "use role LOADER; use secondary roles none; use warehouse LOAD_WH; create or replace table BACKBLAZE.GOLD._ROLE_PROBE as select 1 as x;"
run "ANALYST_READER selects from GOLD" OK \
  "use role ANALYST_READER; use secondary roles none; use warehouse BI_WH; select count(*) from BACKBLAZE.GOLD._ROLE_PROBE;"
run "ANALYST_READER creates table in GOLD" FAIL \
  "use role ANALYST_READER; use secondary roles none; use warehouse BI_WH; create table BACKBLAZE.GOLD._READER_SHOULD_FAIL (x int);"
run "ANALYST_READER creates view in ANALYTICS" FAIL \
  "use role ANALYST_READER; use secondary roles none; use warehouse BI_WH; create view BACKBLAZE.ANALYTICS._READER_SHOULD_FAIL as select 1 x;"
run "ANALYST_READER inserts into GOLD table" FAIL \
  "use role ANALYST_READER; use secondary roles none; use warehouse BI_WH; insert into BACKBLAZE.GOLD._ROLE_PROBE values (2);"
run "ANALYST_READER drops GOLD table" FAIL \
  "use role ANALYST_READER; use secondary roles none; use warehouse BI_WH; drop table BACKBLAZE.GOLD._ROLE_PROBE;"
run "LOADER drops probe table (cleanup)" OK \
  "use role LOADER; use secondary roles none; drop table BACKBLAZE.GOLD._ROLE_PROBE;"
