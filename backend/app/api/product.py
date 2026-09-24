"""Unified product API for the Windows production application."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..adapters.cloud_logs import CloudProviderError
from ..services.award_master_service import AwardMasterError, AwardMasterService
from ..services.sync_job_service import SyncJobManager
from ..services.v9_product_service import V9ProductService

router = APIRouter(prefix="/api/product", tags=["product"])


class ConnectionRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class ADIFRequest(BaseModel):
    content: str
    filename: str = "source.adi"


class HRDLogPushRequest(BaseModel):
    confirm: bool = False
    limit: int = Field(default=500, ge=1, le=5000)


class EqslQrzApplyRequest(BaseModel):
    confirm: bool = False
    limit: int = Field(default=500, ge=1, le=500)


def _run(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CloudProviderError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/bootstrap")
def bootstrap():
    return _run(lambda: V9ProductService().bootstrap())


@router.get("/status")
def status():
    return _run(lambda: V9ProductService().status())


@router.get("/diagnostics")
def diagnostics():
    return _run(lambda: V9ProductService().diagnostics())


@router.get("/dashboard")
def dashboard():
    return _run(lambda: V9ProductService().dashboard())


@router.get("/issues")
def issues(limit: int = Query(default=250, ge=1, le=1000)):
    return _run(lambda: V9ProductService().issues(limit=limit))


@router.get("/qsl")
def qsl():
    return _run(lambda: V9ProductService().qsl_analysis())


@router.get("/qsl/eqsl-qrz/plan")
def eqsl_qrz_plan(refresh: bool = Query(default=False)):
    return _run(lambda: V9ProductService().eqsl_qrz_plan(refresh=refresh))


@router.post("/qsl/eqsl-qrz/apply")
def eqsl_qrz_apply(request: EqslQrzApplyRequest):
    return _run(lambda: V9ProductService().eqsl_qrz_apply(
        confirm=request.confirm,
        limit=request.limit,
    ))


@router.get("/log")
def log(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=10, le=500),
    q: str = "",
    call: str = "",
    band: str = "",
    mode: str = "",
    country: str = "",
    provider: str = "",
    missing_in: str = "",
    qrz: str = "",
    duplicate: str = "",
    differences: str = "",
    confirmed: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "date",
    direction: str = "desc",
):
    return _run(lambda: V9ProductService().log(
        page=page,
        page_size=page_size,
        q=q,
        call=call,
        band=band,
        mode=mode,
        country=country,
        provider=provider,
        missing_in=missing_in,
        qrz=qrz,
        duplicate=duplicate,
        differences=differences,
        confirmed=confirmed,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        direction=direction,
    ))


@router.get("/log/{logical_id}")
def log_detail(logical_id: str):
    return _run(lambda: V9ProductService()._workspace().get(logical_id))


@router.put("/connections/{provider}")
def configure(provider: str, request: ConnectionRequest):
    return _run(lambda: V9ProductService().configure(provider, request.values))


@router.delete("/connections/{provider}")
def disconnect(provider: str):
    return _run(lambda: V9ProductService().disconnect(provider))


@router.post("/connections/{provider}/test")
def test(provider: str):
    return _run(lambda: V9ProductService().test(provider))


@router.post("/sync/{provider}")
def sync(provider: str):
    return _run(lambda: V9ProductService().sync(provider))


@router.post("/sync-all")
def sync_all():
    return _run(lambda: V9ProductService().sync_all())


@router.post("/sync-jobs/{provider}")
def sync_job_start(provider: str):
    return _run(lambda: SyncJobManager.start(provider))


@router.post("/sync-jobs-all")
def sync_jobs_all():
    return _run(SyncJobManager.start_all)


@router.get("/sync-jobs-active")
def sync_jobs_active():
    return _run(SyncJobManager.active)


@router.get("/sync-jobs/{job_id}")
def sync_job_get(job_id: str):
    return _run(lambda: SyncJobManager.get(job_id))


@router.put("/sources/{provider}/adif")
def import_adif(provider: str, request: ADIFRequest):
    return _run(lambda: V9ProductService().import_local_adif(provider, request.content, request.filename))


@router.delete("/sources/{provider}/snapshot")
def clear_snapshot(provider: str):
    return _run(lambda: V9ProductService().clear_snapshot(provider))


@router.get("/hrdlog/plan")
def hrdlog_plan(limit: int = Query(default=500, ge=1, le=5000)):
    return _run(lambda: V9ProductService().hrdlog_plan(limit=limit))


@router.post("/hrdlog/push")
def hrdlog_push(request: HRDLogPushRequest):
    return _run(lambda: V9ProductService().push_hrdlog_missing(confirm=request.confirm, limit=request.limit))


MAX_AWARD_ADIF_BYTES = 80 * 1024 * 1024


async def _read_award_adif(upload: UploadFile, label: str) -> str:
    data = await upload.read(MAX_AWARD_ADIF_BYTES + 1)
    if not data:
        raise HTTPException(status_code=409, detail=f"O arquivo {label} está vazio")
    if len(data) > MAX_AWARD_ADIF_BYTES:
        raise HTTPException(status_code=413, detail=f"O arquivo {label} excede 80 MB")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=409, detail=f"Não foi possível decodificar o arquivo {label}") from exc


@router.post("/award-master/preview")
async def award_master_preview(
    qrz: UploadFile = File(...),
    lotw: UploadFile = File(...),
):
    try:
        qrz_text = await _read_award_adif(qrz, "QRZ")
        lotw_text = await _read_award_adif(lotw, "LoTW")
        result = AwardMasterService().build(qrz_text, lotw_text)
        return {
            **result["report"],
            "filenames": {
                "QRZ": (qrz.filename or "qrz.adi")[:255],
                "LOTW": (lotw.filename or "lotw.adi")[:255],
            },
        }
    except AwardMasterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/award-master/export")
async def award_master_export(
    qrz: UploadFile = File(...),
    lotw: UploadFile = File(...),
):
    try:
        qrz_text = await _read_award_adif(qrz, "QRZ")
        lotw_text = await _read_award_adif(lotw, "LoTW")
        result = AwardMasterService().certified_export(qrz_text, lotw_text)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"PU2BRU-UltimateAAC-MASTER-{stamp}.adi"
        return Response(
            content=result["content"],
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-QSO-Manager-Master-SHA256": result["report"]["master_sha256"],
                "X-QSO-Manager-Certification": result["report"]["certification"],
            },
        )
    except AwardMasterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/award-master/audit")
async def award_master_audit(
    qrz: UploadFile = File(...),
    lotw: UploadFile = File(...),
):
    try:
        qrz_text = await _read_award_adif(qrz, "QRZ")
        lotw_text = await _read_award_adif(lotw, "LoTW")
        service = AwardMasterService()
        result = service.build(qrz_text, lotw_text)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return Response(
            content=service.audit_csv(result),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="PU2BRU-Award-Master-audit-{stamp}.csv"'},
        )
    except AwardMasterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
