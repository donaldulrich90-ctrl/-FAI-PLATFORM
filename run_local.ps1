# Lancement local sans Docker : venv, dependances, migrations, runserver.
# Par defaut : SQLite (fichier db.sqlite3), pour eviter les erreurs Postgres sur Windows.
param(
    [switch]$Sqlite,
    [switch]$Postgres,
    [switch]$SkipDeps,
    [switch]$SkipMigrate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

. (Join-Path $ProjectRoot "scripts\start-helpers.ps1")

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv
        Assert-LastNativeExitCode "creation du venv (py -3 -m venv)"
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
        Assert-LastNativeExitCode "creation du venv (python -m venv)"
    } else {
        throw "Python 3 introuvable. Installez-le depuis https://www.python.org/ ou utilisez Docker (Demarrer.bat)."
    }
    if (-not (Test-Path $venvPython)) {
        throw "Impossible de creer l'environnement virtuel .venv"
    }
}

if ($Postgres -and $Sqlite) {
    throw "run_local : utilisez soit -Postgres soit -Sqlite, pas les deux."
}
if ($Postgres) {
    Remove-Item Env:USE_SQLITE -ErrorAction SilentlyContinue
    Write-Host "[run_local] Base de donnees : PostgreSQL ($env:POSTGRES_HOST / $env:POSTGRES_DB)" -ForegroundColor DarkCyan
} else {
    $env:USE_SQLITE = "1"
    Write-Host "[run_local] Base de donnees : SQLite (db.sqlite3)" -ForegroundColor DarkCyan
}

if (-not $SkipDeps) {
    Write-Host "[run_local] Installation des dependances (pip)..." -ForegroundColor DarkCyan
    & $venvPython -m pip install -r requirements.txt
    Assert-LastNativeExitCode "pip install -r requirements.txt"

    & $venvPython scripts/patch_django_python314.py
    Assert-LastNativeExitCode "scripts/patch_django_python314.py"
}

if (-not $env:POSTGRES_HOST) { $env:POSTGRES_HOST = "127.0.0.1" }
if (-not $env:DJANGO_SECRET_KEY) { $env:DJANGO_SECRET_KEY = "dev-local-only" }
if (-not $env:DJANGO_DEBUG) { $env:DJANGO_DEBUG = "1" }
if (-not $env:DJANGO_ALLOWED_HOSTS) { $env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1" }

if (-not $SkipMigrate) {
    Write-Host "[run_local] Migrations..." -ForegroundColor DarkCyan
    & $venvPython manage.py migrate --noinput
    Assert-LastNativeExitCode "manage.py migrate"
} else {
    Write-Host "[run_local] Migrations ignorees (-SkipMigrate)." -ForegroundColor DarkYellow
}

Write-Host "[run_local] Serveur : http://127.0.0.1:8000/ (Ctrl+C pour arreter)" -ForegroundColor Green
& $venvPython manage.py runserver 0.0.0.0:8000
exit $LASTEXITCODE
