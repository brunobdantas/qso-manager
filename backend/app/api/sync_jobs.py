"""Background synchronization endpoints for progress-aware desktop UX."""
from fastapi import APIRouter, HTTPException

from ..adapters.cloud_logs import CloudProviderError
from ..services.sync_job_service import SyncJobManager

router = APIRouter(prefix="/api/cloud/sync-jobs", tags=["cloud-logbooks"])


def _run(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CloudProviderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{provider}", response_model=dict)
def start_sync_job(provider: str):
    return _run(lambda: SyncJobManager.start(provider))


@router.get("/{job_id}", response_model=dict)
def get_sync_job(job_id: str):
    return _run(lambda: SyncJobManager.get(job_id))


@router.get("", response_model=dict)
def active_sync_jobs():
    return {"active": SyncJobManager.active()}
