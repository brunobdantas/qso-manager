# Support

## Before opening a bug report

1. Confirm the application version in **Ferramentas → Segurança → Diagnóstico do produto**.
2. Reproduce the problem once on the current production build.
3. Export the diagnostic JSON when available.
4. For startup problems, inspect:

```text
%LOCALAPPDATA%\PU2BRU QSO Manager\logs\startup.log
```

5. Remove API keys, passwords and private log content before sharing any material.

## Data-integrity incidents

If a remote logbook was unexpectedly modified:

- stop further synchronization;
- do not delete the local snapshot/backups;
- export the affected provider log;
- record the approximate time of the operation;
- open a bug report with the application version and sanitized evidence.

The eQSL → QRZ workflow stores local and live-ADIF backups before remote mutation. Preserve those files for diagnosis.

## Connectivity

Provider errors can come from credentials, provider-side outages, rate limits or changes in third-party APIs. Use the **Conexão** action for the affected source before reporting a general application failure.

## Security

Do not report credentials or vulnerability details in a public issue. Follow [SECURITY.md](SECURITY.md).
