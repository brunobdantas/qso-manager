"""Background bulk actions for the unified QSO Manager.

Remote mutations are intentionally routed through CloudHubService so every
provider keeps its existing safety policy.  Jobs continue after an individual
record error and expose progress/results to the local browser UI.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .cloud_hub_fast_service import CloudHubService
from .qso_manager_activity import QSOManagerActivityStore
from .qso_manager_workspace import QSOManagerWorkspace


class QSOManagerBulkJobManager:
    _lock = threading.RLock()
    _jobs: Dict[str, Dict[str, Any]] = {}
    _max_history = 100

    @classmethod
    def _now(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _set(cls, job_id: str, **changes: Any) -> None:
        with cls._lock:
            if job_id in cls._jobs:
                cls._jobs[job_id].update(changes)

    @classmethod
    def get(cls, job_id: str) -> Dict[str, Any]:
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                raise LookupError("Bulk job not found")
            return dict(job)

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
            for job_id, _ in finished[: max(0, len(cls._jobs) - cls._max_history)]:
                cls._jobs.pop(job_id, None)

    @classmethod
    def start(
        cls,
        *,
        action: str,
        logical_ids: Sequence[str],
        target: Optional[str] = None,
        source: Optional[str] = None,
        changes: Optional[Dict[str, Any]] = None,
        delete_source: bool = False,
    ) -> Dict[str, Any]:
        workspace = QSOManagerWorkspace()
        plan = workspace.plan_bulk(
            action, logical_ids, target=target, source=source,
            changes=changes, delete_source=delete_source,
        )
        if plan["actionable"] <= 0:
            raise ValueError("Nenhum QSO selecionado pode executar esta ação")

        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "action": plan["action"],
            "target": plan.get("target"),
            "source": plan.get("source"),
            "delete_source": bool(plan.get("delete_source")),
            "changes": plan.get("changes") or {},
            "selected": plan["selected"],
            "actionable": plan["actionable"],
            "status": "queued",
            "phase": "queued",
            "progress": 0,
            "processed": 0,
            "succeeded": 0,
            "skipped": plan["skipped"],
            "failed": 0,
            "message": "Aguardando início…",
            "errors": [],
            "results": [],
            "created_at": cls._now(),
            "started_at": None,
            "completed_at": None,
        }
        with cls._lock:
            cls._jobs[job_id] = job
        thread = threading.Thread(
            target=cls._run,
            args=(job_id, list(dict.fromkeys(logical_ids))),
            daemon=True,
            name=f"qso-bulk-{plan['action'].lower()}",
        )
        thread.start()
        cls._trim()
        return dict(job)

    @classmethod
    def _run(cls, job_id: str, logical_ids: List[str]) -> None:
        cls._set(job_id, status="running", phase="executing", progress=2, started_at=cls._now(), message="Executando ação em lote…")
        activity = QSOManagerActivityStore()
        started = cls.get(job_id)
        activity.append(
            "BULK_START",
            f"{started['action']} em {started['actionable']} QSO(s)",
            {k: started.get(k) for k in ("job_id", "action", "source", "target", "delete_source", "changes", "selected", "actionable")},
        )
        modified_providers = set()
        processed = succeeded = failed = 0
        errors: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []

        try:
            hub = CloudHubService()
            workspace = QSOManagerWorkspace(hub=hub)
            job = cls.get(job_id)
            action = job["action"]
            target = job.get("target")
            source = job.get("source")
            delete_source = bool(job.get("delete_source"))
            changes = dict(job.get("changes") or {})
            total = max(1, int(job.get("actionable") or 1))

            for logical_id in logical_ids:
                try:
                    row = workspace._raw(logical_id)
                    refs = row["refs"]
                    result: Dict[str, Any]
                    actionable = True

                    if action == "PUBLISH":
                        if not target or target in refs:
                            actionable = False
                            result = {"logical_id": logical_id, "status": "skipped", "reason": "target already present"}
                        else:
                            src, src_index = workspace.canonical_ref(logical_id, preferred_source=source)
                            result = hub.publish(src, src_index, target, confirm=True)
                            modified_providers.add(target)
                    elif action == "UPDATE":
                        if not target or target not in refs:
                            actionable = False
                            result = {"logical_id": logical_id, "status": "skipped", "reason": "target not present"}
                        else:
                            result = hub.update_remote(target, int(refs[target]), changes, confirm=True)
                            modified_providers.add(target)
                    elif action == "DELETE":
                        if not target or target not in refs:
                            actionable = False
                            result = {"logical_id": logical_id, "status": "skipped", "reason": "target not present"}
                        else:
                            result = hub.delete_remote(target, int(refs[target]), confirm=True)
                            modified_providers.add(target)
                    elif action == "MOVE":
                        if not source or not target or source not in refs or target in refs:
                            actionable = False
                            result = {"logical_id": logical_id, "status": "skipped", "reason": "route not applicable"}
                        else:
                            publish_result = hub.publish(source, int(refs[source]), target, confirm=True)
                            modified_providers.add(target)
                            delete_result = None
                            if delete_source:
                                delete_result = hub.delete_remote(source, int(refs[source]), confirm=True)
                                modified_providers.add(source)
                            result = {"ok": True, "publish": publish_result, "delete": delete_result}
                    else:
                        raise ValueError(f"Unsupported bulk action {action}")

                    if actionable:
                        succeeded += 1
                    results.append({"logical_id": logical_id, "result": result})
                except Exception as exc:
                    failed += 1
                    errors.append({"logical_id": logical_id, "error": str(exc)})

                processed += 1
                pct = min(88, 4 + round((processed / max(len(logical_ids), 1)) * 84))
                cls._set(
                    job_id,
                    processed=processed,
                    succeeded=succeeded,
                    failed=failed,
                    progress=pct,
                    message=f"Processados {processed}/{len(logical_ids)} QSOs…",
                    errors=errors[-100:],
                    results=results[-100:],
                )

            if modified_providers:
                cls._set(job_id, phase="resync", progress=90, message="Atualizando snapshots das plataformas alteradas…")
                for provider in sorted(modified_providers):
                    if hub.credentials.configured(provider):
                        try:
                            hub.sync(provider)
                        except Exception as exc:
                            errors.append({"provider": provider, "error": f"re-sync: {exc}"})
                            failed += 1
                QSOManagerWorkspace.invalidate_cache()

            status = "succeeded"
            summary = f"{succeeded} concluído(s), {failed} erro(s)."
            cls._set(
                job_id,
                status=status,
                phase="done",
                progress=100,
                processed=processed,
                succeeded=succeeded,
                failed=failed,
                message=summary,
                errors=errors[-100:],
                results=results[-100:],
                completed_at=cls._now(),
            )
            activity.append(
                "BULK_COMPLETE",
                f"{job['action']}: {summary}",
                {"job_id": job_id, "source": source, "target": target, "processed": processed, "succeeded": succeeded, "failed": failed, "errors": errors[:20]},
                status="OK" if failed == 0 else "PARTIAL",
            )
        except Exception as exc:
            cls._set(
                job_id,
                status="failed",
                phase="failed",
                progress=100,
                message="Falha na operação em lote.",
                errors=(errors + [{"error": str(exc)}])[-100:],
                completed_at=cls._now(),
            )
            activity.append("BULK_FAILED", f"Falha: {exc}", {"job_id": job_id}, status="ERROR")
