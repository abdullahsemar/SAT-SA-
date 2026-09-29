#!/usr/bin/env bash
# Startup script for local Hyperledger Fabric permissioned network
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== SAT-SA Permissioned Blockchain Network Initialization ==="

# Check Docker availability
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not accessible. Please ensure Docker is running."
    exit 1
fi

echo "[1/4] Generating cryptographic material (if not present)..."
if [ ! -d "crypto-config" ]; then
    echo "Generating certificates using cryptogen..."
    docker run --rm -v "$SCRIPT_DIR:/work" -w /work hyperledger/fabric-tools:2.5.9 cryptogen generate --config=crypto-config.yaml --output=crypto-config
fi

echo "[2/4] Starting Fabric orderer and peer containers..."
docker compose -f docker-compose.yaml up -d

echo "[3/4] Waiting for peer nodes to become healthy..."
sleep 5

echo "[4/4] Verifying network status..."
docker compose -f docker-compose.yaml ps

echo "=== Fabric Network Ready on Loopback (sat-sa-channel) ==="
