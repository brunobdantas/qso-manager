"""Unified v9 product API consumed by Windows and mirrored by Android."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..adapters.cloud_logs import CloudProviderError
from ..services.v9_product_service import V9ProductService

router = APIRouter(prefix="/api/product", tags=["product-v9"])


class ConnectionRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class ADIFRequest(BaseModel):
    content: str
    filename: str = "source.adi"


class HRDLogPushRequest(BaseModel):
    confirm: bool = False
    limit: int = Field(default=500, ge=1, le=5000)


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
