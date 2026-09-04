@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Ambiente nao configurado. Executando setup.ps1...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo Frontend nao compilado. Executando setup.ps1...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 exit /b 1
)

if not exist "backend\data" mkdir "backend\data"
start "" http://127.0.0.1:8000
cd /d "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
