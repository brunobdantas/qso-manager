# PU2BRU QSO Manager

QSO Manager v9 é uma central unificada para **baixar, importar, comparar, reconciliar, revisar e gerenciar QSOs** no Windows e no Android.

A experiência principal é a mesma nas duas plataformas:

**Visão geral → Log → Revisar → QSL → Fontes**

Recursos avançados, histórico e diagnóstico ficam em segundo nível para não poluir a jornada principal.

## Fontes e capacidades

| Fonte | Leitura | Inclusão | Edição | Exclusão | Observação |
| --- | --- | --- | --- | --- | --- |
| QRZ | API | Sim | Não | Não | Sem `REPLACE`; protege confirmações |
| World Radio League | API | Sim | Sim | Sim | ID remoto estável |
| Club Log | API | Sim | Não | Sim | Exclusão por identidade exata |
| eQSL OutBox | API | Sim | Não | Não | Upload via interface de logger |
| eQSL Inbox | API | Evidência QSL | — | — | Confirmações recebidas |
| LoTW | API | Evidência QSL | — | — | Leitura de confirmações |
| HRDLog.net | ADIF + online | Sim | Não | Não | Estado = bootstrap ADIF + inserts confirmados |
| Ham Radio Deluxe | ADIF | — | — | — | Fonte local comparável em Windows e Android |

O **QRZ é a referência preferencial**, não uma verdade cega. Se outras fontes independentes contradizem ou complementam o QRZ, o sistema apresenta a evidência para revisão em vez de sobrescrever silenciosamente.

## Paridade Windows e Android

Ambas as plataformas oferecem:

- log lógico consolidado por QSO;
- QRZ, WRL, Club Log, eQSL, LoTW e HRDLog;
- importação/reconciliação ADIF do Ham Radio Deluxe;
- detecção de ausências, divergências e duplicidades;
- central de QSL;
- publicação remota conforme capacidade do provedor;
- ações em lote seguras;
- exportação ADIF;
- comparação manual/avançada de ADIF;
- análise manual de QSL por arquivos;
- histórico de ações;
- diagnóstico operacional.

A interface é adaptada ao dispositivo: desktop privilegia densidade de dados; Android usa cards, bottom navigation e sheets. A regra de negócio permanece equivalente.

## Windows 10/11

Use o instalador gerado pelo workflow **Release 4 Windows Installer**. Python, Node.js e npm não são necessários na máquina do usuário.

O v9 removeu a dependência de Tk/Tcl do launcher. Ao abrir o atalho:

1. o processo cria o diretório persistente;
2. escolhe uma porta local disponível, preferindo `127.0.0.1:8000`;
3. inicia o FastAPI/Uvicorn;
4. espera `/api/health` responder;
5. abre o navegador padrão.

Se a porta 8000 estiver ocupada por outro programa, o launcher procura automaticamente outra porta local.

### Diagnóstico de inicialização

O launcher grava:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\logs\launcher.log
```

A própria aplicação tem a tela **Diagnóstico**, que verifica:

- banco SQLite;
- frontend empacotado;
- permissão de escrita;
- diretório de logs;
- registro de provedores;
- informações do runtime instalado.

O CI executa, tanto no bundle quanto na instalação silenciosa:

```text
PU2BRU-QSO-Manager.exe --self-test
PU2BRU-QSO-Manager.exe --smoke-start
```

O segundo comando sobe o servidor real, consulta health/root e encerra. Assim, um instalador não é aprovado apenas porque o executável existe.

## Android

O APK é gerado pelo workflow **Release 5 Android APK**.

As credenciais ficam no Secure Storage/Android Keystore; snapshots e histórico ficam no armazenamento local da aplicação. Requisições aos provedores usam a camada HTTP nativa do Capacitor.

A partir da v9 o workflow mantém uma identidade de assinatura de desenvolvimento persistente no branch principal, evitando troca de certificado a cada build. Builds antigos da série v8 podem exigir uma última desinstalação antes da primeira instalação v9.

## Segurança de escrita

O QSO Manager aplica a capacidade real de cada provedor:

- **QRZ:** leitura + `INSERT`; sem `UPDATE`, `DELETE` ou `REPLACE`.
- **WRL:** leitura, inclusão, edição e exclusão.
- **Club Log:** leitura, inclusão e exclusão exata.
- **eQSL:** leitura e inclusão.
- **HRDLog.net:** inclusão online; não há leitura completa suportada.
- **HRD:** somente evidência/importação ADIF.

Operações em lote seguem seleção → ação → confirmação → execução → atualização do estado conhecido.

## HRDLog.net

O fluxo é deliberadamente híbrido:

1. importe um export ADIF completo para criar o estado inicial;
2. o QSO Manager identifica ausências de alta confiança;
3. envia apenas os QSOs seguros ao endpoint de realtime upload;
4. após confirmação remota, adiciona o QSO ao snapshot gerenciado;
5. alterações feitas diretamente no site do HRDLog exigem nova reconciliação ADIF.

O sistema não usa scraping para fingir sincronização bidirecional.

## QSL

eQSL Inbox e LoTW são tratados como evidências independentes. A regra é invariável:

> `QSO_DATE` nunca é usado como data de recebimento da QSL.

Se a fonte comprova o recebimento mas não fornece uma data explícita, o sistema registra a evidência sem inventar a data.

## Desenvolvimento

Backend:

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Frontend desktop:

```bash
cd frontend
npm install
npm run dev
```

Mobile:

```bash
cd mobile
npm install
npm test
npm run build
```

## Testes e releases

Os workflows verificam regressões do matching, identidade, cobertura, segurança de escrita, integrações, frontend, runtime Windows e Android.

Arquitetura principal:

```text
backend/   FastAPI + serviços de domínio + snapshots + SQLite
frontend/  shell v9 desktop/responsivo
mobile/    app Android v9 com providers nativos e o mesmo modelo de reconciliação
installer/ launcher e instalador Windows
```

A versão de release atual é **9.0.0**.
