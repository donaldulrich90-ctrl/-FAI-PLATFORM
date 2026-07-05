# Fonctions partagées pour le démarrage (PowerShell 5.1 et7+).
# Ne pas exécuter seul : source depuis Demarrer.ps1 via . (Join-Path ... 'start-helpers.ps1')

function Test-DockerComposeUsable {
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $false
    }
    docker compose version 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-DemarrerUsage {
    @'
Faso ISP Manager - demarrage

  .\Demarrer.ps1              Docker si disponible, sinon Python local
  .\Demarrer.ps1 -Local       Ignorer Docker, Python local (SQLite par defaut)
  .\Demarrer.ps1 -Local -Postgres   Python local avec PostgreSQL (.env / variables)
  .\Demarrer.ps1 -Sqlite      Idem que local par defaut (SQLite explicite)
  .\Demarrer.ps1 -Help        Cette aide

  .\run_local.ps1             Python local : SQLite (db.sqlite3) par defaut
  .\run_local.ps1 -Postgres   Utiliser PostgreSQL (serveur doit tourner, mots de passe dans .env)
  .\run_local.ps1 -SkipDeps   Ne pas reinstaller pip / patch (dev avance)
  .\run_local.ps1 -SkipMigrate   Ne pas executer migrate

Double-clic : Demarrer.bat (Docker si installe, sinon SQLite local)
Serveur local rapide : run.bat
'@
}

function Assert-LastNativeExitCode {
    param([string]$StepLabel = "etape")
    if ($LASTEXITCODE -ne 0) {
        throw "Echec : $StepLabel (code sortie $LASTEXITCODE)"
    }
}
