# =============================================================================
# services-stop.ps1
#
# Arrête l'environnement Docker local de Kuma Data Core.
#
# Comportement :
#   - Lance docker compose down (sans -v).
#   - Les volumes nommés (kuma_postgres_data, kuma_redis_data) sont préservés :
#     les données survivent à l'arrêt.
#   - Pour effacer les volumes : docker compose -f docker/docker-compose.yml down -v
#     (opération destructive, à utiliser en connaissance de cause).
#
# Usage : .\scripts\services-stop.ps1
# =============================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$ComposeFile = Join-Path $RepoRoot 'docker/docker-compose.yml'
$EnvFile     = Join-Path $RepoRoot '.env'

if (-not (Test-Path $EnvFile)) {
    Write-Host "Fichier .env introuvable. Les services n'ont probablement jamais été démarrés." -ForegroundColor Yellow
    Write-Host "Tentative d'arrêt sans .env..." -ForegroundColor Yellow
    docker compose -f $ComposeFile down
    exit $LASTEXITCODE
}

Write-Host "Arrêt des conteneurs Kuma..." -ForegroundColor Cyan
docker compose -f $ComposeFile --env-file $EnvFile down
if ($LASTEXITCODE -ne 0) {
    Write-Host "Échec de l'arrêt (code $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Services arrêtés. Les volumes de données sont conservés." -ForegroundColor Green
