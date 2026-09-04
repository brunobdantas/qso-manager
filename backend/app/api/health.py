"""API Routes for health check and system status."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..db.database import get_db
from ..core.config import settings
from ..schemas.schemas import HealthResponse


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """Check API health status."""
    # Check database connection
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        database=db_status,
        qrz_enabled=settings.qrz_enabled,
        environment=settings.environment,
    )
