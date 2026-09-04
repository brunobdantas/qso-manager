"""API Routes for import operations."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List

from ..db.database import get_db
from ..schemas.schemas import ADIFImportResponse, CoverageType
from ..services.import_service import ADIFImportService


router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.post("/adif", response_model=ADIFImportResponse)
async def import_adif(
    file: UploadFile = File(...),
    source_name: str = Form(...),
    source_type: str = Form(default="LOGBOOK"),
    coverage_type: str = Form(default="FULL_EXPORT"),
    reliability_score: float = Form(default=0.5),
    db: Session = Depends(get_db),
):
    """
    Import an ADIF file.
    
    - **file**: ADIF file to import
    - **source_name**: Name of the source (e.g., "QRZ", "WRL", "MSHV")
    - **source_type**: Type of source (LOGBOOK, SOFTWARE, etc.)
    - **coverage_type**: Type of coverage (FULL_EXPORT, PARTIAL_EXPORT, etc.)
    - **reliability_score**: Reliability score 0.0-1.0
    """
    # Validate file type
    if not file.filename.lower().endswith(('.adi', '.adif')):
        raise HTTPException(
            status_code=400, 
            detail="File must be an ADIF file (.adi or .adif)"
        )
    
    # Read file content
    content = await file.read()
    try:
        content_str = content.decode('utf-8')
    except UnicodeDecodeError:
        try:
            content_str = content.decode('latin-1')
        except:
            raise HTTPException(
                status_code=400,
                detail="Unable to decode file. Please ensure it's a valid text file."
            )
    
    # Import using service
    service = ADIFImportService(db)
    result = service.import_adif(
        content=content_str,
        filename=file.filename,
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
