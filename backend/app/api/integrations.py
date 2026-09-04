"""Safe integration API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..adapters.qrz import QRZSafetyError
from ..adapters.wrl_udp import WRLSafetyError
from ..db.database import get_db
from ..services.integration_service import IntegrationService

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class QRZPreviewRequest(BaseModel):
    operation: str = "replace"


class WRLSendRequest(BaseModel):
    dry_run: bool = True


@router.get("/status", response_model=dict)
def integration_status(db: Session = Depends(get_db)):
    return IntegrationService(db).status()


@router.post("/qrz/preview/{qso_uuid}", response_model=dict)
def qrz_preview(qso_uuid: str, request: QRZPreviewRequest, db: Session = Depends(get_db)):
    try:
        return IntegrationService(db).qrz_preview(qso_uuid, operation=request.operation)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QRZSafetyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/qrz/apply/{qso_uuid}", response_model=dict)
def qrz_apply(qso_uuid: str, request: QRZPreviewRequest, db: Session = Depends(get_db)):
    try:
        IntegrationService(db).qrz_live_apply(qso_uuid, operation=request.operation)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QRZSafetyError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    raise HTTPException(status_code=423, detail="QRZ live writes are locked")


@router.post("/wrl/preview/{qso_uuid}", response_model=dict)
def wrl_preview(qso_uuid: str, db: Session = Depends(get_db)):
    try:
        return IntegrationService(db).wrl_preview(qso_uuid)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WRLSafetyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/wrl/send/{qso_uuid}", response_model=dict)
def wrl_send(qso_uuid: str, request: WRLSendRequest, db: Session = Depends(get_db)):
    try:
        return IntegrationService(db).wrl_send(qso_uuid, dry_run=request.dry_run)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WRLSafetyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
