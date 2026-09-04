# Release 2 — Local App

## Resultado

Release 2 validado no GitHub Actions.

- frontend React/Vite compilado com sucesso;
- suíte imutável do Release 1 executada novamente sem regressões;
- verificação de integração Release 2 aprovada;
- FastAPI serve o build React e o fallback SPA;
- endpoints usados pela UI respondem no smoke test;
- scripts Windows `setup.ps1`, `start.bat` e `test.bat` incluídos.

## Interface entregue

- Visão geral;
- Importação ADIF e reconciliação;
- Consulta e filtro de QSOs;
- edição segura por UUID com override persistente;
- resolução persistente de divergências;
- backups JSON/ADIF;
- auditoria;
- diagnóstico do sistema.

## Limites deste release

Integrações externas reais ainda ficam bloqueadas. QRZ seguro/dry-run, UDP local e diagnóstico de integrações pertencem ao Release 3.
