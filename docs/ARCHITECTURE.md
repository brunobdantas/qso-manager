# Architecture

## Product shape

PU2BRU QSO Manager is a local-first QSO reconciliation and logbook-management application.

The Windows production build contains:
- React frontend;
- FastAPI local backend;
- SQLite persistent database;
- encrypted local credential store;
- provider adapters;
- ADIF parser and reconciliation engine;
- PyInstaller runtime bundled by Inno Setup.

The packaged API binds to loopback only.

## Data layers

The persistent reconciliation model is:

```text
RawQSO
  -> NormalizedQSO
  -> QSOIdentity
  -> LogicalQSO
  -> QSOSourceLink
```

Cloud/provider snapshots are deliberately separate from the persistent reconciliation database. A snapshot refresh therefore cannot silently rewrite the persistent logical-QSO model.

## Source roles

Log sources:
- QRZ
- World Radio League
- Club Log
- eQSL OutBox
- HRDLog
- Ham Radio Deluxe ADIF

Confirmation evidence:
- eQSL Inbox
- LoTW

## Matching

Automatic eQSL → QRZ updates require:
- same normalized CALL;
- same QSO date;
- same band;
- compatible effective mode;
- time difference of at most 120 seconds;
- strict one-to-one relationship;
- explicit eQSL receive date;
- stable QRZ LOGID.

Ambiguous relationships are review-only.

## QRZ mutation boundary

The audited confirmation workflow is intentionally narrow. It may change only:
- `EQSL_QSL_RCVD`
- `EQSL_QSLRDATE`

Before writing, the service fetches the exact live LOGID and checks the expected state. After `INSERT + OPTION=REPLACE`, it fetches the record again and verifies protected fields including QSO identity, `CONTEST_ID` and LoTW confirmation state.

## Production packaging

The Windows workflow:
1. installs pinned build tooling;
2. builds the frontend;
3. runs backend regression tests;
4. verifies production contracts;
5. builds the PyInstaller onedir bundle;
6. adds Microsoft runtime DLLs;
7. runs executable self-test;
8. runs GUI smoke test;
9. builds the Inno Setup installer;
10. silently installs it in CI;
11. repeats self-test and GUI smoke test on the installed copy.
