#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

RESET=$'\033[0m'
BOLD=$'\033[1m'
CYAN=$'\033[36m'
GREEN=$'\033[32m'
BLUE=$'\033[34m'

step() {
  local label="$1"
  printf "\n${BLUE}${BOLD}[%s]${RESET} %s\n" "$(date +%H:%M:%S)" "$label"
}

ok() {
  local message="$1"
  printf "${GREEN}  ✓${RESET} %s\n" "$message"
}

echo
echo "${CYAN}========================================${RESET}"
echo "${BOLD}${CYAN}            RAG Demo Shutdown${RESET}"
echo "${CYAN}========================================${RESET}"

step "Stopping local stack and removing Opik volumes"
docker compose --profile opik down -v
ok "Docker services stopped and volumes removed"

echo
echo "${CYAN}========================================${RESET}"
echo "${BOLD}${GREEN}         RAG Demo Shutdown Complete${RESET}"
echo "${CYAN}========================================${RESET}"
echo
