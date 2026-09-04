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

## Validação completa

No Windows, execute `test.bat`.

No CI/Linux:

```bash
python acceptance/run_release1_acceptance.py
cd frontend && npm install && npm run build && cd ..
python scripts/verify_release2.py
python -m pytest backend/tests/test_integrations.py -v
python scripts/verify_release3.py
```

## Integrações — Release 3

### QRZ

O sistema gera um plano/dry-run completo por UUID e exige um localizador exato `CALL + QSO_DATE + TIME_ON`. Ambiguidade ou ausência de `TIME_ON` aborta o plano.

A escrita real no QRZ permanece **fail-closed** nesta versão: o endpoint de apply retorna bloqueio e não executa rede. Isso evita que uma credencial, flag ou clique acidental transforme um preview em alteração real. Um transporte QRZ real deve ser validado separadamente com backup, operação de um único registro e re-FETCH de confirmação antes de ser liberado.

### WRL UDP

O bridge WRL usa por padrão `127.0.0.1:2237` e aceita somente `localhost`/endereços loopback. Destinos LAN/Internet são rejeitados. `dry_run=true` não abre socket. Envio UDP real exige `WRL_UDP_ENABLED=true` explicitamente.

Variáveis disponíveis em `.env`:

```env
QRZ_API_KEY=
QRZ_USERNAME=
QRZ_DRY_RUN=true
QRZ_WRITE_ENABLED=false

WRL_UDP_HOST=127.0.0.1
WRL_UDP_PORT=2237
WRL_UDP_ENABLED=false
```

## Segurança operacional

- Upload manual usa `PARTIAL_EXPORT` por padrão.
- Ausência em export parcial não é tratada como prova de QSO faltante.
- Atualizações manuais são aplicadas por UUID e persistidas contra a identidade estável do QSO.
- Resoluções de divergência sobrevivem a novas reconciliações.
- QRZ real não é habilitado implicitamente nem pela presença de credenciais.
- WRL UDP real é restrito a loopback e exige enable explícito.
- `test.bat` valida novamente o núcleo, frontend e integrações.

## Arquitetura

`RawQSO -> NormalizedQSO -> QSOIdentity -> LogicalQSO -> QSOSourceLink`

O `LogicalQSO` é uma visão materializada. Overrides e resoluções humanas pertencem à `QSOIdentity` persistente.
