#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

RESET=$'\033[0m'
BOLD=$'\033[1m'
CYAN=$'\033[36m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RED=$'\033[31m'
BLUE=$'\033[34m'

step() {
  local label="$1"
  printf "\n${BLUE}${BOLD}[%s]${RESET} %s\n" "$(date +%H:%M:%S)" "$label"
}

ok() {
  local message="$1"
  printf "${GREEN}  ✓${RESET} %s\n" "$message"
}

info() {
  local message="$1"
  printf "${YELLOW}  •${RESET} %s\n" "$message"
}

fail() {
  local message="$1"
  printf "${RED}  ✗${RESET} %s\n" "$message" >&2
}

cleanup_failed=0

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

export AIGW_GATEWAY_ID="${AIGW_GATEWAY_ID:-47e9610a-2ad8-4b19-98d3-2b5364a7f38f}"
export KONNECT_METERING_INGEST_ENDPOINT="${KONNECT_METERING_INGEST_ENDPOINT:-https://us.api.konghq.com/v3/openmeter/events}"
export AIGW_OPENAI_AUTHORIZATION="${AIGW_OPENAI_AUTHORIZATION:-Bearer ${DECK_OPENAI_API_KEY:-}}"
export AIGW_GEMINI_API_KEY="${AIGW_GEMINI_API_KEY:-${DECK_GEMINI_API_KEY:-}}"
AI_GATEWAY_ENTITY_FILES=(
  kongctl/ai-gateway/agents.yaml
  kongctl/ai-gateway/mcp_servers.yaml
  kongctl/ai-gateway/models.yaml
  kongctl/ai-gateway/consumer_groups.yaml
  kongctl/ai-gateway/consumers.yaml
  kongctl/ai-gateway/policies.yaml
  kongctl/ai-gateway/opentelemetry.yaml
  kongctl/ai-gateway/providers.yaml
  kongctl/ai-gateway/identity_providers.yaml
)

echo
echo "${CYAN}========================================${RESET}"
echo "${BOLD}${CYAN}            RAG Demo Shutdown${RESET}"
echo "${CYAN}========================================${RESET}"

step "Removing AA-Demo-2 AI Builder Catalog records"
if [[ -n "${KONNECT_TOKEN:-}" ]] && command -v python3 >/dev/null 2>&1; then
  if python3 scripts/teardown_ai_builder_catalog.py; then
    ok "AA-Demo-2 AI Builder Catalog records removed"
  else
    fail "AA-Demo-2 AI Builder Catalog cleanup did not complete"
    cleanup_failed=1
  fi
else
  fail "KONNECT_TOKEN and python3 are required to remove the AI Builder Catalog records"
  cleanup_failed=1
fi

step "Removing AA-Demo-2 Metering & Billing catalog"
if [[ -n "${KONNECT_SYSTEM_TOKEN:-}" ]] && command -v python3 >/dev/null 2>&1; then
  if python3 scripts/teardown_ai_gateway_metering_billing.py; then
    ok "AA-Demo-2 billing catalog removed"
  else
    fail "AA-Demo-2 billing catalog cleanup did not complete"
    cleanup_failed=1
  fi
else
  fail "KONNECT_SYSTEM_TOKEN and python3 are required to remove the billing catalog"
  cleanup_failed=1
fi

step "Removing managed AA-Demo-2 AI Gateway entities"
if [[ -n "${KONNECT_TOKEN:-}" ]] && command -v kongctl >/dev/null 2>&1; then
  if kongctl delete --auto-approve --force -f "${AI_GATEWAY_ENTITY_FILES[@]}"; then
    ok "AA-Demo-2 child entities removed (the AA-Demo-2 gateway is retained)"
  else
    fail "AA-Demo-2 entity cleanup did not complete"
    cleanup_failed=1
  fi
else
  fail "KONNECT_TOKEN and kongctl are required to remove AI Gateway entities"
  cleanup_failed=1
fi

step "Stopping local stack and removing Opik volumes"
docker compose --profile opik down -v
ok "Docker services stopped and volumes removed"

echo
echo "${CYAN}========================================${RESET}"
echo "${BOLD}${GREEN}         RAG Demo Shutdown Complete${RESET}"
echo "${CYAN}========================================${RESET}"
echo

if [[ "$cleanup_failed" -ne 0 ]]; then
  exit 1
fi
