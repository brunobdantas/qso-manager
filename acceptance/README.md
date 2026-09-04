# Release 1 Acceptance Contract — PU2BRU QSO Manager

This directory is an **external, immutable acceptance suite**. It is not owned by the implementation agent.

## Immutable rule

Qwen may modify application code under `backend/` but must **not modify, delete, skip, xfail, weaken, or rewrite any file under `acceptance/`**.

## Authority of acceptance

From the repository root:

```bash
python acceptance/run_release1_acceptance.py
```

A Release 1 candidate is accepted only when the runner prints `RESULT: PASS` and exits with code 0.

## Frozen behavior contract

The suite requires, among other things:

- persistent `QSOIdentity` linked to the active `LogicalQSO`;
- identity survives reconciliation, new sources, and restart;
- two real QSOs with the same callsign/day remain distinct;
- manual overrides survive reconciliation, cluster evolution, and restart;
- divergence resolutions survive reconstruction and cluster evolution;
- all update paths use safe UUID targeting and reject protected/unknown fields;
- ambiguous no-time QSO is `needs_review`;
- complete-link prevents invalid transitive auto-merges;
- 12:39 regression reconciles correctly with 20 s / 800 Hz / MFSK+FT4 differences;
- manual imports default to `PARTIAL_EXPORT`;
- coverage supports window metadata and conservative absence semantics;
- ADIF raw/unknown fields are preserved;
- backups use ADIF 3.1.7 and persist metadata;
- reconciliation audit is actually committed;
- core API endpoints return 200;
- `.gitignore` contains the required safety rules.

### Coverage service contract

The acceptance suite expects:

```python
from app.services.coverage_service import CoverageService, PresenceStatus

CoverageService().assess(
    is_present: bool,
    coverage_type: CoverageType,
    qso_datetime: datetime,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    coverage_metadata: dict | None,
) -> PresenceStatus
```

`PresenceStatus` must expose these values:

- `PRESENT`
- `MISSING_HIGH_CONFIDENCE`
- `POSSIBLY_MISSING`
- `INSUFFICIENT_COVERAGE`
- `OUT_OF_COVERAGE`

### Divergence resolution contract

The acceptance suite expects:

```python
from app.services.divergence_resolution_service import DivergenceResolutionService

DivergenceResolutionService(db).resolve_divergence(
    divergence_id: int,
    resolved_value: str,
    reason: str,
)
```

The service must persist a stable resolution against the persistent QSO identity and reapply it when the active divergence view is rebuilt.
