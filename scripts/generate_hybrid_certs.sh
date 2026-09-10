#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CERT_DIR="$ROOT_DIR/kong/onprem/certs"

if [[ -f "$CERT_DIR/cluster.crt" && -f "$CERT_DIR/cluster.key" ]]; then
  echo "Hybrid cluster certificate already exists: $CERT_DIR"
  exit 0
fi

mkdir -p "$CERT_DIR"
docker run --rm \
  -v "$CERT_DIR:/certs" \
  -w /certs \
  kong/kong-gateway:3.14.0.6 \
  kong hybrid gen_cert

echo "Generated shared hybrid certificate: $CERT_DIR"
