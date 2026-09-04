"""API Routes for audit log operations."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from ..db.database import get_db
from ..models.models import AuditEvent


router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=List[dict])
def get_audit_log(
    skip: int = 0,
    limit: int = 100,
    entity_type: Optional[str] = None,
    operation: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Get audit log entries.
    
    - **skip**: Number of entries to skip
    - **limit**: Maximum number of entries to return
    - **entity_type**: Filter by entity type (qso, import, backup, etc.)
    - **operation**: Filter by operation type (CREATE, UPDATE, DELETE, etc.)
    """
    query = db.query(AuditEvent).order_by(AuditEvent.timestamp.desc())
    
    if entity_type:
        query = query.filter(AuditEvent.entity_type == entity_type)
    
    if operation:
        query = query.filter(AuditEvent.operation == operation)
    
    events = query.offset(skip).limit(limit).all()
    
    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "operation": e.operation.value if hasattr(e.operation, 'value') else str(e.operation),
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "source": e.source,
            "before": e.before,
            "after": e.after,
            "reason": e.reason,
            "result": e.result,
            "error": e.error,
        }
        for e in events
    ]
