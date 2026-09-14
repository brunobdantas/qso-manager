@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Execute setup.ps1 primeiro.
  exit /b 1
)

echo === Backend regression suite ===
".venv\Scripts\python.exe" -m pytest backend\tests -q
if errorlevel 1 exit /b 1

echo === Core acceptance ===
".venv\Scripts\python.exe" acceptance\run_release1_acceptance.py
if errorlevel 1 exit /b 1

echo === Desktop verification ===
".venv\Scripts\python.exe" scripts\verify_release2.py
if errorlevel 1 exit /b 1

echo === Integration verification ===
".venv\Scripts\python.exe" scripts\verify_release3.py
if errorlevel 1 exit /b 1

echo === Product capability contract ===
".venv\Scripts\python.exe" scripts\verify_product_parity.py
if errorlevel 1 exit /b 1

echo === Production gate ===
".venv\Scripts\python.exe" scripts\verify_production.py
if errorlevel 1 exit /b 1

echo.
echo Todos os testes locais passaram.
