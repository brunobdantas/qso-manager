$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host '=== PU2BRU QSO Manager - Setup ===' -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw 'Python 3.12+ nao encontrado no PATH.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw 'Node.js/NPM nao encontrado no PATH.'
}

if (-not (Test-Path '.venv')) {
  python -m venv .venv
}

& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
& '.\.venv\Scripts\python.exe' -m pip install -r '.\backend\requirements.txt'

Push-Location '.\frontend'
npm install
npm run build
Pop-Location

New-Item -ItemType Directory -Force -Path '.\backend\data' | Out-Null
New-Item -ItemType Directory -Force -Path '.\backups' | Out-Null
New-Item -ItemType Directory -Force -Path '.\imports' | Out-Null
New-Item -ItemType Directory -Force -Path '.\exports' | Out-Null
New-Item -ItemType Directory -Force -Path '.\logs' | Out-Null

Write-Host ''
Write-Host 'Setup concluido.' -ForegroundColor Green
Write-Host 'Agora execute start.bat.' -ForegroundColor Green
