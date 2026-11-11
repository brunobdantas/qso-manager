# Capacidades de escrita das APIs — v1.1.4

Pesquisa consolidada em 10/11/2026. A regra do produto é conservadora: uma operação só aparece quando existe documentação pública ou código-fonte primário que demonstre o contrato. Ausência de API não é contornada com automação de tela nem com edição direta de banco proprietário.

| Plataforma | Ler | Criar | Editar | Excluir | Implementação na v1.1.4 |
| --- | :---: | :---: | :---: | :---: | --- |
| QRZ Logbook | ✅ | ✅ | ✅ | ✅ | `FETCH`, `INSERT`, `INSERT OPTION=REPLACE` e `DELETE LOGIDS`; edição restrita a metadados seguros |
| World Radio League | ✅ | ✅ | ✅ | ✅ | `GET/POST /v1/contacts`, `PATCH/DELETE /v1/contacts/{id}` |
| Club Log | ✅ | ✅ | `CALL` | ✅ | `realtime.php`, `QSLCALL` e `delete.php`; sem edição genérica |
| eQSL | ✅ | ✅ | — | — | download de OutBox e `ImportADIF.cfm` |
| LoTW | ✅ | — | — | — | relatório de QSOs/QSLs; sem CRUD remoto geral |
| HRDLog.net | ADIF | ✅ | ✅ | ✅ | `NewEntry.aspx`, comandos `UPDATE`/`DELETE` e `ADIFKey` |
| Ham Radio Deluxe local | ADIF | — | — | — | importação somente leitura; banco local fora do escopo |

## Guardrails aplicados

- Nenhuma escrita é executada durante sincronização ou análise.
- A prévia calcula elegibilidade registro a registro antes de liberar a execução.
- O snapshot do destino é copiado para backup antes da primeira mutação.
- Escritas não são repetidas automaticamente após falha de transporte, pois o resultado remoto pode ser ambíguo.
- QRZ: `LOGID` obrigatório, `FETCH` exato, identidade conferida contra a prévia, ADIF vivo preservado e novo `FETCH` após `REPLACE`.
- QRZ: `CALL`, data, hora, banda, frequência, modo, submodo, indicativo da estação e campos de confirmação não podem ser alterados pelo editor genérico.
- WRL: ID remoto obrigatório para editar/excluir; criação envia timestamp UTC ISO-8601.
- Club Log: somente `CALL` pode ser corrigido; exclusões são limitadas a 10 por lote, conforme orientação do serviço.
- HRDLog: `UPDATE` e `DELETE` exigem a chave antiga exata; resposta zero é falha para edição/exclusão, não sucesso.
- Exclusão remota exige prévia e a confirmação digitada `EXCLUIR`.

## Fontes primárias e projetos examinados

- [QRZ Logbook API Developer Guide](https://www.qrz.com/docs/logbook30/api)
- [QRZ Logbook integration overview](https://www.qrz.com/page/qrz-logbook.html)
- [Nexus — integração QRZ/WRL/Club Log](https://github.com/kd9taw/Nexus)
- [WRL implementation in Nexus](https://github.com/kd9taw/Nexus/blob/main/crates/tempo-core/src/wrl.rs)
- [WRL client in TR4W](https://github.com/TR4W/TR4W-D12/blob/main/tr4w/src/uWRLClient.pas)
- [Club Log — real-time QSO deletion](https://clublog.freshdesk.com/support/solutions/articles/54903-how-to-delete-qsos-in-real-time)
- [Club Log — QSLCALL update/delete semantics](https://clublog.freshdesk.com/support/solutions/articles/54908-using-adif-to-update-or-delete-qsos)
- [Club Log — real-time upload](https://clublog.freshdesk.com/support/solutions/articles/54906-how-to-upload-qsos-in-real-time)
- [eQSL programming interfaces](https://www.eqsl.cc/qslcard/Programming.cfm)
- [HRDLOG-net-library do mantenedor IW1QLH](https://github.com/iw1qlh/HRDLOG-net-library)
- [HrdProtocol.cs — contrato INSERT/UPDATE/DELETE](https://github.com/iw1qlh/HRDLOG-net-library/blob/main/src/HRDlibrary/HrdProtocol.cs)
- [LoTW query interface](https://lotw.arrl.org/lotw-help/developer-query-qsos-qsls/)

## Limites conhecidos

- A API do HRDLog não fornece leitura completa do log. Alterações realizadas diretamente no site só entram no QSO Manager após nova reconciliação ADIF.
- O Club Log não fornece edição genérica em tempo real; usar exclusão + inclusão automaticamente seria uma operação composta não atômica e, por isso, não é apresentada como `UPDATE`.
- O `REPLACE` do QRZ pode sobrescrever confirmações se um cliente remontar o ADIF de forma ingênua. A v1.1.4 parte do ADIF vivo retornado pelo QRZ, altera somente o campo autorizado e verifica o resultado.
- eQSL oferece exclusão na interface web, mas não há contrato público de API equivalente; a função permanece indisponível no aplicativo.
