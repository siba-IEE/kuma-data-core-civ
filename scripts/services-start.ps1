# =============================================================================
# services-start.ps1
#
# Démarre l'environnement Docker local de Kuma Data Core (PostgreSQL + Redis).
#
# Étapes :
#   1. Vérifie que le démon Docker est joignable (docker info).
#   2. Vérifie qu'un fichier .env existe à la racine du dépôt.
#      Si absent, copie docker/.env.example vers .env et exit 1
#      (l'utilisateur doit remplacer les mots de passe avant tout démarrage).
#   3. Lance docker compose up -d.
#   4. Affiche un récapitulatif (URL PostgreSQL sans mot de passe, port Redis).
#
# Usage : .\scripts\services-start.ps1 (depuis la racine du dépôt ou ailleurs)
# =============================================================================

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Se replace à la racine du dépôt quel que soit le CWD de l'utilisateur.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$ComposeFile = Join-Path $RepoRoot 'docker/docker-compose.yml'
$EnvFile     = Join-Path $RepoRoot '.env'
$EnvExample  = Join-Path $RepoRoot 'docker/.env.example'

# 1. Vérification du démon Docker.
Write-Host "Vérification du démon Docker..." -ForegroundColor Cyan
try {
    docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker info a échoué (code $LASTEXITCODE)." }
} catch {
    Write-Host "Docker ne répond pas. Démarrez Docker Desktop puis réessayez." -ForegroundColor Red
    exit 1
}
Write-Host "Démon Docker joignable." -ForegroundColor Green

# 2. Vérification du fichier .env.
if (-not (Test-Path $EnvFile)) {
    Write-Host "Aucun fichier .env trouvé à la racine." -ForegroundColor Yellow
    if (-not (Test-Path $EnvExample)) {
        Write-Host "Modèle docker/.env.example introuvable. Dépôt incomplet ?" -ForegroundColor Red
        exit 1
    }
    Copy-Item $EnvExample $EnvFile
    Write-Host "Fichier .env créé à partir de docker/.env.example." -ForegroundColor Yellow
    Write-Host "Modifiez les mots de passe (champs changeme_*) avant de relancer ce script." -ForegroundColor Yellow
    exit 1
}
Write-Host "Fichier .env présent." -ForegroundColor Green

# 3. Démarrage des services.
Write-Host "Démarrage des conteneurs (postgres, redis)..." -ForegroundColor Cyan
docker compose -f $ComposeFile --env-file $EnvFile up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "Échec du démarrage des services (code $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

# 4. Récapitulatif.
Write-Host ""
Write-Host "Services démarrés." -ForegroundColor Green
Write-Host "  PostgreSQL : 127.0.0.1:5432 (utilisateur et base définis dans .env)"
Write-Host "  Redis      : 127.0.0.1:6379 (mot de passe requis)"
Write-Host ""
Write-Host "État détaillé : .\scripts\services-status.ps1"
Write-Host "Arrêt         : .\scripts\services-stop.ps1"
