# PU2BRU QSO Manager

Aplicação local para importar, reconciliar, revisar e auditar QSOs de múltiplas fontes com foco em evitar falsos "faltantes".

## Windows 11 — instalação recomendada

A forma recomendada é usar o instalador `PU2BRU-QSO-Manager-Setup.exe` gerado pelo workflow **Release 4 Windows Installer**.

1. Execute o instalador.
2. Clique em **Instalar**.
3. Abra **PU2BRU QSO Manager** pelo atalho criado no Menu Iniciar ou na área de trabalho.

O instalador contém o runtime necessário. **Não é necessário instalar Python, Node.js ou npm** para usar a versão instalada.

O aplicativo inicia o servidor somente em `127.0.0.1:8000` e abre a interface no navegador padrão. A pequena janela nativa do QSO Manager permanece aberta enquanto o servidor local estiver ativo; use **Encerrar** para desligá-lo corretamente.

### Dados persistentes

A aplicação instalada mantém banco, configurações, backups e arquivos de trabalho fora da pasta do programa, em:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\
```

O banco principal fica em:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\data\qso_manager.db
```

Isso evita perder QSOs ao atualizar ou reinstalar o aplicativo.

### Aviso do Windows

O instalador ainda não possui assinatura digital de um certificado de code signing. Por isso, o Windows SmartScreen pode mostrar **Editor desconhecido**. Enquanto não houver assinatura, confirme que o arquivo veio do workflow oficial deste repositório antes de executá-lo.

## Execução a partir do código-fonte — somente desenvolvimento

Para desenvolver a aplicação, instale Python 3.12+ e Node.js 22+, abra PowerShell na pasta do projeto e execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Depois execute `start.bat`.

## Validação

A versão Windows empacotada é construída e testada automaticamente no GitHub Actions. O pipeline:

- compila o frontend React;
- executa os testes do backend;
- valida Releases 2 e 3;
- gera o executável standalone com PyInstaller;
- executa um self-test do executável já empacotado;
- cria o instalador com Inno Setup;
- publica `PU2BRU-QSO-Manager-Setup.exe` como artefato.

O Release 1 continua protegido pela suíte imutável executada no workflow Linux de acceptance.

## Integrações

### QRZ

O sistema gera plano/dry-run por UUID e exige localizador exato `CALL + QSO_DATE + TIME_ON`. Ambiguidade ou ausência de `TIME_ON` aborta o plano.

A escrita real no QRZ permanece **fail-closed**: o endpoint de apply retorna bloqueio e não executa rede. Um transporte real só deve ser liberado depois de backup, operação de um único registro e re-FETCH de confirmação.

### WRL UDP

O bridge WRL usa por padrão `127.0.0.1:2237` e aceita somente `localhost`/endereços loopback. Destinos LAN/Internet são rejeitados. `dry_run=true` não abre socket. Envio UDP real exige `WRL_UDP_ENABLED=true` explicitamente.

As configurações da aplicação instalada podem ser colocadas em:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\.env
```

Exemplo:

```env
QRZ_API_KEY=
QRZ_USERNAME=
QRZ_DRY_RUN=true
QRZ_WRITE_ENABLED=false

WRL_UDP_HOST=127.0.0.1
WRL_UDP_PORT=2237
WRL_UDP_ENABLED=false
```

## Segurança operacional

- Upload manual usa `PARTIAL_EXPORT` por padrão.
- Ausência em export parcial não é tratada como prova de QSO faltante.
- Atualizações manuais são aplicadas por UUID e persistidas contra a identidade estável do QSO.
- Resoluções de divergência sobrevivem a novas reconciliações.
- QRZ real não é habilitado implicitamente nem pela presença de credenciais.
- WRL UDP real é restrito a loopback e exige enable explícito.

## Arquitetura

`RawQSO -> NormalizedQSO -> QSOIdentity -> LogicalQSO -> QSOSourceLink`

O `LogicalQSO` é uma visão materializada. Overrides e resoluções humanas pertencem à `QSOIdentity` persistente.
