#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$#" -gt 1 ]] || [[ "$#" -eq 1 && "$1" != "NORMAL_RUN" ]]; then
  echo "Usage: $0 [NORMAL_RUN]" >&2
  exit 2
fi

if [[ "${1:-}" == "NORMAL_RUN" ]]; then
  export RUN_NORMAL_DEMO_ON_START=true
fi

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
  printf "${CYAN}  •${RESET} %s\n" "$message"
}

fail() {
  local message="$1"
  printf "${RED}  ✗${RESET} %s\n" "$message" >&2
}

link() {
  local url="$1"
  local label="$2"
  printf '\033]8;;%s\033\\%s\033]8;;\033\\' "$url" "$label"
}

require_bin() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    fail "Required command not found: $name"
    exit 1
  fi
}

urlencode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

konnect_api() {
  local method="$1"
  local url="$2"
  local data="${3:-}"
  local body_file
  body_file="$(mktemp)"
  local http_status

  if [[ -n "$data" ]]; then
    http_status="$(curl -sS -X "$method" "$url" \
      -H "Authorization: Bearer $KONNECT_TOKEN" \
      -H "Content-Type: application/json" \
      --data "$data" \
      -o "$body_file" \
      -w "%{http_code}")"
  else
    http_status="$(curl -sS -X "$method" "$url" \
      -H "Authorization: Bearer $KONNECT_TOKEN" \
      -o "$body_file" \
      -w "%{http_code}")"
  fi

  echo "$http_status $body_file"
}

resolve_control_plane_response() {
  local cp_name="$1"
  local encoded_name
  encoded_name="$(urlencode "$cp_name")"
  local response cp_lookup_status body_file
  response="$(konnect_api GET "${KONNECT_API_URL}/v2/control-planes?filter%5Bname%5D%5Beq%5D=${encoded_name}")"
  cp_lookup_status="${response%% *}"
  body_file="${response#* }"

  if [[ "$cp_lookup_status" != "200" ]]; then
    fail "Failed to resolve Konnect control plane id for '${cp_name}' (HTTP $cp_lookup_status)."
    cat "$body_file" >&2
    rm -f "$body_file"
    exit 1
  fi

  echo "$body_file"
}

create_control_plane() {
  local cp_name="$1"
  local body_file
  body_file="$(mktemp)"
  local http_status
  local encoded_name encoded_type
  encoded_name="$(urlencode "$cp_name")"
  encoded_type="$(urlencode "${KONNECT_CONTROL_PLANE_CLUSTER_TYPE}")"

  http_status="$(curl -sS -X POST "${KONNECT_API_URL}/v2/control-planes" \
    -H "Authorization: Bearer $KONNECT_TOKEN" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data "name=${encoded_name}&cluster_type=${encoded_type}" \
    -o "$body_file" \
    -w "%{http_code}")"

  if [[ "$http_status" != "200" && "$http_status" != "201" ]]; then
    fail "Failed to create Konnect control plane '${cp_name}' (HTTP $http_status)."
    cat "$body_file" >&2
    rm -f "$body_file"
    exit 1
  fi

  echo "$body_file"
}

ensure_control_plane() {
  local cp_name="$1"
  local body_file cp_id cp_display_name
  body_file="$(resolve_control_plane_response "$cp_name")"
  cp_id="$(jq -r '.data[0].id // empty' "$body_file")"
  cp_display_name="$(jq -r '.data[0].name // empty' "$body_file")"
  rm -f "$body_file"

  if [[ -n "$cp_id" ]]; then
    echo "$cp_display_name|$cp_id|existing"
    return
  fi

  info "Creating Konnect control plane '${cp_name}'"
  body_file="$(create_control_plane "$cp_name")"
  cp_id="$(jq -r '.id // empty' "$body_file")"
  cp_display_name="$(jq -r '.name // empty' "$body_file")"
  rm -f "$body_file"

  if [[ -z "$cp_id" || -z "$cp_display_name" ]]; then
    fail "Konnect control plane creation did not return a usable id/name for '${cp_name}'."
    exit 1
  fi

  echo "$cp_display_name|$cp_id|created"
}

run_optional_normal_demo() {
  local enabled="${RUN_NORMAL_DEMO_ON_START:-false}"
  case "${enabled:l}" in
    1|true|yes)
      ;;
    *)
      info "Skipping optional normal run (start with NORMAL_RUN to enable it)"
      return 0
      ;;
  esac

  local run_id="startup-normal-$(date +%Y%m%d%H%M%S)"
  local context_id="${run_id}-context"
  local payload response_file summary
  payload="$(jq -nc --arg run_id "$run_id" --arg context_id "$context_id" '{run_id: $run_id, context_id: $context_id, governance_scenario: "normal"}')"
  response_file="$(mktemp)"

  step "Running optional normal orchestration"
  if ! curl --fail-with-body --silent --show-error \
    --max-time "${RUN_NORMAL_DEMO_TIMEOUT_SECONDS:-240}" \
    -H "Content-Type: application/json" \
    -H "apikey: ${AIGW_ORCHESTRATOR_API_KEY:-orchestrator-demo-key}" \
    -H "x-demo-run-id: ${run_id}" \
    -H "x-demo-context-id: ${context_id}" \
    --data "$payload" \
    http://localhost:8000/orchestrator/play >"$response_file"; then
    fail "Optional normal run failed. The stack remains running; inspect the response below."
    cat "$response_file" >&2
    rm -f "$response_file"
    return 1
  fi

  summary="$(jq -r '.executive_brief.summary // .summary // "completed"' "$response_file")"
  rm -f "$response_file"
  ok "Normal run complete: ${run_id}"
  info "${summary}"
}

