# PowerShell teardown script for local Hyperledger Fabric network
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "=== Stopping SAT-SA Fabric Network ===" -ForegroundColor Yellow
docker compose -f docker-compose.yaml down -v --remove-orphans
Write-Host "Network stopped." -ForegroundColor Green
