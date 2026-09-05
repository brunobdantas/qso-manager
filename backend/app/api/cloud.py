"""Connected logbook API for QRZ, WRL, Club Log and eQSL."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..adapters.cloud_logs import CloudProviderError
from ..services.cloud_hub_fast_service import CloudHubService

router = APIRouter(prefix="/api/cloud", tags=["cloud-logbooks"])


class ConnectionRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class PublishRequest(BaseModel):
    source: str
    index: int = Field(ge=0)
    target: str
    confirm: bool = False


class RemoteUpdateRequest(BaseModel):
    index: int = Field(ge=0)
    changes: Dict[str, Any]
    confirm: bool = False


class RemoteDeleteRequest(BaseModel):
    index: int = Field(ge=0)
    confirm: bool = False


def _run(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CloudProviderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/status", response_model=dict)
def status():
    return _run(lambda: CloudHubService().status())


@router.put("/connections/{provider}", response_model=dict)
def configure_connection(provider: str, request: ConnectionRequest):
    return _run(lambda: CloudHubService().configure(provider, request.values))


@router.delete("/connections/{provider}", response_model=dict)
def disconnect(provider: str):
    return _run(lambda: CloudHubService().disconnect(provider))


@router.delete("/snapshots/{provider}", response_model=dict)
def clear_local_snapshot(provider: str):
    """Delete only the active local snapshot. Remote data and credentials stay untouched."""
    return _run(lambda: CloudHubService().clear_snapshot(provider))


@router.post("/connections/{provider}/test", response_model=dict)
def test_connection(provider: str):
    return _run(lambda: CloudHubService().test(provider))


@router.post("/sync/{provider}", response_model=dict)
def sync_provider(provider: str):
    return _run(lambda: CloudHubService().sync(provider))


@router.post("/sync-all", response_model=dict)
def sync_all():
    return _run(lambda: CloudHubService().sync_all())


@router.get("/analysis", response_model=dict)
def analysis():
    return _run(lambda: CloudHubService().analysis())


@router.get("/search", response_model=dict)
def search(call: str = "", limit: int = Query(default=200, ge=1, le=2000)):
    return _run(lambda: CloudHubService().search(call=call, limit=limit))


@router.get("/record/{provider}/{index}", response_model=dict)
def get_record(provider: str, index: int):
    return _run(lambda: CloudHubService().record(provider, index))


@router.post("/publish", response_model=dict)
def publish(request: PublishRequest):
    return _run(lambda: CloudHubService().publish(request.source, request.index, request.target, request.confirm))


@router.post("/remote/{provider}/update", response_model=dict)
def remote_update(provider: str, request: RemoteUpdateRequest):
    return _run(lambda: CloudHubService().update_remote(provider, request.index, request.changes, request.confirm))


@router.post("/remote/{provider}/delete", response_model=dict)
def remote_delete(provider: str, request: RemoteDeleteRequest):
    return _run(lambda: CloudHubService().delete_remote(provider, request.index, request.confirm))
