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

resolve_control_plane_id() {
  local encoded_name
  encoded_name="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$KONNECT_CONTROL_PLANE_NAME")"
  local response cp_lookup_status body_file
  response="$(konnect_api GET "${KONNECT_API_URL}/v2/control-planes?filter%5Bname%5D%5Beq%5D=${encoded_name}")"
  cp_lookup_status="${response%% *}"
  body_file="${response#* }"

  if [[ "$cp_lookup_status" != "200" ]]; then
    fail "Failed to resolve Konnect control plane id for '${KONNECT_CONTROL_PLANE_NAME}' (HTTP $cp_lookup_status)."
    cat "$body_file" >&2
    rm -f "$body_file"
    exit 1
  fi

  local cp_id
  cp_id="$(jq -r '.data[0].id // empty' "$body_file")"
  rm -f "$body_file"

  if [[ -z "$cp_id" ]]; then
    fail "No Konnect control plane found for '${KONNECT_CONTROL_PLANE_NAME}'."
    exit 1
  fi

  echo "$cp_id"
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

if [[ ! -f .env ]]; then
  fail ".env not found in $ROOT_DIR"
  exit 1
fi

require_bin curl
require_bin jq
require_bin python3
require_bin deck

set -a
source .env
set +a

if [[ -z "${KONNECT_TOKEN:-}" || -z "${KONNECT_CONTROL_PLANE_NAME:-}" ]]; then
  fail "KONNECT_TOKEN or KONNECT_CONTROL_PLANE_NAME is not set in .env"
  exit 1
fi

KONNECT_API_URL="${KONNECT_API_URL:-https://us.api.konghq.com}"

echo
echo "${CYAN}========================================${RESET}"
echo "${BOLD}${GREEN}           Demo Startup${RESET}"
echo "${CYAN}========================================${RESET}"

step "Starting local stack with Opik"
docker compose --profile opik up -d --build 
ok "Docker services are up"

step "Resolving Konnect control plane"
CONTROL_PLANE_ID="$(resolve_control_plane_id)"
ok "Using control plane '${KONNECT_CONTROL_PLANE_NAME}'"
info "Control plane id: ${CONTROL_PLANE_ID}"

step "Syncing custom plugin schemas"
sync_plugin_schema "$CONTROL_PLANE_ID" "prompt-capture" "kong/plugins/prompt-capture/schema.lua"
sync_plugin_schema "$CONTROL_PLANE_ID" "trace-enricher" "kong/plugins/trace-enricher/schema.lua"
sync_plugin_schema "$CONTROL_PLANE_ID" "workflow-graph" "kong/plugins/workflow-graph/schema.lua"

step "Syncing Kong configuration"
deck gateway sync \
  --konnect-token "$KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONNECT_CONTROL_PLANE_NAME" \
  kong/deck/kong.yaml
ok "decK sync complete"

step "Uploading Konnect observability dashboards"
python3 scripts/upload_konnect_dashboards.py \
  --control-plane-id "$CONTROL_PLANE_ID" \
  --pat "$KONNECT_TOKEN" \
  --server-url "$KONNECT_API_URL"
ok "Konnect dashboards synced"

step "Ingesting fictional AtlasFlow support KB"
python3 scripts/ingest_rag_kb.py
ok "RAG knowledge base ingested"

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
