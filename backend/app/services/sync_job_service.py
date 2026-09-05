"""In-process background synchronization jobs with user-visible progress.

The desktop app is a single local process, so an in-memory job registry is
sufficient and avoids introducing a queue/broker. Jobs only orchestrate reads
and snapshot saves; existing safety rules for remote writes are unchanged.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from ..adapters.cloud_logs import adapter_for
from .cloud_hub_fast_service import CloudHubService


class SyncJobManager:
    _lock = threading.RLock()
    _jobs: Dict[str, Dict[str, Any]] = {}
    _active_by_provider: Dict[str, str] = {}
    _max_history = 100

    @classmethod
    def _now(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _snapshot(cls, job_id: str) -> Dict[str, Any]:
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                raise LookupError("Sync job not found")
            return dict(job)

    @classmethod
    def _set(cls, job_id: str, **changes: Any) -> None:
        with cls._lock:
            if job_id in cls._jobs:
                cls._jobs[job_id].update(changes)

    @classmethod
    def _trim(cls) -> None:
        with cls._lock:
            if len(cls._jobs) <= cls._max_history:
                return
            finished = [
                (job_id, job)
                for job_id, job in cls._jobs.items()
                if job.get("status") in {"succeeded", "failed"}
            ]
            finished.sort(key=lambda pair: pair[1].get("completed_at") or pair[1].get("created_at") or "")
            for job_id, _ in finished[: max(0, len(cls._jobs) - cls._max_history)]:
                cls._jobs.pop(job_id, None)

    @classmethod
    def start(cls, provider: str) -> Dict[str, Any]:
        provider = CloudHubService._provider(provider)
        service = CloudHubService()
        if not service.credentials.configured(provider):
            raise LookupError(f"{provider} is not configured")

        with cls._lock:
            active_id = cls._active_by_provider.get(provider)
            if active_id:
                active = cls._jobs.get(active_id)
                if active and active.get("status") in {"queued", "running"}:
                    return dict(active)

            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "provider": provider,
                "status": "queued",
                "phase": "queued",
                "progress": 0,
                "message": "Aguardando início…",
                "records": None,
                "created_at": cls._now(),
                "started_at": None,
                "completed_at": None,
                "error": None,
                "snapshot": None,
            }
            cls._jobs[job_id] = job
            cls._active_by_provider[provider] = job_id

        thread = threading.Thread(target=cls._run, args=(job_id, provider), daemon=True, name=f"qso-sync-{provider.lower()}")
        thread.start()
        cls._trim()
        return dict(job)

    @classmethod
    def get(cls, job_id: str) -> Dict[str, Any]:
        return cls._snapshot(job_id)

    @classmethod
    def active(cls) -> Dict[str, Dict[str, Any]]:
        with cls._lock:
            result: Dict[str, Dict[str, Any]] = {}
            for provider, job_id in list(cls._active_by_provider.items()):
                job = cls._jobs.get(job_id)
                if job and job.get("status") in {"queued", "running"}:
                    result[provider] = dict(job)
            return result

    @classmethod
    def _run(cls, job_id: str, provider: str) -> None:
        cls._set(
            job_id,
            status="running",
            phase="preparing",
            progress=8,
            message="Preparando conexão…",
            started_at=cls._now(),
        )
        try:
            service = CloudHubService()
            credentials = service._credentials(provider)
            cls._set(job_id, phase="downloading", progress=20, message=f"Baixando QSOs do {provider}…")

            with adapter_for(provider, credentials) as adapter:
                result = adapter.fetch_all()

            records = result.get("records") or []
            metadata = result.get("metadata") or {}
            cls._set(
                job_id,
                phase="validating",
                progress=82,
                records=len(records),
                message=f"{len(records):,} QSOs recebidos. Validando…".replace(",", "."),
            )

            metadata.update({"source": "remote_api", "coverage": metadata.get("coverage") or "API_FULL_SYNC"})
            cls._set(job_id, phase="saving", progress=92, message="Salvando snapshot local…")
            summary = service.snapshots.save(provider, records, metadata)

            cls._set(
                job_id,
                status="succeeded",
                phase="done",
                progress=100,
                records=len(records),
                message=f"{provider} atualizado com {len(records):,} QSOs.".replace(",", "."),
                completed_at=cls._now(),
                snapshot=summary,
            )
        except Exception as exc:
            cls._set(
                job_id,
                status="failed",
                phase="failed",
                progress=100,
                message="Falha na sincronização.",
                error=str(exc),
                completed_at=cls._now(),
            )
        finally:
            with cls._lock:
                if cls._active_by_provider.get(provider) == job_id:
                    cls._active_by_provider.pop(provider, None)
