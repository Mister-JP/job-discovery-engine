#!/bin/bash

# Full end-to-end API regression test using curl against the live backend.
#
# Usage:
#   bash tests/manual_curl_test.sh
#   BASE_URL=http://localhost:8000 QUERY="AI safety labs hiring" bash tests/manual_curl_test.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
QUERY="${QUERY:-AI safety research labs hiring researchers}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

RUN_RESPONSE="$TMP_DIR/run.json"
RUN_DETAIL_RESPONSE="$TMP_DIR/run_detail.json"
RUN_LIST_RESPONSE="$TMP_DIR/run_list.json"
INSTITUTIONS_RESPONSE="$TMP_DIR/institutions.json"
JOBS_RESPONSE="$TMP_DIR/jobs.json"

FAILURES=0

print_section() {
  printf '\n=== %s ===\n' "$1"
}

record_ok() {
  printf '[OK] %s\n' "$1"
}

record_warn() {
  printf '[WARN] %s\n' "$1"
}

record_fail() {
  printf '[FAIL] %s\n' "$1"
  FAILURES=$((FAILURES + 1))
}

print_json() {
  python3 -m json.tool "$1"
}

parse_json() {
  local file="$1"
  local expr="$2"

  python3 - "$file" "$expr" <<'PY'
import json
import sys

file_path, expression = sys.argv[1], sys.argv[2]
with open(file_path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

safe_globals = {
    "__builtins__": {},
    "len": len,
    "any": any,
}
value = eval(expression, safe_globals, {"data": data})
if value is None:
    print("")
elif isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

run_request() {
  local method="$1"
  local url="$2"
  local output_file="$3"
  local data="${4:-}"

  local http_code
  if [[ -n "$data" ]]; then
    http_code="$(curl -sS -o "$output_file" -w '%{http_code}' -X "$method" "$url" \
      -H 'Content-Type: application/json' \
      -d "$data")"
  else
    http_code="$(curl -sS -o "$output_file" -w '%{http_code}' -X "$method" "$url")"
  fi

  if [[ "$http_code" != 2* ]]; then
    printf 'HTTP %s from %s %s\n' "$http_code" "$method" "$url" >&2
    print_json "$output_file" || cat "$output_file"
    exit 1
  fi
}

print_section "1. Health check"
run_request GET "$BASE_URL/" "$TMP_DIR/health.json"
print_json "$TMP_DIR/health.json"

print_section "2. Trigger search"
REQUEST_BODY="$(python3 - "$QUERY" <<'PY'
import json
import sys

print(json.dumps({"query": sys.argv[1]}))
PY
)"
run_request POST "$BASE_URL/api/search-runs" "$RUN_RESPONSE" "$REQUEST_BODY"
print_json "$RUN_RESPONSE"

RUN_ID="$(parse_json "$RUN_RESPONSE" 'data["id"]')"
STATUS="$(parse_json "$RUN_RESPONSE" 'data["status"]')"
RAW="$(parse_json "$RUN_RESPONSE" 'data["candidates_raw"]')"
VERIFIED="$(parse_json "$RUN_RESPONSE" 'data["candidates_verified"]')"
NEW_INST="$(parse_json "$RUN_RESPONSE" 'data["institutions_new"]')"
UPDATED_INST="$(parse_json "$RUN_RESPONSE" 'data["institutions_updated"]')"
NEW_JOBS="$(parse_json "$RUN_RESPONSE" 'data["jobs_new"]')"
UPDATED_JOBS="$(parse_json "$RUN_RESPONSE" 'data["jobs_updated"]')"
DURATION_MS="$(parse_json "$RUN_RESPONSE" 'data["duration_ms"]')"
ERROR_DETAIL="$(parse_json "$RUN_RESPONSE" 'data["error_detail"]')"

print_section "Search Run Summary"
printf 'Run ID:                %s\n' "$RUN_ID"
printf 'Status:                %s\n' "$STATUS"
printf 'Raw candidates:        %s\n' "$RAW"
printf 'Verified candidates:   %s\n' "$VERIFIED"
printf 'Institutions new:      %s\n' "$NEW_INST"
printf 'Institutions updated:  %s\n' "$UPDATED_INST"
printf 'Jobs new:              %s\n' "$NEW_JOBS"
printf 'Jobs updated:          %s\n' "$UPDATED_JOBS"
printf 'Duration (ms):         %s\n' "$DURATION_MS"
printf 'Error detail:          %s\n' "${ERROR_DETAIL:-<none>}"

print_section "3. Get run detail"
run_request GET "$BASE_URL/api/search-runs/$RUN_ID" "$RUN_DETAIL_RESPONSE"
python3 - "$RUN_DETAIL_RESPONSE" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

evidence = data["verification_evidence"]
print(f"Evidence records: {len(evidence)}")
for item in evidence[:10]:
    status = "PASS" if item["passed"] else "FAIL"
    detail = (item.get("detail") or "").replace("\n", " ")
    candidate_name = (item.get("candidate_name") or "")[:30]
    check_name = item["check_name"][:20]
    print(f"  {status:<4} {candidate_name:<30} {check_name:<20} {detail[:80]}")
PY

print_section "4. List search runs"
run_request GET "$BASE_URL/api/search-runs?limit=5" "$RUN_LIST_RESPONSE"
python3 - "$RUN_LIST_RESPONSE" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    runs = json.load(handle)

print(f"Total runs returned: {len(runs)}")
for run in runs:
    query = run["query"][:40]
    print(
        f"  {run['status']:<10} {query:<42} "
        f"raw={run['candidates_raw']} verified={run['candidates_verified']}"
    )
PY

print_section "5. List institutions"
run_request GET "$BASE_URL/api/institutions?verified=true" "$INSTITUTIONS_RESPONSE"
python3 - "$INSTITUTIONS_RESPONSE" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    institutions = json.load(handle)

print(f"Verified institutions: {len(institutions)}")
for institution in institutions[:10]:
    institution_type = institution.get("institution_type") or ""
    print(
        f"  {institution['name'][:30]:<30} "
        f"{institution['domain'][:25]:<25} type={institution_type}"
    )
PY

print_section "6. List jobs"
run_request GET "$BASE_URL/api/jobs?is_active=true" "$JOBS_RESPONSE"
python3 - "$JOBS_RESPONSE" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    jobs = json.load(handle)

print(f"Active jobs: {len(jobs)}")
for job in jobs[:10]:
    level = job.get("experience_level") or ""
    print(
        f"  {job['title'][:35]:<35} "
        f"@ {job['institution_name'][:25]:<25} level={level}"
    )
PY

RUN_LIST_COUNT="$(parse_json "$RUN_LIST_RESPONSE" 'len(data)')"
RUN_LIST_CONTAINS_ID="$(parse_json "$RUN_LIST_RESPONSE" 'any(item["id"] == "'"$RUN_ID"'" for item in data)')"
INSTITUTION_COUNT="$(parse_json "$INSTITUTIONS_RESPONSE" 'len(data)')"
JOB_COUNT="$(parse_json "$JOBS_RESPONSE" 'len(data)')"
EVIDENCE_COUNT="$(parse_json "$RUN_DETAIL_RESPONSE" 'len(data["verification_evidence"])')"

print_section "Validation"

if [[ "$STATUS" == "completed" ]]; then
  record_ok "search completed successfully"
else
  record_fail "search status is $STATUS${ERROR_DETAIL:+ ($ERROR_DETAIL)}"
fi

if [[ "$VERIFIED" =~ ^[0-9]+$ ]] && (( VERIFIED > 0 )); then
  record_ok "$VERIFIED candidates were verified"
else
  record_fail "no candidates were verified"
fi

if [[ "$RAW" =~ ^[0-9]+$ ]] && [[ "$VERIFIED" =~ ^[0-9]+$ ]] && (( RAW >= VERIFIED )); then
  record_ok "raw candidate count is >= verified candidate count"
else
  record_fail "raw candidate count ($RAW) is less than verified count ($VERIFIED)"
fi

if [[ "$VERIFIED" =~ ^[0-9]+$ ]] && [[ "$NEW_INST" =~ ^[0-9]+$ ]] && [[ "$UPDATED_INST" =~ ^[0-9]+$ ]] && (( VERIFIED >= NEW_INST + UPDATED_INST )); then
  record_ok "verified candidates cover institution inserts and updates"
else
  record_fail "verified candidates ($VERIFIED) do not cover institution changes ($NEW_INST new + $UPDATED_INST updated)"
fi

if [[ "$RUN_LIST_COUNT" =~ ^[0-9]+$ ]] && (( RUN_LIST_COUNT > 0 )); then
  record_ok "recent search runs endpoint returned data"
else
  record_fail "recent search runs endpoint returned no data"
fi

if [[ "$RUN_LIST_CONTAINS_ID" == "true" ]]; then
  record_ok "recent search runs includes the new run"
else
  record_fail "recent search runs does not include run $RUN_ID"
fi

if [[ "$EVIDENCE_COUNT" =~ ^[0-9]+$ ]] && (( EVIDENCE_COUNT > 0 )); then
  record_ok "run detail includes verification evidence"
else
  record_fail "run detail returned no verification evidence"
fi

if [[ "$INSTITUTION_COUNT" =~ ^[0-9]+$ ]] && (( INSTITUTION_COUNT > 0 )); then
  record_ok "verified institutions endpoint returned data"
else
  record_fail "verified institutions endpoint returned no data"
fi

if [[ "$JOB_COUNT" =~ ^[0-9]+$ ]] && (( JOB_COUNT > 0 )); then
  record_ok "active jobs endpoint returned data"
else
  record_fail "active jobs endpoint returned no data"
fi

if [[ "$DURATION_MS" =~ ^[0-9]+$ ]] && (( DURATION_MS < 30000 )); then
  record_ok "search completed in under 30 seconds"
else
  record_fail "search took too long or duration is missing ($DURATION_MS ms)"
fi

if [[ "$NEW_INST" =~ ^[0-9]+$ ]] && [[ "$UPDATED_INST" =~ ^[0-9]+$ ]] && [[ "$NEW_JOBS" =~ ^[0-9]+$ ]] && [[ "$UPDATED_JOBS" =~ ^[0-9]+$ ]] && (( NEW_INST + UPDATED_INST + NEW_JOBS + UPDATED_JOBS > 0 )); then
  record_ok "search stored or refreshed institution/job data"
else
  record_warn "no institution/job rows changed; this may mean the search only found duplicates"
fi

print_section "Complete"
if (( FAILURES == 0 )); then
  printf 'End-to-end curl test passed.\n'
else
  printf 'End-to-end curl test failed with %d issue(s).\n' "$FAILURES"
  exit 1
fi
