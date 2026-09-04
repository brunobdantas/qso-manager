"""API Routes for backup operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from ..db.database import get_db
from ..services.backup_service import BackupService


router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.post("", response_model=dict)
def create_backup(
    backup_type: str = "full",
    description: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Create a backup of QSO data.
    
    - **backup_type**: Type of backup ('full' for JSON, 'adif' for ADIF format)
    - **description**: Optional description for the backup
    """
    if backup_type not in ("full", "adif"):
        raise HTTPException(
            status_code=400,
            detail="backup_type must be 'full' or 'adif'"
        )
    
    service = BackupService(db)
    result = service.create_backup(
        backup_type=backup_type,
        description=description,
    )
    
    return result


@router.get("", response_model=list)
def list_backups(db: Session = Depends(get_db)):
    """List all backups."""
    service = BackupService(db)
    return service.list_backups()


@router.delete("/{backup_id}", response_model=dict)
def delete_backup(backup_id: int, db: Session = Depends(get_db)):
    """Delete a backup."""
    service = BackupService(db)
    success = service.delete_backup(backup_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    return {"message": "Backup deleted successfully"}
