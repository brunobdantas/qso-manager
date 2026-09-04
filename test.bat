@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Execute setup.ps1 primeiro.
  exit /b 1
)
".venv\Scripts\python.exe" acceptance\run_release1_acceptance.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\verify_release2.py
