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

require_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

step() {
  printf "\n[%s] %s\n" "$(date +%H:%M:%S)" "$1"
}

if [[ ! -f .env ]]; then
  echo ".env not found in $ROOT_DIR (copy .env.example first)" >&2
  exit 1
fi

require_bin docker
require_bin deck
require_bin curl
require_bin python3

set -a
source .env
set +a
source "$ROOT_DIR/scripts/resolve_embeddings_env.sh"

if [[ -z "${KONG_LICENSE_DATA:-}" ]]; then
  echo "KONG_LICENSE_DATA is required for this Enterprise deployment; add the one-line license JSON to .env." >&2
  exit 1
fi

step "Generating the local hybrid cluster certificate"
"$ROOT_DIR/scripts/generate_hybrid_certs.sh"

step "Starting the self-hosted control plane, data plane, and demo services"
docker compose --profile opik up -d --build --remove-orphans

step "Waiting for the local Kong Admin API"
until curl --fail --silent http://localhost:8001/status >/dev/null; do
  sleep 2
done

step "Syncing self-hosted Gateway primitives converted from AI Gateway entities"
deck gateway sync --kong-addr http://localhost:8001 kong/deck/kong.yaml

step "Ingesting fictional AtlasFlow support KB"
python3 scripts/ingest_rag_kb.py

if [[ "${RUN_NORMAL_DEMO_ON_START:-false}" == "true" ]]; then
  step "Running optional normal orchestration"
  curl --fail-with-body --silent --show-error \
    --max-time "${RUN_NORMAL_DEMO_TIMEOUT_SECONDS:-240}" \
    -H "Content-Type: application/json" \
    -H "apikey: ${AIGW_ORCHESTRATOR_API_KEY:-orchestrator-demo-key}" \
    --data '{"governance_scenario":"normal"}' \
    http://localhost:8000/orchestrator/play
  echo
fi

echo
echo "Self-hosted demo is ready."
echo "  UI:      http://localhost:8000"
echo "  Admin:   http://localhost:8001"
echo "  Manager: http://localhost:8002"
echo "  Grafana: http://localhost:3001"
