@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Environment missing. Run: powershell -ExecutionPolicy Bypass -File setup-local.ps1
  pause
  exit /b 1
)
set "APPDATA=%~dp0.local\appdata"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
if not exist "%APPDATA%" mkdir "%APPDATA%"
"%~dp0.venv\Scripts\python.exe" -m pet %*
if errorlevel 1 (
  echo Startup failed. See the output above and .local\appdata\dsh-pet-standalone\pet-*.log.
  pause
  exit /b 1
)
