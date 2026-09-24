"""Parallel background synchronization jobs with user-visible progress.

The desktop application is a single local process, so a small in-memory job
registry is enough. Every provider runs in its own daemon thread; remote
downloads are read-only and snapshots are replaced only after a complete,
validated fetch succeeds.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from .qso_manager_workspace import QSOManagerWorkspace
from .v9_product_service import V9ProductService


class SyncJobManager:
    _lock = threading.RLock()
    _jobs: Dict[str, Dict[str, Any]] = {}
    _active_by_provider: Dict[str, str] = {}
    _max_history = 200

    @classmethod
    def _now(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _copy(cls, job: Dict[str, Any]) -> Dict[str, Any]:
        return {**job, "snapshot": dict(job.get("snapshot") or {})}

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
                (job_id, job) for job_id, job in cls._jobs.items()
                if job.get("status") in {"succeeded", "failed"}
            ]
            finished.sort(key=lambda pair: pair[1].get("completed_at") or pair[1].get("created_at") or "")
            for job_id, _job in finished[: max(0, len(cls._jobs) - cls._max_history)]:
                cls._jobs.pop(job_id, None)

    @classmethod
    def start(cls, provider: str) -> Dict[str, Any]:
        service = V9ProductService()
        provider = service._normalize_provider(provider)
        if provider not in service.SYNC_PROVIDERS:
            raise ValueError(f"{provider} não possui download remoto completo")
        if not service._configured(provider):
            raise ValueError(f"{provider} não está configurado")

        with cls._lock:
            active_id = cls._active_by_provider.get(provider)
            if active_id:
                active = cls._jobs.get(active_id)
                if active and active.get("status") in {"queued", "running"}:
                    return cls._copy(active)

            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "provider": provider,
                "status": "queued",
                "phase": "queued",
                "progress": 0,
                "message": "Na fila para atualização…",
                "records": None,
                "created_at": cls._now(),
                "started_at": None,
                "completed_at": None,
                "error": None,
                "snapshot": None,
                "remote_write": False,
            }
            cls._jobs[job_id] = job
            cls._active_by_provider[provider] = job_id

        threading.Thread(
            target=cls._run,
            args=(job_id, provider),
            daemon=True,
            name=f"qso-source-sync-{provider.lower()}",
        ).start()
        cls._trim()
        return cls._copy(job)

    @classmethod
    def start_all(cls) -> Dict[str, Any]:
        service = V9ProductService()
        configured: List[str] = []
        skipped: List[Dict[str, str]] = []
        for provider in service.SYNC_PROVIDERS:
            if service._configured(provider):
                configured.append(provider)
            else:
                skipped.append({"provider": provider, "reason": "not_configured"})

        jobs = [cls.start(provider) for provider in configured]
        return {
            "parallel": True,
            "jobs": jobs,
            "started": len(jobs),
            "skipped": skipped,
            "providers": configured,
        }

    @classmethod
    def get(cls, job_id: str) -> Dict[str, Any]:
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                raise LookupError("Sync job not found")
            return cls._copy(job)

    @classmethod
    def active(cls) -> Dict[str, Dict[str, Any]]:
        with cls._lock:
            result: Dict[str, Dict[str, Any]] = {}
            for provider, job_id in list(cls._active_by_provider.items()):
                job = cls._jobs.get(job_id)
                if job and job.get("status") in {"queued", "running"}:
                    result[provider] = cls._copy(job)
            return result

    @classmethod
    def _run(cls, job_id: str, provider: str) -> None:
        cls._set(
            job_id,
            status="running",
            phase="connecting",
            progress=8,
            message="Conectando…",
            started_at=cls._now(),
        )
        try:
            service = V9ProductService()
            cls._set(
                job_id,
                phase="downloading",
                progress=18,
                message=f"Baixando dados do {service.LABELS.get(provider, provider)}…",
            )

            with service._adapter(provider) as adapter:
                result = adapter.fetch_all()

            records = result.get("records") or []
            metadata = dict(result.get("metadata") or {})
            cls._set(
                job_id,
                phase="validating",
                progress=82,
                records=len(records),
                message=f"{len(records):,} registros recebidos. Validando…".replace(",", "."),
            )

            metadata.setdefault("coverage", "API_FULL_SYNC")
            metadata.setdefault("source", "remote_api")
            cls._set(job_id, phase="saving", progress=93, message="Salvando cópia local segura…")
            summary = service.snapshots.save(provider, records, metadata)
            QSOManagerWorkspace.invalidate_cache()

            cls._set(
                job_id,
                status="succeeded",
                phase="done",
                progress=100,
                records=len(records),
                snapshot=summary,
                message=f"{service.LABELS.get(provider, provider)} atualizado: {len(records):,} registros.".replace(",", "."),
                completed_at=cls._now(),
            )
        except Exception as exc:
            cls._set(
                job_id,
                status="failed",
                phase="failed",
                progress=100,
                message="Falha na atualização. O snapshot anterior foi preservado.",
                error=str(exc),
                completed_at=cls._now(),
            )
        finally:
            with cls._lock:
                if cls._active_by_provider.get(provider) == job_id:
                    cls._active_by_provider.pop(provider, None)
