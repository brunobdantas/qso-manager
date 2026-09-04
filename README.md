# PU2BRU QSO Manager

Central local para baixar, comparar, reconciliar e gerenciar QSOs sem depender de abrir cada plataforma individualmente.

## Release 5 — Connected QSO Hub

O fluxo principal conecta **QRZ, World Radio League (WRL), Club Log e eQSL** ao backend local. Cada fonte pode ser atualizada sob demanda e o QSO Manager preserva um snapshot local completo para pesquisa, comparação e evidência.

O **QRZ é a base preferencial**, mas não é tratado como verdade cega: um QSO ausente no QRZ e presente em outras fontes aparece como candidato de desatualização. Quando duas ou mais fontes independentes corroboram o mesmo QSO, a evidência é elevada, porém nenhuma correção é executada automaticamente.

Principais recursos:

- baixar snapshots completos de QRZ, WRL, Club Log e eQSL;
- atualizar uma fonte ou todas as fontes conectadas;
- comparar QRZ × cada fonte usando o mesmo núcleo tolerante do comparador ADIF;
- separar faltantes, divergências de campos e duplicidades prováveis;
- pesquisar QSOs nos quatro snapshots sem abrir os sites;
- enviar QSO faltante do QRZ para uma fonte suportada;
- adicionar ao QRZ um QSO corroborado por outra fonte, somente com confirmação explícita;
- editar/excluir contatos WRL por ID estável;
- excluir contato Club Log por identidade exata;
- manter o comparador manual de dois arquivos ADIF para qualquer outra fonte.

### Credenciais

As credenciais são cadastradas pela própria tela **Fontes** e ficam apenas no backend local. O arquivo de conexões é criptografado com AES-GCM e a interface nunca devolve a chave/senha completa depois de salva.

Dados persistentes:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\
```

Snapshots das APIs:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\cloud_snapshots\
```

Para configurar as fontes:

- **QRZ:** Logbook API Key de uma assinatura compatível com Logbook API.
- **WRL:** Developer API Key criada em Integrations → Developer API; Logbook ID é opcional.
- **Club Log:** e-mail, Application Password, indicativo do log e API Key para operações de escrita.
- **eQSL:** indicativo/Username, senha e QTH Nickname opcional.

## Segurança de escrita remota

O sistema é conservador por desenho.

**QRZ:** leitura completa e `INSERT` de QSO ausente são suportados. O sistema não usa `REPLACE`, não oferece edição arbitrária nem `DELETE`. Após `INSERT`, o LOGID retornado é consultado novamente por FETCH; falha de verificação aborta a operação. Isso preserva a regra de QRZ como base preferencial sem arriscar confirmações.

**WRL:** leitura, inclusão, edição e exclusão usam a API REST e o ID remoto estável do contato. Alterações partem de snapshot local e exigem confirmação.

**Club Log:** download completo, inclusão individual em tempo real e exclusão por identidade exata. O export do Club Log é tratado como representação minimalista e não como cópia byte a byte do log original.

**eQSL:** leitura do OutBox e inclusão são suportadas. Edição e exclusão remotas não são oferecidas sem interface oficial documentada para essas operações.

Antes de escrita/exclusão suportada, o snapshot local do destino é copiado para backup. Nenhuma divergência de campo sobrescreve automaticamente o QRZ.

## Comparação e identidade

O pareamento usa CALL, data, banda, horário e frequência com tolerância controlada. Modo não é uma chave rígida; equivalências como `MFSK/SUBMODE=FT4` × `FT4` são aceitas. Diferenças pequenas de segundos e frequência podem ser classificadas como toleradas. Duplicidades praticamente idênticas na mesma fonte não viram falsos QSOs faltantes.

O comparador manual continua disponível para exports ADIF completos ou parciais. Upload manual permanece conservador: ausência em `PARTIAL_EXPORT` não prova que um QSO esteja faltando.

## Windows 11 — instalação recomendada

Use `PU2BRU-QSO-Manager-Setup.exe` gerado pelo workflow Windows. O instalador contém o runtime necessário; **não é necessário instalar Python, Node.js ou npm**.

O aplicativo inicia somente em `127.0.0.1:8000` e abre a interface no navegador padrão. A janela nativa permanece aberta enquanto o servidor local está ativo; use **Encerrar** para desligá-lo corretamente.

O banco principal permanece em:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\data\qso_manager.db
```

Atualizar ou reinstalar o programa não remove os dados persistentes.

### Aviso do Windows

O instalador ainda não possui assinatura digital de code signing. O Windows SmartScreen pode mostrar **Editor desconhecido**. Confirme que o arquivo veio do workflow oficial deste repositório antes de executá-lo.

## Execução a partir do código-fonte — somente desenvolvimento

Para desenvolvimento, use Python 3.12+ e Node.js 22+:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Depois execute `start.bat`.

## Validação

O pipeline Windows compila o React, executa os testes de backend e regressão, gera o executável standalone com PyInstaller, executa self-test já no binário empacotado e cria o Setup com Inno Setup. O self-test da Release 5 também valida que o Connected QSO Hub, criptografia local e rotas `/api/cloud/*` foram incluídos no executável.

O Release 1 continua protegido pela suíte imutável de acceptance em Linux.

## Arquitetura legada/persistente

`RawQSO -> NormalizedQSO -> QSOIdentity -> LogicalQSO -> QSOSourceLink`

O `LogicalQSO` é uma visão materializada. Overrides e resoluções humanas pertencem à `QSOIdentity` persistente. O Connected QSO Hub usa snapshots independentes para que a análise de nuvem não altere silenciosamente essa base local.
