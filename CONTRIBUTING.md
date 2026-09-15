# Contributing

PU2BRU QSO Manager prioritizes data integrity over convenience. Changes that write to remote logbooks must be fail-closed, reviewable and covered by tests.

## Development environment

Requirements:
- Python 3.12+
- Node.js 22+
- Windows is required only for installer verification.

On Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
test.bat
```

For the desktop UI:

```powershell
cd frontend
npm ci
npm run build
```

## Pull requests

A pull request should:
- explain the user-visible behavior;
- include regression tests for bug fixes;
- preserve the conservative ADIF matching rules;
- avoid embedding credentials or user logs;
- update `CHANGELOG.md` for production-facing changes;
- pass all GitHub Actions checks.

## Remote-write rules

Any new remote mutation must document:
1. the provider-supported operation;
2. the stable record identity used;
3. preconditions checked immediately before writing;
4. fields allowed to change;
5. protected fields verified after writing;
6. backup/rollback strategy;
7. ambiguity behavior.

A remote write must never be inferred from a low-confidence match.

## Versioning

Production releases use semantic versioning. The canonical release number is recorded in `VERSION` and enforced by `scripts/verify_production.py`.
