#!/usr/bin/env bash
# Host-side smoke test for pg-dba-gym.
# Hits /health, /tasks, POST /reset, POST /step and prints PASS/FAIL.
# Exits non-zero on any failure.
set -euo pipefail

HOST_URL="${HOST_URL:-http://localhost:8000}"
FAILED=0

if command -v jq >/dev/null 2>&1; then
  PRETTY=(jq .)
else
  PRETTY=(cat)
fi

run() {
  local name="$1"; shift
  echo "---- $name ----"
  local body status
  # Capture body + status code
  local tmp
  tmp=$(mktemp)
  status=$(curl -sS -o "$tmp" -w "%{http_code}" "$@" || echo "000")
  body=$(cat "$tmp"); rm -f "$tmp"
  if [[ "$status" =~ ^2 ]]; then
    echo "$body" | "${PRETTY[@]}" || echo "$body"
    echo "PASS: $name (HTTP $status)"
  else
    echo "$body"
    echo "FAIL: $name (HTTP $status)"
    FAILED=1
  fi
  echo
}

run "GET /health" "$HOST_URL/health"
run "GET /tasks"  "$HOST_URL/tasks"
run "POST /reset" -X POST "$HOST_URL/reset" \
    -H 'Content-Type: application/json' \
    -d '{"task":"easy"}'
run "POST /step"  -X POST "$HOST_URL/step" \
    -H 'Content-Type: application/json' \
    -d '{"action":{"sql":"SELECT 1","done":false}}'

if [ "$FAILED" -ne 0 ]; then
  echo "Smoke test FAILED."
  exit 1
fi
echo "Smoke test PASSED."