sync_plugin_schema() {
  local cp_id="$1"
  local plugin_name="$2"
  local schema_file="$3"
  local schema_payload
  schema_payload="$(jq -Rs '{lua_schema: .}' "$schema_file")"

  local base_url="${KONNECT_API_URL}/v2/control-planes/${cp_id}/core-entities/plugin-schemas"
  local check_response check_status check_body_file
  check_response="$(konnect_api GET "${base_url}/${plugin_name}")"
  check_status="${check_response%% *}"
  check_body_file="${check_response#* }"

  local method url verb
  case "$check_status" in
    200)
      method="PUT"
      url="${base_url}/${plugin_name}"
      verb="Updating"
      ;;
    404)
      method="POST"
      url="${base_url}"
      verb="Creating"
      ;;
    *)
      echo "Failed to inspect custom plugin schema '${plugin_name}' (HTTP $check_status)." >&2
      cat "$check_body_file" >&2
      rm -f "$check_body_file"
      exit 1
      ;;
  esac
  rm -f "$check_body_file"

  info "${verb} custom plugin schema '${plugin_name}' in Konnect"
  local write_response write_status write_body_file
  write_response="$(konnect_api "$method" "$url" "$schema_payload")"
  write_status="${write_response%% *}"
  write_body_file="${write_response#* }"

  case "$write_status" in
    200|201)
      rm -f "$write_body_file"
      wait_for_plugin_schema "$cp_id" "$plugin_name"
      ok "Custom plugin schema '${plugin_name}' synced"
      ;;
    *)
      fail "Failed to sync custom plugin schema '${plugin_name}' (HTTP $write_status)."
      cat "$write_body_file" >&2
      rm -f "$write_body_file"
      exit 1
      ;;
  esac
}

wait_for_plugin_schema() {
  local cp_id="$1"
  local plugin_name="$2"
  local base_url="${KONNECT_API_URL}/v2/control-planes/${cp_id}/core-entities/plugin-schemas"
  local attempt max_attempts sleep_seconds
  max_attempts="${KONNECT_PLUGIN_SCHEMA_WAIT_ATTEMPTS:-15}"
  sleep_seconds="${KONNECT_PLUGIN_SCHEMA_WAIT_SECONDS:-2}"

  for (( attempt = 1; attempt <= max_attempts; attempt++ )); do
    local check_response check_status check_body_file
    check_response="$(konnect_api GET "${base_url}/${plugin_name}")"
    check_status="${check_response%% *}"
    check_body_file="${check_response#* }"

    if [[ "$check_status" == "200" ]]; then
      rm -f "$check_body_file"
      return 0
    fi

    if [[ "$attempt" -lt "$max_attempts" ]]; then
      info "Waiting for Konnect to expose custom plugin schema '${plugin_name}' (${attempt}/${max_attempts})"
      rm -f "$check_body_file"
      sleep "$sleep_seconds"
      continue
    fi

    fail "Konnect did not expose custom plugin schema '${plugin_name}' after ${max_attempts} attempts."
    cat "$check_body_file" >&2
    rm -f "$check_body_file"
    exit 1
  done
}

