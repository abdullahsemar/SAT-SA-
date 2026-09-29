#!/usr/bin/env bash
# Teardown script for local Hyperledger Fabric network
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Stopping SAT-SA Fabric Network ==="
docker compose -f docker-compose.yaml down -v --remove-orphans
echo "Network stopped."
