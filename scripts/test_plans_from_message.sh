#!/usr/bin/env bash
# /plans/from-message smoke test for Linux/macOS shells.

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
API_KEY="${GATEWAY_API_KEY:-change-me-before-use}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

json_body() {
  local message="$1"
  local agent="$2"
  local plan_id="$3"
  python3 - "$message" "$agent" "$plan_id" <<'PY'
import json
import sys

message, agent, plan_id = sys.argv[1:4]
print(json.dumps({"message": message, "agent": agent, "plan_id": plan_id}))
PY
}

post_json() {
  local path="$1"
  local body="$2"
  local out="$3"
  curl -fsS \
    -X POST "$BASE_URL$path" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "$body" \
    -o "$out"
}

post_json_with_status() {
  local path="$1"
  local body="$2"
  local out="$3"
  curl -sS \
    -X POST "$BASE_URL$path" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "$body" \
    -o "$out" \
    -w "%{http_code}"
}

get_json() {
  local path="$1"
  local out="$2"
  curl -fsS \
    "$BASE_URL$path" \
    -H "X-API-Key: $API_KEY" \
    -o "$out"
}

json_value() {
  local file="$1"
  local expr="$2"
  python3 - "$file" "$expr" <<'PY'
import json
import sys

path, expr = sys.argv[1:3]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
value = eval(expr, {}, {"data": data})
print(value)
PY
}

assert_json() {
  local file="$1"
  local expr="$2"
  local message="$3"
  python3 - "$file" "$expr" "$message" <<'PY'
import json
import sys

path, expr, message = sys.argv[1:4]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
if not eval(expr, {}, {"data": data}):
    raise SystemExit(message)
PY
}

echo "Base URL: $BASE_URL"

PLAN_ID1="manual_from_message_list_$(date -u +%Y%m%d_%H%M%S)"
RESP1="$TMP_DIR/resp1.json"
WS1="$TMP_DIR/ws1.json"

echo
echo "--- Case 1: list project files ---"
post_json "/plans/from-message" "$(json_body "list project files" "project_maintainer_agent" "$PLAN_ID1")" "$RESP1"
assert_json "$RESP1" "data.get('status') == 'pending_approval'" "Expected pending_approval for case 1."
assert_json "$RESP1" "data.get('workspace', {}).get('state') == 'active'" "Expected active workspace for case 1."
SUMMARY1="$(json_value "$RESP1" "data['workspace']['summary_url']")"
get_json "$SUMMARY1" "$WS1"
assert_json "$WS1" "data['plan_json']['steps'][0]['tool'] == 'list_project_files'" "Expected list_project_files."
assert_json "$WS1" "data.get('execution_log_count') == 0" "/plans/from-message must not execute tools."
echo "Case 1 OK: tool=list_project_files and execution_log_count=0"

PLAN_ID2="manual_from_message_search_$(date -u +%Y%m%d_%H%M%S)"
RESP2="$TMP_DIR/resp2.json"
WS2="$TMP_DIR/ws2.json"

echo
echo "--- Case 2: search repo for PATCH_PROPOSAL.md ---"
post_json "/plans/from-message" "$(json_body "search repo for PATCH_PROPOSAL.md" "project_maintainer_agent" "$PLAN_ID2")" "$RESP2"
assert_json "$RESP2" "data.get('status') == 'pending_approval'" "Expected pending_approval for case 2."
SUMMARY2="$(json_value "$RESP2" "data['workspace']['summary_url']")"
get_json "$SUMMARY2" "$WS2"
assert_json "$WS2" "data['plan_json']['steps'][0]['tool'] == 'search_repo'" "Expected search_repo."
assert_json "$WS2" "'PATCH_PROPOSAL.md' in data['plan_json']['steps'][0]['args']['query']" "Expected query to include PATCH_PROPOSAL.md."
assert_json "$WS2" "data.get('execution_log_count') == 0" "/plans/from-message must not execute tools."
echo "Case 2 OK: tool=search_repo, query includes PATCH_PROPOSAL.md, execution_log_count=0"

PLAN_ID3="manual_from_message_unsafe_$(date -u +%Y%m%d_%H%M%S)"
RESP3="$TMP_DIR/resp3.json"

echo
echo "--- Case 3: unsafe phrasing (radarr_search) ---"
STATUS3="$(post_json_with_status "/plans/from-message" "$(json_body "run radarr_search for Inception" "project_maintainer_agent" "$PLAN_ID3")" "$RESP3")"
if [[ "$STATUS3" -ge 200 && "$STATUS3" -lt 300 ]]; then
  WS3="$TMP_DIR/ws3.json"
  SUMMARY3="$(json_value "$RESP3" "data['workspace']['summary_url']")"
  get_json "$SUMMARY3" "$WS3"
  assert_json "$WS3" "data['plan_json']['steps'][0]['tool'] != 'radarr_search'" "Unsafe message produced radarr_search."
  assert_json "$WS3" "data.get('execution_log_count') == 0" "/plans/from-message must not execute tools."
  TOOL3="$(json_value "$WS3" "data['plan_json']['steps'][0]['tool']")"
  echo "Case 3 OK: did not propose radarr_search (tool=$TOOL3), execution_log_count=0"
else
  if grep -Eq "policy_rejected|Unsupported|400" "$RESP3"; then
    echo "Case 3 OK: HTTP $STATUS3 rejection."
  else
    cat "$RESP3"
    echo "Unexpected HTTP $STATUS3 for unsafe message." >&2
    exit 1
  fi
fi

echo
echo "Done."
