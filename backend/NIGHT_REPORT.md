# PU2BRU QSO Manager — Night Autonomous Run

## Estado inicial

- **Data/hora**: 2024-09-04 (sessão noturna autônoma)
- **Testes iniciais**: 34 collected, 34 passed, 0 failed
- **Warnings**: 142 warnings (depreciação datetime.utcnow + SAWarning identity map)
- **Principais problemas identificados pela auditoria externa**:
  1. LogicalQSO.uuid muda quando cluster evolui (QRZ+WRL → UUID A, QRZ+WRL+MSHV → UUID B)
  2. Overrides manuais são perdidos após reconciliação
  3. Resoluções de divergência desaparecem após reconciliation
  4. Status needs_review não verifica corretamente o LogicalQSO específico
  5. .gitignore com delimitadores Markdown ```
  6. Arquivos proibidos versionados (qso_manager.db, __pycache__, *.pyc)

## Estrutura de Identidade Persistente Implementada

### Nova entidade: QSOIdentity

```python
class QSOIdentity(Base):
    \"\"\"Persistent identity for a QSO that survives reconciliation and cluster evolution.\"\"\"
    uuid: str  # NUNCA muda para o mesmo QSO real
    callsign: str
    qso_date: str
    time_on: str
    
    # Relacionamentos:
    - logical_qsos (visões materializadas)
    - overrides (LogicalQSOFieldOverride)
    - resolutions (DivergenceResolution)
```

### LogicalQSO agora é visão materializada

```python
class LogicalQSO(Base):
    \"\"\"Materialized active view of a QSO identity at current reconciliation state.\"\"\"
    qso_identity_id: int  # FK para QSOIdentity
    # ... campos canônicos recalculados a cada reconciliation
```

### Modelos atualizados para usar identidade persistente

1. **LogicalQSOFieldOverride**:
   - Antes: `logical_qso_uuid` → FK para LogicalQSO.uuid (instável)
   - Agora: `qso_identity_id` → FK para QSOIdentity.id (estável)

2. **DivergenceResolution**:
   - Antes: `logical_qso_uuid` → FK para LogicalQSO.uuid (instável)
   - Agora: `qso_identity_id` → FK para QSOIdentity.id (estável)
   - `divergence_key`: fingerprint estável baseado em identity + field + sources

## Arquivos alterados

1. **backend/app/models/models.py**:
   - Adicionada classe `QSOIdentity` (linhas 232-255)
   - Modificada classe `LogicalQSO` para incluir `qso_identity_id` e relationship
   - Atualizado `LogicalQSOFieldOverride` para usar `qso_identity_id`
   - Atualizado `DivergenceResolution` para usar `qso_identity_id`

2. **.gitignore**:
   - Substituído completamente sem delimitadores Markdown
   - Incluídos: .env, *.db, __pycache__/, .pytest_cache/, venv/, node_modules/, etc.

3. **Limpeza de artefatos**:
   - Removido: backend/data/qso_manager.db
   - Removidos: todos __pycache__/
   - Removidos: todos *.pyc
   - Removido: .pytest_cache/

## Testes existentes (34 testes)

Todos os 34 testes originais continuam passando:
- test_reconciliation_is_idempotent ✓
- test_reconciliation_evolving_cluster_replaces_active_view ✓
- test_divergences_do_not_duplicate_across_reconciliation_runs ✓
- test_complete_link_prevents_transitive_auto_merge ✓
- test_exact_multisource_status_is_reconciled ✓
- test_ambiguous_no_time_status_is_needs_review ✓
- test_divergences_endpoint_returns_200 ✓
- test_safe_update_rejects_protected_fields ✓
- test_safe_update_rejects_unknown_fields ✓
- test_safe_update_by_uuid_preserves_other_fields ✓
- test_qso_update_rejects_protected_fields ✓
- ... (23 outros)

## Pendências Críticas (P0)

### P0-1: Integração do SafeUpdateService com QSOIdentity
**Status**: Modelo pronto, service precisa ser implementado
**O que falta**: 
- SafeUpdateService.apply_safe_update deve criar/atualizar LogicalQSOFieldOverride
- ReconciliationService deve reaplicar overrides após reconstruir LogicalQSO

### P0-2: DivergenceResolutionService
**Status**: Modelo pronto, service não existe
**O que falta**:
- Implementar serviço para criar/atualizar resoluções
- ReconciliationService deve reaplicar resoluções existentes

### P0-3: Status needs_review correto
**Status**: Teste existe mas pode não verificar status corretamente
**O que falta**:
- Verificar se teste localiza LogicalQSO específico contendo QRZ sem TIME_ON
- Corrigir engine para considerar candidatos externos plausíveis

### P0-4: Warnings SQLAlchemy
**Status**: 142 warnings durante reconciliation
**Problema**: Identity map conflicts durante delete/recreate
**Solução necessária**: Usar synchronize_session=False ou sessão separada

## Próximos passos obrigatórios

1. Implementar SafeUpdateService integrado com QSOIdentity
2. Implementar reconciliação de overrides persistentes
3. Criar DivergenceResolutionService
4. Implementar reconciliação de resoluções persistentes
5. Corrigir warnings SQLAlchemy
6. Adicionar testes de persistência pós-reconciliação
7. Implementar CoverageType (default PARTIAL_EXPORT)
8. Frontend React/Vite
9. QRZ Adapter mock/dry-run

## Como revalidar

```bash
cd /workspace/backend
python -m pytest tests/ -v
# Esperado: 34 collected, 34 passed, 0 failed

# Limpeza pós-testes:
rm -rf .pytest_cache data/qso_manager.db
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -name "*.pyc" -delete

# Verificar limpeza:
cd /workspace
find . -name "*.db" | grep -v "/tmp/"  # Deve retornar vazio
```

## Smoke tests pendentes

- [ ] GET /api/health = 200
- [ ] GET /api/qsos = 200
- [ ] GET /api/qsos/normalized = 200
- [ ] GET /api/qsos/divergences = 200
- [ ] POST /api/imports/adif (QRZ) = 200
- [ ] POST /api/imports/adif (WRL) = 200
- [ ] POST /api/reconciliation × 3 = 200
- [ ] Verificar SQLite: LogicalQSO=1, Links=2, Runs=3

## Decisões arquiteturais

1. **Separação identidade vs. visão materializada**: QSOIdentity representa o QSO real do mundo, LogicalQSO é a visão atual reconstruída a cada reconciliation.

2. **Overrides e resoluções ligadas à identidade**: Dados humanos persistem mesmo quando cluster evolui.

3. **Reconstrução atômica preservada**: DELETE + recreate da visão ativa continua, mas agora com identidade persistente separada.

## Riscos conhecidos

1. **SAWarnings durante reconciliation**: Identity map conflicts podem causar problemas em produção com dados reais.

2. **Migração de dados existentes**: Banco existente teria que ser migrado para nova estrutura QSOIdentity.

3. **Performance**: Recriar toda visão ativa + reaplicar overrides pode ser lento com muitos QSOs.

---

*Relatório gerado automaticamente durante execução noturna autônoma.*
