"""API Routes for import operations."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from sqlalchemy.orm import Session
from typing import List, Optional

from ..db.database import get_db
from ..schemas.schemas import ADIFImportResponse, CoverageType
from ..services.import_service import ADIFImportService


router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.post("/adif", response_model=ADIFImportResponse)
async def import_adif(
    content: str = Body(..., embed=True),
    source_name: str = Body(..., embed=True),
    filename: Optional[str] = Body(default="inline.adif", embed=True),
    source_type: str = Body(default="LOGBOOK", embed=True),
    coverage_type: str = Body(default="FULL_EXPORT", embed=True),
    reliability_score: float = Body(default=0.5, embed=True),
    db: Session = Depends(get_db),
):
    """
    Import an ADIF file content.
    
    Expects JSON body with:
    - **content**: ADIF file content as string
    - **source_name**: Name of the source (e.g., "QRZ", "WRL", "MSHV")
    - **filename**: Optional filename (default: "inline.adif")
    - **source_type**: Type of source (LOGBOOK, SOFTWARE, etc.)
    - **coverage_type**: Type of coverage (FULL_EXPORT, PARTIAL_EXPORT, etc.)
    - **reliability_score**: Reliability score 0.0-1.0
    """
    # Import using service
    service = ADIFImportService(db)
    result = service.import_adif(
        content=content,
        filename=filename,
        source_name=source_name,
        source_type=source_type,
        coverage_type=CoverageType(coverage_type),
        reliability_score=reliability_score,
    )
    
    if result["status"] == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {'; '.join(result['errors'])}"
        )
    
    return ADIFImportResponse(**result)


@router.get("", response_model=List[dict])
def list_imports(db: Session = Depends(get_db)):
    """List all imports."""
    from ..models.models import Import
    imports = db.query(Import).order_by(Import.started_at.desc()).all()
    return [
        {
            "id": i.id,
            "source_id": i.source_id,
            "coverage_type": i.coverage_type.value,
            "started_at": i.started_at.isoformat() if i.started_at else None,
            "completed_at": i.completed_at.isoformat() if i.completed_at else None,
            "status": i.status,
            "total_records": i.total_records,
            "processed_records": i.processed_records,
        }
        for i in imports
    ]
