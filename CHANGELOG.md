# Changelog

## [1.0.2] - 2026-09-24

### Android hotfix — 2026-09-25

- corrige a leitura do QRZ Logbook no Android quando o campo ADIF chega codificado ou duplamente codificado;
- preserva caracteres literais do ADIF, incluindo valores com `+`, sem corromper o conteúdo ao interpretar a resposta;
- adiciona timeout ampliado e retentativas limitadas para leituras QRZ em falhas transitórias;
- mantém o fallback oficial de `FETCH ALL` para paginação por `MAX:250,AFTERLOGID` e preserva o snapshot anterior em download incompleto;
- alinha automaticamente a versão do APK Android à versão do pacote mobile.

- muda o LoTW de feed de confirmações para **log completo**: QSOs aceitos + QSLs/confirmações;
- adiciona sincronização incremental LoTW usando `APP_LoTW_LASTQSORX` e `APP_LoTW_LASTQSL`;
- migra automaticamente snapshots antigos do LoTW que continham somente QSLs;
- gera o **Master para awards diretamente das fontes já carregadas**, sem reenviar QRZ/LoTW;
- mantém upload manual de ADIF apenas como modo avançado;
- preserva os guardrails, auditoria e bloqueios de segurança do Master;
- mantém downloads paralelos e progresso por fonte da v1.0.1.


## [1.0.1] - 2026-09-24

- corrige a validação LoTW para usar uma consulta pequena, com timeout e mensagens de erro acionáveis;

- executa downloads paralelos das fontes remotas, com até seis integrações simultâneas;
- adiciona barra de progresso geral e estado individual por fonte;
- mantém falhas isoladas por provedor sem interromper os demais downloads nem apagar snapshots anteriores;
- preserva compatibilidade do endpoint de sincronização existente, agora também executado em paralelo;

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

