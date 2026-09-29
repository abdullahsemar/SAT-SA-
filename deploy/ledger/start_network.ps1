# PowerShell startup script for local Hyperledger Fabric network
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "=== SAT-SA Permissioned Blockchain Network Initialization ===" -ForegroundColor Cyan

# Check Docker availability
try {
    docker info | Out-Null
} catch {
    Write-Warning "Docker daemon is not accessible. Please ensure Docker Desktop is started with admin privileges."
    exit 1
}

Write-Host "[1/4] Checking cryptographic certificates..." -ForegroundColor Green
if (-not (Test-Path "crypto-config")) {
    Write-Host "Generating crypto-config via containerized cryptogen..."
    docker run --rm -v "${ScriptDir}:/work" -w /work hyperledger/fabric-tools:2.5.9 cryptogen generate --config=crypto-config.yaml --output=crypto-config
}

Write-Host "[2/4] Starting Fabric orderer and peer containers..." -ForegroundColor Green
docker compose -f docker-compose.yaml up -d

Write-Host "[3/4] Waiting for container initialization..." -ForegroundColor Green
Start-Sleep -Seconds 5

Write-Host "[4/4] Verifying network status..." -ForegroundColor Green
docker compose -f docker-compose.yaml ps

Write-Host "=== Fabric Network Ready on Loopback (sat-sa-channel) ===" -ForegroundColor Cyan
