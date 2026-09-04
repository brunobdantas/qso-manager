# PU2BRU QSO Manager — Release 1 Backend Core

## Resultado

Release 1 backend core validado contra a suíte externa de aceite.

- 60 testes coletados
- 60 testes aprovados
- 0 falhas
- `python acceptance/run_release1_acceptance.py` → `RESULT: PASS`, exit code 0
- segunda execução consecutiva → PASS
- suíte também executada com `SAWarning` tratado como erro → PASS

## Funcionalidades fechadas

- identidade persistente `QSOIdentity` separada da visão materializada `LogicalQSO`;
- identidade preservada após nova reconciliação, entrada de nova fonte e restart;
- dois QSOs reais do mesmo indicativo no mesmo dia permanecem distintos;
- override manual persistente por identidade, inclusive após evolução de cluster;
- resolução humana de divergência persistente por identidade/campo/fontes;
- `needs_review` aplicado ao QSO específico quando `TIME_ON` ausente gera ambiguidade;
- update seguro por UUID, sem fallback inseguro para ID inteiro;
- imports manuais usam `PARTIAL_EXPORT` por padrão;
- suporte persistente a `coverage_start`, `coverage_end` e `coverage_metadata`;
- avaliação conservadora de cobertura (`PRESENT`, `MISSING_HIGH_CONFIDENCE`, `INSUFFICIENT_COVERAGE`, `OUT_OF_COVERAGE`);
- regressão crítica 12:39 protegida, incluindo 20 s, 800 Hz e equivalência MFSK/SUBMODE FT4 × FT4;
- auditoria de reconciliação persistida na mesma transação do run;
- parser ADIF, reimportação idempotente, backup JSON/ADI e endpoints principais preservados;
- `.gitignore` com regras de segurança para bancos, secrets, caches e artefatos locais.

## Arquitetura do núcleo

`RawQSO -> NormalizedQSO -> QSOIdentity -> LogicalQSO -> QSOSourceLink`

`LogicalQSOFieldOverride` e `DivergenceResolution` pertencem a `QSOIdentity` e não à visão transitória.

## Limitações deliberadas deste release

- frontend executável ainda pertence ao Release 2;
- QRZ/WRL/UDP reais pertencem ao Release 3 e não foram habilitados;
- permanecem avisos de depreciação de Pydantic/SQLAlchemy/datetime que não afetam o contrato funcional do Release 1; os conflitos de identity map (`SAWarning`) foram eliminados.
