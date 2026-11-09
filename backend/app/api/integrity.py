"""Explainable, QRZ-led integrity and safe assisted corrections."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.integrity_service import IntegrityService, IntegrityStore
from ..services.integrity_monitor import IntegrityMonitor
from ..services.qso_manager_activity import QSOManagerActivityStore
from ..services.qso_manager_bulk_jobs import QSOManagerBulkJobManager

router = APIRouter(prefix="/api/integrity", tags=["integrity"])


def _run(fn):
    try:
        return fn()
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class DecisionRequest(BaseModel):
    case_key: str = Field(min_length=8, max_length=128)
    provider: str
    decision: str
    reason: str = Field(min_length=5, max_length=4000)
    evidence: Dict[str, Any] = Field(default_factory=dict)


class AssistedApplyRequest(BaseModel):
    target: str
    signature: str = Field(min_length=8, max_length=128)
    logical_ids: List[str] = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=5, max_length=4000)
    confirm: bool = False


class MonitorRequest(BaseModel):
    enabled: bool = False
    interval_hours: int = Field(default=12, ge=6, le=168)


@router.get("/report")
def report(page: int = Query(1, ge=1), page_size: int = Query(50, ge=10, le=200),
           provider: str = "", kind: str = "", q: str = ""):
    return _run(lambda: IntegrityService().report(page, page_size, provider, kind, q))


@router.get("/qsl-dxcc")
def qsl_dxcc(limit: int = Query(100, ge=1, le=1000)):
    return _run(lambda: IntegrityService().qsl_opportunities(limit))


@router.get("/history")
def history(limit: int = Query(100, ge=1, le=500)):
    return _run(lambda: {
        "decisions": IntegrityStore().history(limit),
        "scans": IntegrityStore().scans(25),
        "actions": QSOManagerActivityStore().list(limit=limit),
        "provider_errors": IntegrityStore().errors(),
    })


@router.post("/decision")
def decide(request: DecisionRequest):
    def execute():
        service = IntegrityService()
        analysis = service._cached_analysis()
        matches = [
            c for c in analysis["cases"]
            if c["case_key"] == request.case_key and c["provider"] == request.provider.upper()
        ]
        if not matches:
            raise ValueError("A ocorrência não existe no snapshot atual; atualize o diagnóstico")
        case = matches[0]
        evidence = {
            "case": {k: case.get(k) for k in ("kind", "call", "date", "time", "band", "mode", "field", "reason")},
            "user_evidence": request.evidence,
            "signature": analysis["signature"],
        }
        result = service.store.decide(request.case_key, request.provider, request.decision, request.reason, evidence)
        QSOManagerActivityStore().append(
            "INTEGRITY_DECISION", request.decision,
            {"case_key": request.case_key, "provider": request.provider, "reason": request.reason})
        return result
    return _run(execute)


@router.get("/plan/{provider}")
def plan(provider: str, limit: int = Query(100, ge=1, le=1000)):
    return _run(lambda: IntegrityService().reconcile_plan(provider, limit))


@router.post("/apply")
def apply(request: AssistedApplyRequest):
    def execute():
        if not request.confirm:
            raise ValueError("Confirmação explícita necessária; nenhuma gravação foi iniciada")
        service = IntegrityService()
        analysis = service._cached_analysis()
        if request.signature != analysis["signature"]:
            raise ValueError("Os snapshots mudaram desde a prévia. Gere novo plano antes de aplicar")
        target = request.target.upper()
        candidates = {
            case["logical_id"] for case in analysis["cases"]
            if case["provider"] == target and case["kind"] == "MISSING" and case["actionable"]
        }
        selected = list(dict.fromkeys(request.logical_ids))
        if not candidates or not set(selected).issubset(candidates):
            raise ValueError("Seleção contém QSO não elegível para inclusão segura")
        plan = service.workspace.plan_bulk("PUBLISH", selected, target=target, source="QRZ")
        if plan["actionable"] != len(selected):
            raise ValueError("A prévia do provedor não permite incluir todos os QSOs selecionados")
        job = QSOManagerBulkJobManager.start(
            action="PUBLISH", logical_ids=selected, target=target, source="QRZ"
        )
        QSOManagerActivityStore().append(
            "ASSISTED_RECONCILIATION",
            "Correção QRZ → " + target,
            {"job_id": job["job_id"], "records": len(selected), "reason": request.reason,
             "snapshot_signature": request.signature, "source": "QRZ", "target": target})
        return job
    return _run(execute)


@router.get("/monitor")
def monitor():
    return _run(IntegrityMonitor.snapshot_status)


@router.put("/monitor")
def monitor_config(request: MonitorRequest):
    return _run(lambda: IntegrityMonitor.configure(request.enabled, request.interval_hours))


@router.post("/monitor/check")
def monitor_check():
    return _run(lambda: {
        "report": IntegrityService().report(page=1, page_size=10)["summary"],
        "status": IntegrityMonitor.snapshot_status(),
    })
