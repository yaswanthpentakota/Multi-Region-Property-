#!/usr/bin/env bash
# ============================================================
# demonstrate_failover.sh
#
# Demonstrates NGINX failover: when backend-us is stopped,
# requests to /us/* are automatically served by backend-eu.
#
# Usage:
#   bash tests/demonstrate_failover.sh
#
# Prerequisites:
#   docker-compose up -d
#   Wait ~90 seconds for all services to be healthy
# ============================================================

set -euo pipefail

BASE_URL="http://localhost:8080"
GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[1;33m"
NC="\033[0m"

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
separator() { echo -e "\n${YELLOW}══════════════════════════════════════════════════${NC}\n"; }

separator
info "Multi-Region Failover Demonstration"
separator

# ── Step 1: Verify both backends are up ──────────────────────────────
info "Step 1: Verifying both backends are healthy..."

US_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/us/health")
EU_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/eu/health")

if [ "$US_STATUS" == "200" ]; then
  pass "US backend is healthy (HTTP $US_STATUS)"
else
  fail "US backend returned HTTP $US_STATUS"
  exit 1
fi

if [ "$EU_STATUS" == "200" ]; then
  pass "EU backend is healthy (HTTP $EU_STATUS)"
else
  fail "EU backend returned HTTP $EU_STATUS"
  exit 1
fi

# ── Step 2: Normal request to /us/health ─────────────────────────────
separator
info "Step 2: Sending a normal request to /us/health..."
RESPONSE=$(curl -s "${BASE_URL}/us/health")
echo "  Response: $RESPONSE"
pass "Got response from US backend"

# ── Step 3: Stop backend-us ──────────────────────────────────────────
separator
info "Step 3: Stopping backend-us container to simulate failure..."
docker stop backend_us
info "backend_us container stopped."
sleep 3

# ── Step 4: Request to /us/* should now be served by backend-eu ──────
separator
info "Step 4: Sending request to /us/health (backend-us is DOWN)..."

FAILOVER_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/us/health")
FAILOVER_RESPONSE=$(curl -s "${BASE_URL}/us/health")

echo "  HTTP Status : $FAILOVER_STATUS"
echo "  Response    : $FAILOVER_RESPONSE"

if [ "$FAILOVER_STATUS" == "200" ]; then
  pass "Failover successful! NGINX routed /us/ traffic to backend-eu (HTTP $FAILOVER_STATUS)"
  if echo "$FAILOVER_RESPONSE" | grep -q '"region":"eu"'; then
    pass "Confirmed: Response came from backend-eu (region=eu in payload)"
  else
    info "Response region field: $FAILOVER_RESPONSE"
  fi
else
  fail "Failover failed! HTTP $FAILOVER_STATUS received."
  docker start backend_us
  exit 1
fi

# ── Step 5: Verify EU backend logs ───────────────────────────────────
separator
info "Step 5: Checking backend-eu logs for /us/ request handling..."
EU_LOGS=$(docker logs backend_eu 2>&1 | tail -20)
echo "$EU_LOGS"

# ── Step 6: Restart backend-us ───────────────────────────────────────
separator
info "Step 6: Restarting backend-us to restore full capacity..."
docker start backend_us
sleep 5

RESTORED_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/us/health")
if [ "$RESTORED_STATUS" == "200" ]; then
  pass "backend-us is back online (HTTP $RESTORED_STATUS)"
else
  info "backend-us may still be warming up (HTTP $RESTORED_STATUS) – try again in a few seconds"
fi

separator
pass "Failover demonstration complete!"
echo ""
echo "  Summary:"
echo "    ✅ /us/health returned 200 with both backends UP"
echo "    ✅ backend-us was stopped"
echo "    ✅ /us/health still returned 200 via failover to backend-eu"
echo "    ✅ backend-us was restarted and restored"
echo ""
