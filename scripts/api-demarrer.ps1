# =============================================================================
# api-demarrer.ps1
#
# Démarre l'API Kuma Data Core en mode développement avec rechargement
# automatique (uvicorn --reload).
#
# Pré-requis :
#   - Docker Compose en marche (.\scripts\services-start.ps1)
#   - Migrations appliquées (uv run alembic upgrade head)
#   - Fichier .env complet avec API_CLE_SOLAR_BRIDGE et API_CLE_ADMIN
#
# Usage : .\scripts\api-demarrer.ps1
# =============================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path (Join-Path $RepoRoot '.env'))) {
    Write-Host "Fichier .env introuvable à la racine." -ForegroundColor Red
    Write-Host "Lancez d'abord .\scripts\services-start.ps1 pour le générer," -ForegroundColor Yellow
    Write-Host "puis renseignez les variables API_CLE_* avant de relancer ce script." -ForegroundColor Yellow
    exit 1
}

Write-Host "Démarrage de l'API Kuma Data Core (mode dev, rechargement actif)..." -ForegroundColor Cyan
Write-Host "  URL          : http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  Documentation: http://127.0.0.1:8000/docs (si API_DOCS_ACTIVES=true)" -ForegroundColor Cyan
Write-Host ""

uv run uvicorn kuma_data_core.api.main:app --reload --host 127.0.0.1 --port 8000
