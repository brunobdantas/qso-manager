# Security Policy

## Supported version

| Version | Support |
| --- | --- |
| 1.0.x | ✅ Current production line |
| Pre-1.0 development builds | ❌ Unsupported |

## Security model

PU2BRU QSO Manager is a local-first desktop application. The Windows build binds its local API to `127.0.0.1` and stores persistent application data under the user's local application-data directory.

Credentials configured in the application are stored locally using the product's encrypted credential store. Secrets must never be committed to this repository, copied into issue reports, screenshots, test fixtures or logs.

Remote mutations are intentionally constrained. The eQSL → QRZ workflow can update only `EQSL_QSL_RCVD` and `EQSL_QSLRDATE`, requires an exact QRZ LOGID, performs a live preflight and verifies protected fields after the write.

## Reporting a vulnerability

Do **not** open a public issue containing credentials, API keys, passwords, private logbook exports or exploit details.

Report the problem privately to the repository owner through GitHub's private contact mechanisms. Include:
- affected version;
- operating system;
- reproduction steps;
- expected and observed behavior;
- whether remote logbook data was modified.

Revoke any exposed third-party credential directly with the provider.

## Scope

Security reports are welcome for credential handling, local API exposure, unsafe remote mutation, dependency vulnerabilities, installer behavior and data integrity.
