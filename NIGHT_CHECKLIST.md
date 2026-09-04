# Night Checklist - PU2BRU QSO Manager

## Fase 1 - Safe Update Validation ✅ CONCLUÍDA
- [x] SafeUpdateService._validate_changes() implementado
- [x] SafeUpdateService.build_safe_update() valida campos
- [x] SafeUpdateService.apply_safe_update() valida campos
- [x] QSOUpdateService._validate_changes() implementado
- [x] QSOUpdateService.update_by_uuid() valida campos
- [x] QSOUpdateService.build_safe_update() adicionado
- [x] test_safe_update_rejects_protected_fields ✅
- [x] test_safe_update_rejects_unknown_fields ✅
- [x] test_qso_update_rejects_protected_fields ✅

## Fase 2 - Manual Override Persistente ⏳ PENDENTE
- [ ] LogicalQSOFieldOverride integrado no SafeUpdateService.apply_safe_update
- [ ] Overrides persistidos em tabela separada
- [ ] Reconciliation aplica overrides após reconstrução
- [ ] test_manual_override_survives_reconciliation

## Fase 3 - Divergence Resolution Persistente ⏳ PENDENTE
- [ ] DivergenceResolutionService implementado
- [ ] Fingerprint estável para divergences
- [ ] Resoluções reaplicadas após reconciliação
- [ ] test_divergence_resolution_survives_reconciliation

## Fase 4 - Status needs_review Correto ⏳ PENDENTE
- [ ] Verificar lógica de status baseada em matches/candidatos
- [ ] QRZ sem TIME_ON deve gerar needs_review
- [ ] test_ambiguous_no_time_status_is_needs_review verifica status corretamente

## Fase 5 - .gitignore e Limpeza ⏳ PENDENTE
- [ ] Remover delimitadores Markdown do .gitignore
- [ ] Adicionar todas entradas necessárias
- [ ] Remover backend/data/qso_manager.db
- [ ] Remover __pycache__/
- [ ] Remover *.pyc
- [ ] Remover .pytest_cache/

## Fase 6 - Testes Adversariais ⏳ PENDENTE
- [ ] Mesmo CALL em horas diferentes (11:59, 12:00, 18:00)
- [ ] Mesmo CALL em bandas diferentes
- [ ] Mesmo CALL FT8 vs FT4
- [ ] TIME ausente em múltiplas fontes
- [ ] Frequência ausente em uma fonte
- [ ] Grid 4-char vs 6-char
- [ ] QSO repetido no mesmo arquivo
- [ ] Três fontes com pequenas diferenças
- [ ] Quatro fontes
- [ ] Fonte com campos vazios

## Fase 7 - Smoke Tests Completos ⏳ PENDENTE
- [ ] GET /api/health = 200
- [ ] GET /api/qsos = 200
- [ ] GET /api/qsos/normalized = 200
- [ ] GET /api/qsos/divergences = 200
- [ ] POST /api/imports/adif (QRZ) = 200
- [ ] POST /api/imports/adif (WRL) = 200
- [ ] POST /api/reconciliation = 200 (3x)
- [ ] Validação SQLite: LogicalQSO=1, Links=2, Runs=3

## Fase 8 - Cluster Evolutivo ⏳ PENDENTE
- [ ] QRZ+WRL reconcile → 1 LogicalQSO, 2 links
- [ ] Adicionar MSHV → reconcile → 1 LogicalQSO, 3 links
- [ ] test_reconciliation_evolving_cluster_replaces_active_view ✅ (já existe)

## Critério de Aceite Final
- [ ] pytest: 0 failed
- [ ] Mais de 34 testes
- [ ] Smoke tests passando
- [ ] Overrides manuais sobrevivem à reconciliação
- [ ] Divergence resolutions sobrevivem à reconciliação
- [ ] .gitignore válido sem Markdown
- [ ] Nenhum arquivo proibido versionado
