"""Safe orchestration for external integration adapters."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..adapters.qrz import QRZAdapter, QRZSafetyError
from ..adapters.wrl_udp import WRLUDPAdapter, WRLSafetyError
from ..core.config import settings
from ..models.models import (
    AuditEvent,
    AuditOperation,
    LogicalQSO,
    QueueStatus,
    SyncAttempt,
    SyncJob,
)


class IntegrationService:
    def __init__(self, db: Session):
        self.db = db

    def status(self) -> Dict[str, Any]:
        wrl_safe = True
        wrl_error: Optional[str] = None
        try:
            WRLUDPAdapter(settings.wrl_udp_host, settings.wrl_udp_port)
        except WRLSafetyError as exc:
            wrl_safe = False
            wrl_error = str(exc)
        return {
            "qrz": {
                "credentials_configured": settings.qrz_credentials_configured,
                "dry_run": True,
                "write_enabled": False,
                "live_transport": "locked",
                "safety": "fail_closed",
            },
            "wrl": {
                "host": settings.wrl_udp_host,
                "port": settings.wrl_udp_port,
                "enabled": settings.wrl_udp_enabled,
                "loopback_safe": wrl_safe,
                "error": wrl_error,
            },
        }

    def _qso(self, qso_uuid: str) -> LogicalQSO:
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
        if qso is None:
            raise LookupError("QSO not found")
        return qso

    def _assert_exact_qrz_locator(self, qso: LogicalQSO) -> None:
        if not qso.callsign or not qso.qso_date or not qso.time_on:
            raise QRZSafetyError("QRZ exact targeting requires CALL, QSO_DATE and TIME_ON")
        duplicates = self.db.query(LogicalQSO).filter(
            LogicalQSO.callsign == qso.callsign,
            LogicalQSO.qso_date == qso.qso_date,
            LogicalQSO.time_on == qso.time_on,
            LogicalQSO.uuid != qso.uuid,
        ).count()
        if duplicates:
            raise QRZSafetyError("Ambiguous QRZ locator: more than one logical QSO has the same CALL/QSO_DATE/TIME_ON")

    def qrz_preview(self, qso_uuid: str, operation: str = "replace") -> Dict[str, Any]:
        qso = self._qso(qso_uuid)
        self._assert_exact_qrz_locator(qso)
        plan = QRZAdapter().plan(qso, operation=operation)
        result = plan.as_dict()
        result.update({
            "qso_uuid": qso.uuid,
            "qso_identity_id": qso.qso_identity_id,
            "real_write_allowed": False,
            "backup_required_before_live_write": True,
            "verification_required_after_live_write": True,
        })
        return result

    def qrz_live_apply(self, qso_uuid: str, operation: str = "replace") -> None:
        # There is intentionally no condition that silently unlocks this path.
        # Real transport requires a future separately validated implementation.
        self.qrz_preview(qso_uuid, operation=operation)
        raise QRZSafetyError(
            "QRZ live writes are locked in this release. Dry-run preview is available and no network request was made."
        )

    def wrl_preview(self, qso_uuid: str) -> Dict[str, Any]:
        qso = self._qso(qso_uuid)
        plan = WRLUDPAdapter(settings.wrl_udp_host, settings.wrl_udp_port).plan(qso)
        result = plan.as_dict()
        result["qso_uuid"] = qso.uuid
        return result

    def wrl_send(self, qso_uuid: str, *, dry_run: bool = True) -> Dict[str, Any]:
        qso = self._qso(qso_uuid)
        adapter = WRLUDPAdapter(settings.wrl_udp_host, settings.wrl_udp_port)
        plan = adapter.plan(qso)

        job = SyncJob(
            destination="wrl",
            logical_qso_id=qso.id,
            operation="insert",
            status=QueueStatus.PENDING,
            dry_run=dry_run,
            result_data={"host": plan.host, "port": plan.port},
        )
        self.db.add(job)
        self.db.flush()

        if dry_run:
            job.status = QueueStatus.CONFIRMED
            result = {**plan.as_dict(), "qso_uuid": qso.uuid, "sent": False, "sync_job_id": job.id}
            job.result_data = result
            self.db.add(SyncAttempt(
                sync_job_id=job.id,
                attempt_number=1,
                status="dry_run",
                request_data={"host": plan.host, "port": plan.port, "payload": plan.payload},
                response_data={"sent": False},
                duration_ms=0,
            ))
        else:
            if not settings.wrl_udp_enabled:
                job.status = QueueStatus.FAILED
                job.error_message = "WRL UDP sending is disabled"
                self.db.commit()
                raise WRLSafetyError("WRL UDP sending is disabled; use dry_run or enable WRL_UDP_ENABLED explicitly")
            started = datetime.utcnow()
            try:
                bytes_sent = adapter.send(plan)
                duration_ms = max(0, int((datetime.utcnow() - started).total_seconds() * 1000))
                job.status = QueueStatus.CONFIRMED
                result = {
                    **plan.as_dict(), "dry_run": False, "qso_uuid": qso.uuid,
                    "sent": True, "bytes_sent": bytes_sent, "sync_job_id": job.id,
                }
                job.result_data = result
                self.db.add(SyncAttempt(
                    sync_job_id=job.id,
                    attempt_number=1,
                    status="sent",
                    request_data={"host": plan.host, "port": plan.port, "payload": plan.payload},
                    response_data={"bytes_sent": bytes_sent},
                    duration_ms=duration_ms,
                ))
            except Exception as exc:
                job.status = QueueStatus.FAILED
                job.error_message = str(exc)
                self.db.add(SyncAttempt(
                    sync_job_id=job.id,
                    attempt_number=1,
                    status="failed",
                    request_data={"host": plan.host, "port": plan.port},
                    error_message=str(exc),
                ))
                self.db.commit()
                raise

        self.db.add(AuditEvent(
            operation=AuditOperation.SYNC,
            entity_type="logical_qso",
            entity_id=qso.id,
            source="wrl_udp",
            after={"dry_run": dry_run, "host": plan.host, "port": plan.port},
            reason="WRL local UDP integration",
            result="success",
        ))
        self.db.commit()
        return result
