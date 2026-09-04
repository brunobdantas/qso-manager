"""API routes for QSO operations."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models.models import Divergence, LogicalQSO, NormalizedQSO
from ..schemas.schemas import (
    DivergenceResponse,
    LogicalQSODetail,
    LogicalQSOResponse,
    NormalizedQSOFull,
)
from ..services.divergence_resolution_service import DivergenceResolutionService
from ..services.safe_update_service import SafeUpdateService

router = APIRouter(prefix="/api/qsos", tags=["qsos"])


class QSOUpdateRequest(BaseModel):
    changes: Dict[str, Any]
    reason: str = Field(default="Manual update from local UI", min_length=1)


class DivergenceResolveRequest(BaseModel):
    resolved_value: str
    reason: str = Field(default="Manual resolution from local UI", min_length=1)
    status: str = "resolved"


@router.get("", response_model=List[LogicalQSOResponse])
def get_qsos(
    skip: int = 0,
    limit: int = 100,
    callsign: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    band: Optional[str] = None,
    mode: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(LogicalQSO)
    if callsign:
        query = query.filter(LogicalQSO.callsign.ilike(f"%{callsign}%"))
    if date_from:
        query = query.filter(LogicalQSO.qso_date >= date_from)
    if date_to:
        query = query.filter(LogicalQSO.qso_date <= date_to)
    if band:
        query = query.filter(LogicalQSO.band == band.upper())
    if mode:
        query = query.filter(
            (LogicalQSO.mode == mode.upper()) |
            (LogicalQSO.operating_mode == mode.upper())
        )
    return query.order_by(LogicalQSO.qso_date.desc(), LogicalQSO.time_on.desc()).offset(skip).limit(limit).all()


@router.get("/divergences", response_model=List[DivergenceResponse])
def get_divergences(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Divergence)
    if status:
        query = query.filter(Divergence.status == status)
    return query.order_by(Divergence.created_at.desc()).all()


@router.post("/divergences/{divergence_id}/resolve", response_model=dict)
def resolve_divergence(
    divergence_id: int,
    request: DivergenceResolveRequest,
    db: Session = Depends(get_db),
):
    try:
        resolution = DivergenceResolutionService(db).resolve_divergence(
            divergence_id,
            resolved_value=request.resolved_value,
            reason=request.reason,
            status=request.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if resolution is None:
        raise HTTPException(status_code=404, detail="Divergence not found")
    return {
        "status": resolution.status,
        "resolved_value": resolution.resolved_value,
        "reason": resolution.reason,
        "divergence_key": resolution.divergence_key,
    }


@router.get("/normalized", response_model=List[NormalizedQSOFull])
def get_normalized_qsos(
    skip: int = 0,
    limit: int = 100,
    source_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(NormalizedQSO)
    if source_id:
        query = query.filter(NormalizedQSO.source_id == source_id)
    return query.offset(skip).limit(limit).all()


@router.get("/uuid/{qso_uuid}", response_model=LogicalQSODetail)
def get_qso_by_uuid(qso_uuid: str, db: Session = Depends(get_db)):
    qso = db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
    if not qso:
        raise HTTPException(status_code=404, detail="QSO not found")
    return qso


@router.patch("/uuid/{qso_uuid}", response_model=LogicalQSODetail)
def update_qso_by_uuid(
    qso_uuid: str,
    request: QSOUpdateRequest,
    db: Session = Depends(get_db),
):
    try:
        qso = SafeUpdateService(db).apply_safe_update(
            qso_uuid,
            request.changes,
            request.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if qso is None:
        raise HTTPException(status_code=404, detail="QSO not found")
    return qso


@router.get("/id/{qso_id}", response_model=LogicalQSODetail)
def get_qso_by_internal_id(qso_id: int, db: Session = Depends(get_db)):
    qso = db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
    if not qso:
        raise HTTPException(status_code=404, detail="QSO not found")
    return qso


@router.get("/{qso_id}", response_model=LogicalQSODetail)
def get_qso(qso_id: int, db: Session = Depends(get_db)):
    qso = db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
    if not qso:
        raise HTTPException(status_code=404, detail="QSO not found")
    return qso
