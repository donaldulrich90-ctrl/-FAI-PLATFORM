@echo off
REM Point d'entree Windows : delegue a Demarrer.ps1 (Docker ou Python local).
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Demarrer.ps1" %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo Echec du demarrage (code %ERR%).
  pause
)
exit /b %ERR%
