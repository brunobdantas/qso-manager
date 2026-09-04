"""API Routes for QSO operations."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..db.database import get_db
from ..models.models import LogicalQSO, NormalizedQSO, Source, Divergence
from ..schemas.schemas import LogicalQSOResponse, LogicalQSODetail, NormalizedQSOFull, DivergenceResponse


router = APIRouter(prefix="/api/qsos", tags=["qsos"])


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
    """Get list of logical QSOs with optional filtering."""
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
    
    qsos = query.order_by(LogicalQSO.qso_date.desc()).offset(skip).limit(limit).all()
    return qsos


@router.get("/divergences", response_model=List[DivergenceResponse])
def get_divergences(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get list of divergences between sources."""
    query = db.query(Divergence)
    
    if status:
        query = query.filter(Divergence.status == status)
    
    divergences = query.all()
    return divergences


@router.get("/normalized", response_model=List[NormalizedQSOFull])
def get_normalized_qsos(
    skip: int = 0,
    limit: int = 100,
    source_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Get list of normalized QSOs from all sources."""
    query = db.query(NormalizedQSO)
    
    if source_id:
        query = query.filter(NormalizedQSO.source_id == source_id)
    
    qsos = query.offset(skip).limit(limit).all()
    return qsos


@router.get("/id/{qso_id}", response_model=LogicalQSODetail)
def get_qso_by_internal_id(qso_id: int, db: Session = Depends(get_db)):
    """Get a specific logical QSO by internal ID."""
    qso = db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
    if not qso:
        raise HTTPException(status_code=404, detail="QSO not found")
    return qso


@router.get("/{qso_id}", response_model=LogicalQSODetail)
def get_qso(qso_id: int, db: Session = Depends(get_db)):
    """Get a specific logical QSO by ID."""
    qso = db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
    if not qso:
        raise HTTPException(status_code=404, detail="QSO not found")
    return qso


@router.get("/uuid/{uuid}", response_model=LogicalQSODetail)
def get_qso_by_uuid(uuid: str, db: Session = Depends(get_db)):
    """Get a specific logical QSO by UUID."""
    qso = db.query(LogicalQSO).filter(LogicalQSO.uuid == uuid).first()
    if not qso:
        raise HTTPException(status_code=404, detail="QSO not found")
    return qso
