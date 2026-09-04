# Release 3 — Integrações e Validação Final

## Entregas

- QRZ adapter com preview/dry-run determinístico e localizador exato `CALL + QSO_DATE + TIME_ON`;
- bloqueio explícito de ambiguidade e de registros sem `TIME_ON`;
- QRZ live transport fail-closed: nenhum endpoint executa escrita real nesta versão;
- WRL UDP adapter restrito a loopback (`localhost`, `127.0.0.0/8`, `::1`);
- WRL `dry_run` sem abertura de socket;
- envio local real exige enable explícito e gera `SyncJob`, `SyncAttempt` e auditoria;
- `/api/integrations/status`;
- endpoints de preview QRZ/WRL e envio WRL controlado;
- `.env.example` com flags seguras;
- testes adversariais de integração;
- `scripts/verify_release3.py` e workflow GitHub Actions final.

## Gates obrigatórios

O workflow `Release 3 Integrations` executa, na ordem:

1. build React/Vite;
2. suíte imutável Release 1;
3. verificação Release 2;
4. testes de segurança das integrações;
5. verificação final Release 3.

## Estado de segurança

QRZ real continua bloqueado de propósito. A presença de `QRZ_API_KEY`, `QRZ_USERNAME` ou `QRZ_WRITE_ENABLED` não transforma o dry-run em escrita. A liberação de mutação real requer um transporte separado e validado com backup prévio e verificação pós-escrita.

WRL UDP pode operar localmente, mas somente em loopback e com `WRL_UDP_ENABLED=true` explícito.
