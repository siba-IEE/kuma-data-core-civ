# =============================================================================
# services-status.ps1
#
# Affiche l'état des services Docker locaux de Kuma Data Core.
#
# Affiche :
#   - La sortie brute de docker compose ps (services, état, ports).
#   - Un récapitulatif lisible : pour chaque service, son statut et son
#     état de healthcheck (healthy / unhealthy / starting / inconnu).
#
# Usage : .\scripts\services-status.ps1
# =============================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$ComposeFile = Join-Path $RepoRoot 'docker/docker-compose.yml'
$EnvFile     = Join-Path $RepoRoot '.env'

if (-not (Test-Path $EnvFile)) {
    Write-Host "Fichier .env introuvable. Lancez d'abord .\scripts\services-start.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "État brut (docker compose ps) :" -ForegroundColor Cyan
docker compose -f $ComposeFile --env-file $EnvFile ps
if ($LASTEXITCODE -ne 0) {
    Write-Host "Échec de la commande docker compose ps (code $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Récapitulatif :" -ForegroundColor Cyan

$Services = @('kuma-postgres', 'kuma-redis')
foreach ($name in $Services) {
    $exists = docker ps -a --filter "name=^/$name$" --format '{{.Names}}'
    if (-not $exists) {
        Write-Host ("  {0,-16} : non créé" -f $name) -ForegroundColor Yellow
        continue
    }
    $state  = docker inspect -f '{{.State.Status}}' $name 2>$null
    $health = docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' $name 2>$null

    $color = 'Yellow'
    if ($state -eq 'running' -and ($health -eq 'healthy' -or $health -eq 'n/a')) { $color = 'Green' }
    elseif ($state -eq 'exited' -or $health -eq 'unhealthy') { $color = 'Red' }

    Write-Host ("  {0,-16} : état={1,-10} santé={2}" -f $name, $state, $health) -ForegroundColor $color
}
