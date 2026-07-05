# Point d'entree principal : Docker (stack complete) ou Python local.
param(
    [switch]$Sqlite,
    [switch]$Postgres,
    [switch]$Local,
    [switch]$Help
)

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

. (Join-Path $ProjectRoot "scripts\start-helpers.ps1")

if ($Help) {
    Write-Host (Get-DemarrerUsage)
    exit 0
}

$useDocker = (-not $Local) -and (Test-DockerComposeUsable)

if ($useDocker) {
    Write-Host "[Demarrer] Docker disponible - lancement de la stack (code monte depuis ce dossier)..." -ForegroundColor Cyan
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
    exit $LASTEXITCODE
}

Write-Host "[Demarrer] Mode Python local (Docker ignore ou -Local)..." -ForegroundColor Yellow
if ($Postgres -and $Sqlite) {
    Write-Host "[Demarrer] Erreur : -Postgres et -Sqlite sont incompatibles." -ForegroundColor Red
    exit 1
}
$localArgs = @{}
if ($Postgres) { $localArgs.Postgres = $true }
elseif ($Sqlite) { $localArgs.Sqlite = $true }
try {
    & (Join-Path $ProjectRoot "run_local.ps1") @localArgs
    exit $LASTEXITCODE
} catch {
    Write-Host ('[Demarrer] Erreur : ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
