@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Environment missing. Run: powershell -ExecutionPolicy Bypass -File setup-local.ps1
  pause
  exit /b 1
)
set "APPDATA=%~dp0.local\appdata"
set "PYTHONUTF8=1"
if not exist "%APPDATA%" mkdir "%APPDATA%"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m pet %*
