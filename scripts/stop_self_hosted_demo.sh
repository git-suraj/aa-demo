#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$#" -gt 1 ]] || [[ "$#" -eq 1 && "$1" != "--volumes" ]]; then
  echo "Usage: $0 [--volumes]" >&2
  exit 2
fi

if [[ "${1:-}" == "--volumes" ]]; then
  echo "Stopping the self-hosted demo and removing Docker volumes."
  echo "The next start will create a fresh Kong database and resync configuration."
  docker compose --profile opik down --volumes
else
  echo "Stopping the self-hosted demo. Docker volumes are preserved."
  docker compose --profile opik down
fi
