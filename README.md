# PU2BRU QSO Manager

[![Core Acceptance](https://github.com/brunobdantas/qso-manager/actions/workflows/release1-acceptance.yml/badge.svg)](https://github.com/brunobdantas/qso-manager/actions/workflows/release1-acceptance.yml)
[![Desktop](https://github.com/brunobdantas/qso-manager/actions/workflows/release2-local-app.yml/badge.svg)](https://github.com/brunobdantas/qso-manager/actions/workflows/release2-local-app.yml)
[![Integrations](https://github.com/brunobdantas/qso-manager/actions/workflows/release3-integrations.yml/badge.svg)](https://github.com/brunobdantas/qso-manager/actions/workflows/release3-integrations.yml)
[![Windows](https://github.com/brunobdantas/qso-manager/actions/workflows/release4-windows-installer.yml/badge.svg)](https://github.com/brunobdantas/qso-manager/actions/workflows/release4-windows-installer.yml)

**PU2BRU QSO Manager v1.0.0** é um gerenciador local-first para radioamadorismo que consolida, compara e reconcilia QSOs entre múltiplos logbooks, com foco em integridade de dados e escritas remotas auditáveis.

> **Status:** Windows 11 é o alvo de produção da v1.0.0. O aplicativo Android é um companion em preview e não executa a rotina de escrita eQSL → QRZ.

## O que o produto faz

- consolida QRZ, World Radio League, Club Log, eQSL, LoTW, HRDLog e ADIF do Ham Radio Deluxe;
- pesquisa e compara QSOs sem precisar abrir cada plataforma;
- identifica ausências, divergências e duplicidades prováveis;
- mantém snapshots locais das fontes online;
- usa evidências do eQSL Inbox e LoTW para análise de confirmação;
- sincroniza confirmações recebidas no eQSL para o QRZ com política conservadora;
- oferece comparação avançada de arquivos ADIF;
- gera um **Master ADIF para awards** combinando QRZ + LoTW com política conservadora, auditoria e bloqueio automático contra regressão de cobertura;
- preserva backups e histórico de atividade;
- armazena credenciais localmente de forma criptografada.

## Integrações

| Fonte | Leitura | Escrita suportada | Papel |
| --- | :---: | :---: | --- |
| QRZ | ✅ | ✅ restrita | Log de referência e destino auditado de confirmações eQSL |
| World Radio League | ✅ | ✅ | Log online |
| Club Log | ✅ | ✅ | Log online |
| eQSL OutBox | ✅ | ✅ inclusão | Log enviado ao eQSL |
| eQSL Inbox | ✅ | — | Evidência de QSL recebida |
| LoTW | ✅ | — | Evidência de QSL recebida |
| HRDLog.net | bootstrap + envio | ✅ inclusão | Log online/híbrido |
| Ham Radio Deluxe | ADIF local | — | Fonte manual/local |

As capacidades variam de acordo com a API pública oferecida por cada serviço. O QSO Manager não inventa operações que o provedor não documenta ou não permite.

## eQSL → QRZ

A Central de QSL pode atualizar o QRZ a partir das confirmações recebidas no eQSL Inbox.

Uma atualização automática só é elegível quando houver:

1. mesmo CALL normalizado;
2. mesma data do QSO;
3. mesma banda;
4. modo compatível;
5. diferença de horário de no máximo 2 minutos;
6. relação estritamente 1:1;
7. data explícita de recebimento no eQSL;
8. LOGID estável no QRZ.

O sistema altera exclusivamente:

```text
EQSL_QSL_RCVD = Y
EQSL_QSLRDATE = <data explícita do eQSL>
```

Antes da primeira gravação, o lote inteiro passa por preflight. O sistema cria backup local e backup do ADIF live, executa um canário, busca o LOGID novamente antes de cada alteração e valida o registro após o `REPLACE`.

Campos protegidos — incluindo identidade do QSO, `CONTEST_ID` e confirmação/data LoTW — não podem mudar silenciosamente. Qualquer regressão interrompe o lote.

Casos ambíguos, colisões, ausência de data ou pareamentos fora da janela automática permanecem fora da gravação.

## Master ADIF para awards

Na área **Ferramentas → Master para awards**, o desktop pode combinar exports completos do QRZ e do LoTW sem escrever em nenhuma plataforma remota.

A rotina usa pareamento conservador: primeiro por identidade e horário exatos; apenas pares 1:1 dentro de uma janela curta podem ser aproximados. Casos ambíguos permanecem separados e bloqueiam a exportação segura. O QRZ é usado para enriquecer metadados como IOTA e grids; o LoTW prevalece nos campos geográficos de award. Antes de liberar o download, o sistema compara métricas protegidas — DXCC, grids, IOTA e cobertura de estados por FT8/FT4. Regressões críticas bloqueiam o Master. Divergências de grid que não podem ser preservadas simultaneamente sem duplicar um QSO são mantidas como alertas auditados, com preferência conservadora pela localização do LoTW.

O relatório de auditoria registra conflitos, pareamentos ambíguos, hashes SHA-256 das fontes e do Master gerado. A indicação **SAFE** é uma validação interna do QSO Manager sobre integridade da fusão; não substitui a validação das entidades emissoras de awards.

## Segurança e privacidade

O Windows desktop opera localmente e publica a API somente em `127.0.0.1`.

Dados persistentes:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\
```

Banco principal:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\data\qso_manager.db
```

Snapshots das fontes:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\cloud_snapshots\
```

As credenciais cadastradas em **Fontes** são armazenadas localmente pelo credential store criptografado. A interface não devolve segredos completos depois de salvos.

Consulte [SECURITY.md](SECURITY.md) antes de reportar qualquer problema envolvendo credenciais, dados privados ou escrita remota.

## Instalação — Windows 11

O artefato de produção é:

```text
PU2BRU-QSO-Manager-Setup-v1.0.0.exe
```

Ele é gerado pelo workflow **Build · Windows Installer** e inclui o runtime necessário. Não é necessário instalar Python, Node.js ou npm.

A atualização/reinstalação do programa não remove os dados persistentes do usuário.

### SmartScreen

A v1.0.0 ainda não possui assinatura digital de code signing. O Windows pode exibir **Editor desconhecido**. Use somente o instalador produzido pelo workflow oficial deste repositório e valide sua origem antes da execução.

## Desenvolvimento

Requisitos:

- Python 3.12+
- Node.js 22+

No Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
start.bat
```

Testes locais:

```powershell
test.bat
python scripts/verify_product_parity.py
python scripts/verify_production.py
```

Build do frontend:

```powershell
cd frontend
npm ci
npm run build
```

## Qualidade e release gates

A v1.0.0 exige, no CI:

- suíte de acceptance imutável;
- regressão completa do backend;
- build do frontend;
- verificação de integrações;
- contrato de capacidades do produto;
- verificação de metadados de produção;
- build PyInstaller;
- self-test do executável empacotado;
- GUI smoke test do executável empacotado;
- build Inno Setup;
- instalação silenciosa;
- self-test e GUI smoke test da cópia instalada.

A estratégia completa está em [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md).

## Arquitetura

Modelo persistente de reconciliação:

```text
RawQSO -> NormalizedQSO -> QSOIdentity -> LogicalQSO -> QSOSourceLink
```

Snapshots de provedores são mantidos separados do modelo persistente para impedir que uma atualização de API reescreva silenciosamente a base reconciliada.

Mais detalhes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentação do projeto

- [Changelog](CHANGELOG.md)
- [Arquitetura](docs/ARCHITECTURE.md)
- [Produção e release](docs/PRODUCTION_READINESS.md)
- [Segurança](SECURITY.md)
- [Contribuição](CONTRIBUTING.md)
- [Suporte](SUPPORT.md)

## Escopo de plataforma

| Plataforma | Estado v1.0.0 |
| --- | --- |
| Windows 11 | **Produção** |
| Android | **Preview / companion** |

O Android participa de leitura, comparação e gestão local de fontes compatíveis, mas não deve ser interpretado como equivalente ao desktop para mutações auditadas no QRZ.
