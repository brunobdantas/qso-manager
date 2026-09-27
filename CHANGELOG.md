# Changelog

## [1.0.5] - 2026-09-27

### Award Master Safe V4

- preserva integralmente CQZ/ITUZ quando QRZ e LoTW concordam;
- mantém as correções nativas do LoTW e o histórico do mesmo indicativo;
- reintroduz consenso geográfico entre indicativos somente para zonas cuja origem ainda é exclusivamente QRZ;
- exige mesmo DXCC e mesmo grid;
- grid6 exige pelo menos 2 confirmações LoTW unânimes;
- grid4 exige pelo menos 5 confirmações LoTW unânimes;
- o consenso geográfico nunca pode alterar valores marcados como CONSENSUS, LOTW, QRZ_REVIEW, LOTW_INFERRED ou LOTW_CORRECTED;
- registra a correção como LOTW_GEO_CONSENSUS na auditoria e no ADIF;
- adiciona regressões para os casos reais detectados na validação da v1.0.4.

## [1.0.4] - 2026-09-27

### Award Master Safe V3

- impede que histórico LoTW sobrescreva um valor em que QRZ e LoTW já concordam;
- remove completamente a normalização cruzada por DXCC + grid entre indicativos diferentes;
- restringe correções históricas a mesmo indicativo + mesmo DXCC + mesmo grid, com pelo menos duas confirmações LoTW unânimes;
- usa grid de 6 caracteres quando disponível; registros com grid de 6 caracteres não fazem fallback para consenso de 4 caracteres;
- trata zonas numericamente equivalentes como iguais (ex.: 5 = 05, 7 = 07);
- registra explicitamente a origem de CQZ/ITUZ no Master para bloquear reprocessamentos indevidos;
- preserva correções por sinalizadores nativos do LoTW e a limpeza de IOTA da v1.0.3;
- adiciona regressões baseadas nos casos W3GLH, K8FER e KF5SFJ observados na auditoria real.

## [1.0.3] - 2026-09-27

### Award Master Safe V2

- elimina placeholders inválidos de IOTA sem alterar os logs de origem;
- usa os sinalizadores nativos `APP_LOTW_*_INVALID` e `APP_LOTW_*_INFERRED` para corrigir ou retirar somente metadados explicitamente invalidados pelo LoTW;
- mantém o UltimateAAC exclusivamente como validador externo, nunca como fonte de correção;
- preserva o QRZ em conflitos CQ/ITU não explicados quando QRZ e LoTW descrevem a mesma localização, registrando o caso na auditoria;
- usa consenso de histórico LoTW confirmado, com pelo menos duas observações coerentes, para normalizar CQZ/ITUZ;
- dá preferência ao IOTA confirmado pelo LoTW quando houver conflito;
- não remove grids plausíveis sem evidência nativa; grids explicitamente marcados como inválidos pelo LoTW são descartados ou substituídos;
- adiciona métricas de qualidade e testes de regressão para os casos identificados na validação do UltimateAAC.

## [1.0.2] - 2026-09-24

### LoTW incremental hotfix — 2026-09-26

- serializa as consultas incrementais de QSOs e QSLs do LoTW para evitar duas requisições simultâneas à mesma conta;
- adiciona retentativa limitada para HTTP 429/500/502/503/504, com backoff e suporte a `Retry-After`;
- preserva o snapshot local quando o LoTW permanece indisponível após as tentativas;
- adiciona testes de regressão para HTTP 503 e para a ordem sequencial das consultas incrementais.

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

