# PU2BRU QSO Manager

Aplicação local para importar, reconciliar, revisar e auditar QSOs de múltiplas fontes com foco em evitar falsos "faltantes".

## Windows 11 — primeira execução

1. Instale Python 3.12+ e Node.js 22+.
2. Abra PowerShell na pasta do projeto.
3. Execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

4. Depois execute `start.bat`.

O navegador abrirá em `http://127.0.0.1:8000`.

## Uso normal

Depois do setup, basta executar `start.bat`. O backend FastAPI serve a interface React compilada e usa SQLite local em `backend/data/qso_manager.db`.

## Validação

No Windows, execute `test.bat`.

No CI/Linux:

```bash
python acceptance/run_release1_acceptance.py
cd frontend && npm install && npm run build && cd ..
python scripts/verify_release2.py
```

## Segurança operacional

- Upload manual usa `PARTIAL_EXPORT` por padrão.
- Ausência em export parcial não é tratada como prova de QSO faltante.
- Atualizações manuais são aplicadas por UUID e persistidas contra a identidade estável do QSO.
- Resoluções de divergência sobrevivem a novas reconciliações.
- Escrita real no QRZ não é automática nem habilitada por padrão.
- UDP real é restrito a destinos locais no Release 3.

## Arquitetura

`RawQSO -> NormalizedQSO -> QSOIdentity -> LogicalQSO -> QSOSourceLink`

O `LogicalQSO` é uma visão materializada. Overrides e resoluções humanas pertencem à `QSOIdentity` persistente.
