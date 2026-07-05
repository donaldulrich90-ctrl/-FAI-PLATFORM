@echo off
REM Python local uniquement (pas Docker). Meme logique que run_local.ps1.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1" %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo Echec (code %ERR%). Astuce : Demarrer.bat pour la stack Docker complete.
  pause
)
exit /b %ERR%
