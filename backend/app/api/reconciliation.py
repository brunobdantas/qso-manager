"""API Routes for reconciliation operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..schemas.schemas import (
    ReconciliationRunResponse, 
    ReconciliationMatchResponse,
    DivergenceResponse,
    DuplicateGroupResponse,
)
from ..services.reconciliation_service import ReconciliationService


router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.post("", response_model=dict)
def run_reconciliation(db: Session = Depends(get_db)):
    """
    Run reconciliation on all normalized QSOs.
    
    This will:
    1. Group QSOs by callsign + date
    2. Evaluate matches between sources
    3. Apply time-based blocking rules
    4. Create logical QSOs
    5. Detect divergences
    
    Returns summary of the reconciliation run.
    """
    service = ReconciliationService(db)
    result = service.run_reconciliation()
    
    if result.get("status") == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Reconciliation failed: {result.get('error')}"
        )
    
    return result


@router.get("/runs", response_model=list)
def list_runs(db: Session = Depends(get_db)):
    """List all reconciliation runs."""
    from ..models.models import ReconciliationRun
    runs = db.query(ReconciliationRun).order_by(
        ReconciliationRun.started_at.desc()
    ).all()
    return [
        {
            "id": r.id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "status": r.status,
            "total_logical_qsos": r.total_logical_qsos,
            "total_matches": r.total_matches,
            "total_divergences": r.total_divergences,
            "total_duplicates": r.total_duplicates,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=ReconciliationRunResponse)
def get_run(run_id: int, db: Session = Depends(get_db)):
    """Get details of a specific reconciliation run."""
    from ..models.models import ReconciliationRun
    run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/matches", response_model=list)
def list_matches(db: Session = Depends(get_db)):
    """List all reconciliation matches."""
    from ..models.models import ReconciliationMatch
    matches = db.query(ReconciliationMatch).order_by(
        ReconciliationMatch.created_at.desc()
    ).limit(100).all()
    return matches


@router.get("/divergences", response_model=list)
def list_divergences(db: Session = Depends(get_db)):
    """List all divergences between sources."""
    from ..models.models import Divergence
    divergences = db.query(Divergence).all()
    return divergences


@router.get("/duplicates", response_model=list)
def list_duplicates(db: Session = Depends(get_db)):
    """List all detected duplicate groups."""
    from ..models.models import DuplicateGroup
    duplicates = db.query(DuplicateGroup).all()
    return duplicates
