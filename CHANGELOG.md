# Changelog

## Unreleased

## [1.0.1] - 2026-09-24

### Added
- Downloads paralelos de QRZ, WRL, Club Log, eQSL OutBox, eQSL Inbox e LoTW.
- Barra de progresso individual por fonte e progresso agregado.
- Jobs de sincronização em background, permitindo que a interface continue responsiva.

### Safety
- Cada fonte grava em snapshot atômico independente.
- Falhas de download preservam o snapshot anterior.
- Sincronização em background continua somente leitura nas fontes remotas.


- adiciona **Award Master** QRZ + LoTW com preview read-only, auditoria, guardrails de cobertura e bloqueio de exportação quando houver pareamento ambíguo ou regressão;
- preserva metadados úteis para awards sem sobrescrever silenciosamente identidade de QSO;
- corrige a marca lateral para exibir o indicativo completo **PU2BRU** sem corte;
- inclui testes de regressão e gates de produção específicos para a nova rotina.


All notable changes to PU2BRU QSO Manager are documented here.

The project follows semantic versioning for production releases.

## [1.0.0] - 2026-09-14

### Added
- Production Windows desktop distribution with local-first architecture.
- Unified QSO workspace across QRZ, World Radio League, Club Log, eQSL, LoTW, HRDLog and manual Ham Radio Deluxe ADIF.
- Complete eQSL Inbox download with generated-file validation.
- Audited eQSL → QRZ confirmation synchronization.
- Strict 1:1 matching for automatic QSL updates with a two-minute tolerance.
- Exact QRZ LOGID preflight, live ADIF backup, canary update and post-write verification.
- Protection for `CONTEST_ID`, LoTW confirmation fields and QSO identity during QRZ replacement.
- Local encrypted credential storage.
- Windows installer self-test and installed-copy GUI smoke test.
- Android companion build pipeline (preview).

### Safety
- No automatic remote delete in the eQSL → QRZ workflow.
- QRZ arbitrary replacement remains unavailable outside the audited QSL workflow.
- Ambiguous matches, missing dates and collisions are never auto-written.