sync_all_plugin_schemas() {
  local cp_id="$1"
  local schema_files plugin_name schema_file
  schema_files=(kong/plugins/*/schema.lua(N))

  if [[ "${#schema_files[@]}" -eq 0 ]]; then
    fail "No custom plugin schemas found under kong/plugins/*/schema.lua"
    exit 1
  fi

  for schema_file in "${schema_files[@]}"; do
    plugin_name="$(basename "$(dirname "$schema_file")")"
    sync_plugin_schema "$cp_id" "$plugin_name" "$schema_file"
  done
}

if [[ ! -f .env ]]; then
  fail ".env not found in $ROOT_DIR"
  exit 1
fi

require_bin curl
require_bin jq
require_bin python3
require_bin deck
require_bin kongctl

set -a
source .env
set +a

source "${ROOT_DIR}/scripts/resolve_embeddings_env.sh"

if [[ -z "${KONNECT_TOKEN:-}" ]]; then
  fail "KONNECT_TOKEN is not set in .env"
  exit 1
fi

if [[ -z "${KONNECT_SYSTEM_TOKEN:-}" ]]; then
  fail "KONNECT_SYSTEM_TOKEN is required for AI Gateway Metering & Billing"
  exit 1
fi

export AIGW_GATEWAY_ID="${AIGW_GATEWAY_ID:-47e9610a-2ad8-4b19-98d3-2b5364a7f38f}"
export KONNECT_METERING_INGEST_ENDPOINT="${KONNECT_METERING_INGEST_ENDPOINT:-https://us.api.konghq.com/v3/openmeter/events}"
export AIGW_OPENAI_AUTHORIZATION="${AIGW_OPENAI_AUTHORIZATION:-Bearer ${DECK_OPENAI_API_KEY}}"
export AIGW_GEMINI_API_KEY="${AIGW_GEMINI_API_KEY:-${DECK_GEMINI_API_KEY}}"

KONNECT_API_URL="${KONNECT_API_URL:-https://us.api.konghq.com}"
KONNECT_CONTROL_PLANE_NAME="${KONNECT_CONTROL_PLANE_NAME:-AA Demo}"
KONNECT_CONTROL_PLANE_CLUSTER_TYPE="${KONNECT_CONTROL_PLANE_CLUSTER_TYPE:-CLUSTER_TYPE_HYBRID}"

echo
echo "${CYAN}========================================${RESET}"
echo "${BOLD}${GREEN}           Demo Startup${RESET}"
echo "${CYAN}========================================${RESET}"

step "Starting local stack with Opik"
docker compose --profile opik up -d --build 
ok "Docker services are up"

step "Ensuring Konnect control plane"
CONTROL_PLANE_INFO="$(ensure_control_plane "${KONNECT_CONTROL_PLANE_NAME}")"
CONTROL_PLANE_NAME_RESOLVED="${CONTROL_PLANE_INFO%%|*}"
CONTROL_PLANE_INFO_REMAINDER="${CONTROL_PLANE_INFO#*|}"
CONTROL_PLANE_ID="${CONTROL_PLANE_INFO_REMAINDER%%|*}"
CONTROL_PLANE_STATUS="${CONTROL_PLANE_INFO_REMAINDER##*|}"
KONNECT_CONTROL_PLANE_NAME="${CONTROL_PLANE_NAME_RESOLVED}"
ok "Using control plane '${KONNECT_CONTROL_PLANE_NAME}'"
info "Control plane id: ${CONTROL_PLANE_ID}"
if [[ "${CONTROL_PLANE_STATUS}" == "created" ]]; then
  ok "Konnect control plane created"
else
  info "Konnect control plane already existed"
fi

step "Syncing custom plugin schemas"
sync_all_plugin_schemas "$CONTROL_PLANE_ID"

step "Syncing Kong configuration"
deck gateway sync \
  --konnect-token "$KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONNECT_CONTROL_PLANE_NAME" \
  kong/deck/kong.yaml
ok "decK sync complete"

step "Syncing AI Gateway 2.0 entities"
kongctl diff -f kongctl/ai-gateway --mode apply
kongctl apply --auto-approve -f kongctl/ai-gateway
ok "AI Gateway 2.0 entities synced to AA-Demo-2"

step "Registering AI Builder Catalog Models and MCP Servers"
python3 scripts/register_ai_builder_catalog.py
ok "AI Builder Catalog records linked to AA-Demo-2"

step "Creating agent token-metering and billing catalog"
python3 scripts/setup_ai_gateway_metering_billing.py
ok "Agent billing customers and subscriptions are ready"

step "Uploading Konnect observability dashboards"
python3 scripts/upload_konnect_dashboards.py \
  --control-plane-id "$CONTROL_PLANE_ID" \
  --pat "$KONNECT_TOKEN" \
  --server-url "$KONNECT_API_URL"
ok "Konnect dashboards synced"

step "Registering Konnect MCP Registry"
python3 scripts/register_konnect_mcp_registry.py
ok "Konnect MCP registry synced"

step "Ingesting fictional AtlasFlow support KB"
python3 scripts/ingest_rag_kb.py
ok "RAG knowledge base ingested"

run_optional_normal_demo

echo
echo "${CYAN}========================================${RESET}"
echo "${BOLD}${GREEN}        Demo Startup Complete${RESET}"
echo "${CYAN}========================================${RESET}"
echo
echo "${BOLD}URLs:${RESET}"
printf "  ${CYAN}UI${RESET}       %s\n" "$(link "http://localhost:8000" "http://localhost:8000")"
printf "  ${CYAN}Grafana${RESET}  %s\n" "$(link "http://localhost:3001" "http://localhost:3001")"
printf "  ${CYAN}Opik${RESET}     %s\n" "$(link "http://localhost:5173" "http://localhost:5173")"
printf "  ${CYAN}Jaeger${RESET}   %s\n" "$(link "http://localhost:16686" "http://localhost:16686")"
echo
echo "${BOLD}Konnect MCP Registry:${RESET}"
printf "  ${CYAN}Registry${RESET}  %s\n" "AA Demo MCP Registry"
printf "  ${CYAN}Server${RESET}    %s\n" "com.aa-demo/mock-mcp"
printf "  ${CYAN}Remote${RESET}    %s\n" "http://host.docker.internal:8002/mock-mcp"
echo
