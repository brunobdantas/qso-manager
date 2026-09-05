"""Unified QSO Manager API inspired by task-based log management workflows."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services.qso_manager_activity import QSOManagerActivityStore
from ..services.qso_manager_bulk_jobs import QSOManagerBulkJobManager
from ..services.qso_manager_workspace import QSOManagerWorkspace

router = APIRouter(prefix="/api/qso-manager", tags=["qso-manager"])


class ExportRequest(BaseModel):
    logical_ids: List[str] = Field(min_length=1, max_length=50000)
    filename: Optional[str] = None


class BulkRequest(BaseModel):
    action: str
    logical_ids: List[str] = Field(min_length=1, max_length=10000)
    target: Optional[str] = None
    source: Optional[str] = None
    changes: Dict[str, Any] = Field(default_factory=dict)
    delete_source: bool = False


def _run(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _filters(
    q: str,
    call: str,
    band: str,
    mode: str,
    country: str,
    date_from: str,
    date_to: str,
    provider: str,
    missing_in: str,
    qrz: str,
    duplicate: Optional[str],
    differences: Optional[str],
    confirmed: Optional[str],
) -> Dict[str, Any]:
    return {
        "q": q, "call": call, "band": band, "mode": mode, "country": country,
        "date_from": date_from, "date_to": date_to, "provider": provider,
        "missing_in": missing_in, "qrz": qrz, "duplicate": duplicate,
        "differences": differences, "confirmed": confirmed,
    }


@router.get("/options", response_model=dict)
def options():
    return _run(lambda: QSOManagerWorkspace().options())


@router.get("/rows", response_model=dict)
def rows(
    q: str = "",
    call: str = "",
    band: str = "",
    mode: str = "",
    country: str = "",
    date_from: str = "",
    date_to: str = "",
    provider: str = "",
    missing_in: str = "",
    qrz: str = "",
    duplicate: Optional[str] = None,
    differences: Optional[str] = None,
    confirmed: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=10, le=500),
    sort: str = "date",
    direction: str = "desc",
):
    filters = _filters(q, call, band, mode, country, date_from, date_to, provider, missing_in, qrz, duplicate, differences, confirmed)
    return _run(lambda: QSOManagerWorkspace().query(page=page, page_size=page_size, sort=sort, direction=direction, **filters))


@router.get("/ids", response_model=dict)
def ids(
    q: str = "",
    call: str = "",
    band: str = "",
    mode: str = "",
    country: str = "",
    date_from: str = "",
    date_to: str = "",
    provider: str = "",
    missing_in: str = "",
    qrz: str = "",
    duplicate: Optional[str] = None,
    differences: Optional[str] = None,
    confirmed: Optional[str] = None,
    limit: int = Query(default=50000, ge=1, le=50000),
):
    filters = _filters(q, call, band, mode, country, date_from, date_to, provider, missing_in, qrz, duplicate, differences, confirmed)
    return _run(lambda: QSOManagerWorkspace().ids(limit=limit, **filters))


@router.get("/rows/{logical_id}", response_model=dict)
def row_detail(logical_id: str):
    return _run(lambda: QSOManagerWorkspace().get(logical_id))


@router.post("/export")
def export_selected(request: ExportRequest):
    try:
        content = QSOManagerWorkspace().export_adif(request.logical_ids)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = request.filename or f"PU2BRU-QSO-Manager-{stamp}.adi"
        filename = "".join(ch for ch in filename if ch.isalnum() or ch in "-_.") or f"qso-export-{stamp}.adi"
        QSOManagerActivityStore().append(
            "EXPORT",
            f"Exportados {len(request.logical_ids)} QSO(s) para ADIF",
            {"records": len(request.logical_ids), "filename": filename},
        )
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/bulk/preview", response_model=dict)
def bulk_preview(request: BulkRequest):
    return _run(lambda: QSOManagerWorkspace().plan_bulk(
        request.action,
        request.logical_ids,
        target=request.target,
        source=request.source,
        changes=request.changes,
        delete_source=request.delete_source,
    ))


@router.post("/bulk/jobs", response_model=dict)
def bulk_start(request: BulkRequest):
    return _run(lambda: QSOManagerBulkJobManager.start(
        action=request.action,
        logical_ids=request.logical_ids,
        target=request.target,
        source=request.source,
        changes=request.changes,
        delete_source=request.delete_source,
    ))


@router.get("/bulk/jobs/{job_id}", response_model=dict)
def bulk_job(job_id: str):
    return _run(lambda: QSOManagerBulkJobManager.get(job_id))


@router.get("/activity", response_model=List[dict])
def activity(limit: int = Query(default=200, ge=1, le=1000), kind: str = ""):
    return _run(lambda: QSOManagerActivityStore().list(limit=limit, kind=kind))
