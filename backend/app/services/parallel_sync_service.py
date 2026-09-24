"""Parallel remote-source synchronization with observable progress.

The coordinator keeps the existing provider adapters and snapshot safety model,
but runs independent read-only downloads concurrently. A job is observable via
polling so the desktop can render overall and per-provider progress instead of
blocking on one long request.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from .qso_manager_workspace import QSOManagerWorkspace
from .v9_product_service import V9ProductService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ParallelSyncCoordinator:
    """Coordinate one active all-source synchronization at a time."""

    MAX_HISTORY = 20

    def __init__(
        self,
        service_factory: Callable[[], V9ProductService] = V9ProductService,
        max_workers: int = 6,
    ) -> None:
        self.service_factory = service_factory
        self.max_workers = max(1, int(max_workers))
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._active_job_id: Optional[str] = None

    def start(self) -> Dict[str, Any]:
        with self._lock:
            if self._active_job_id:
                active = self._jobs.get(self._active_job_id)
                if active and active.get("status") in {"queued", "running"}:
                    return copy.deepcopy(active)

            service = self.service_factory()
            status = service.status()
            provider_rows = {
                row["provider"]: row
                for row in status.get("providers", [])
            }
            sync_order = list(service.SYNC_PROVIDERS)

            providers: Dict[str, Dict[str, Any]] = {}
            configured_targets = []
            for provider in sync_order:
                row = provider_rows.get(provider) or {}
                configured = bool(row.get("configured"))
                item = {
                    "provider": provider,
                    "label": row.get("label") or provider,
                    "configured": configured,
                    "status": "queued" if configured else "skipped",
                    "records": None,
                    "error": None,
                    "started_at": None,
                    "finished_at": _now() if not configured else None,
                    "duration_ms": 0 if not configured else None,
                }
                providers[provider] = item
                if configured:
                    configured_targets.append(provider)

            job_id = uuid.uuid4().hex
            total = len(configured_targets)
            job = {
                "job_id": job_id,
                "status": "queued" if total else "completed",
                "created_at": _now(),
                "started_at": None,
                "finished_at": _now() if not total else None,
                "total": total,
                "completed": 0,
                "succeeded": 0,
                "failed": 0,
                "progress": 100 if not total else 0,
                "parallelism": min(self.max_workers, total) if total else 0,
                "providers": providers,
                "results": [],
            }
            self._jobs[job_id] = job
            self._active_job_id = job_id if total else None
            self._trim_history_locked()

        if total:
            thread = threading.Thread(
                target=self._run_job,
                args=(job_id, configured_targets),
                name=f"qso-sync-{job_id[:8]}",
                daemon=True,
            )
            thread.start()

        return self.get(job_id)

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                raise LookupError("Synchronization job not found")
            return copy.deepcopy(job)

    def active(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._active_job_id:
                return None
            job = self._jobs.get(self._active_job_id)
            if not job:
                return None
            return copy.deepcopy(job)

    def _run_job(self, job_id: str, providers: list[str]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            job["started_at"] = _now()

        workers = min(self.max_workers, max(1, len(providers)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qso-provider") as executor:
            futures = {executor.submit(self._sync_one, job_id, provider): provider for provider in providers}
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # _sync_one should already normalize, defensive only.
                    result = {
                        "provider": provider,
                        "ok": False,
                        "error": str(exc),
                    }
                self._finish_provider(job_id, provider, result)

        QSOManagerWorkspace.invalidate_cache()
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "completed_with_errors" if job["failed"] else "completed"
            job["progress"] = 100
            job["finished_at"] = _now()
            if self._active_job_id == job_id:
                self._active_job_id = None

    def _sync_one(self, job_id: str, provider: str) -> Dict[str, Any]:
        start = time.monotonic()
        with self._lock:
            item = self._jobs[job_id]["providers"][provider]
            item["status"] = "running"
            item["started_at"] = _now()

        try:
            result = self.service_factory().sync(provider)
            return {
                "provider": provider,
                "ok": True,
                "records": int(result.get("records") or 0),
                "result": result,
                "duration_ms": int((time.monotonic() - start) * 1000),
            }
        except Exception as exc:
            return {
                "provider": provider,
                "ok": False,
                "error": str(exc),
                "duration_ms": int((time.monotonic() - start) * 1000),
            }

    def _finish_provider(self, job_id: str, provider: str, result: Dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            item = job["providers"][provider]
            ok = bool(result.get("ok"))
            item["status"] = "success" if ok else "failed"
            item["records"] = result.get("records")
            item["error"] = result.get("error")
            item["duration_ms"] = int(result.get("duration_ms") or 0)
            item["finished_at"] = _now()

            job["completed"] += 1
            if ok:
                job["succeeded"] += 1
            else:
                job["failed"] += 1
            job["progress"] = min(
                100,
                round((job["completed"] / max(1, job["total"])) * 100),
            )
            job["results"].append({
                "provider": provider,
                "ok": ok,
                "records": item["records"],
                "error": item["error"],
                "duration_ms": item["duration_ms"],
            })

    def _trim_history_locked(self) -> None:
        if len(self._jobs) <= self.MAX_HISTORY:
            return
        removable = [
            (job.get("created_at") or "", job_id)
            for job_id, job in self._jobs.items()
            if job_id != self._active_job_id and job.get("status") not in {"queued", "running"}
        ]
        removable.sort()
        while len(self._jobs) > self.MAX_HISTORY and removable:
            _created, job_id = removable.pop(0)
            self._jobs.pop(job_id, None)


parallel_sync = ParallelSyncCoordinator()
