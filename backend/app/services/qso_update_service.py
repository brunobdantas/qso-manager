"""QSO Update Service - Safe update operations for LogicalQSO."""

from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from ..models.models import LogicalQSO


class QSOUpdateService:
    """Service for safely updating LogicalQSO records.
    
    Key principle: Updates must target the EXACT LogicalQSO by UUID,
    never by CALL+DATE which could match multiple QSOs.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def update_qso(self, qso_id: str, changes: Dict[str, Any]) -> Optional[LogicalQSO]:
        """Update a specific LogicalQSO by its UUID.
        
        Args:
            qso_id: The UUID of the LogicalQSO to update
            changes: Dictionary of field changes to apply
            
        Returns:
            Updated LogicalQSO or None if not found
        """
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
        
        if qso is None:
            return None
        
        # Apply changes only to the specified QSO
        for field, value in changes.items():
            if hasattr(qso, field):
                setattr(qso, field, value)
        
        self.db.commit()
        self.db.refresh(qso)
        
        return qso
    
    def get_qso_by_id(self, qso_id: str) -> Optional[LogicalQSO]:
        """Get a LogicalQSO by its exact UUID."""
        return self.db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
