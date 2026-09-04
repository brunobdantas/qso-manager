"""Safe Update Service - Build safe update previews for LogicalQSO."""

from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from ..models.models import LogicalQSO


class SafeUpdateService:
    """Service for building safe update previews for LogicalQSO records.
    
    Key principle: Build a preview of changes without persisting,
    ensuring all non-targeted fields remain identical.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def build_safe_update(
        self, 
        qso_id: str, 
        changes: Dict[str, Any], 
        reason: str
    ) -> Optional[Dict[str, Any]]:
        """Build a safe update preview for a specific LogicalQSO by its UUID.
        
        Args:
            qso_id: The UUID/id of the LogicalQSO to update
            changes: Dictionary of field changes to apply
            reason: Reason for the update
            
        Returns:
            Dictionary containing:
            - qso_uuid: The UUID of the QSO
            - before: Current state of all fields
            - after: Projected state after changes
            - changed_fields: List of fields that will change
            - preserved_fields: List of fields that remain unchanged
            - reason: Reason for the update
            
            Returns None if QSO not found.
        """
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
        
        if qso is None:
            return None
        
        # Get all model fields
        all_fields = [c.name for c in LogicalQSO.__table__.columns]
        
        # Build 'before' state
        before = {}
        for field in all_fields:
            value = getattr(qso, field, None)
            # Convert non-serializable types
            if isinstance(value, datetime):
                value = value.isoformat()
            before[field] = value
        
        # Build 'after' state by cloning before and applying changes
        after = before.copy()
        changed_fields = []
        
        for field, new_value in changes.items():
            if field in all_fields:
                old_value = before.get(field)
                if old_value != new_value:
                    after[field] = new_value
                    changed_fields.append(field)
        
        # Determine preserved fields (all fields not being changed)
        preserved_fields = [f for f in all_fields if f not in changed_fields]
        
        return {
            "qso_uuid": getattr(qso, 'uuid', qso_id),
            "qso_id": qso_id,
            "before": before,
            "after": after,
            "changed_fields": changed_fields,
            "preserved_fields": preserved_fields,
            "reason": reason,
        }
    
    def apply_safe_update(
        self,
        qso_id: str,
        changes: Dict[str, Any],
        reason: str
    ) -> Optional[LogicalQSO]:
        """Apply a safe update to a LogicalQSO.
        
        Args:
            qso_id: The UUID/id of the LogicalQSO to update
            changes: Dictionary of field changes to apply
            reason: Reason for the update
            
        Returns:
            Updated LogicalQSO or None if not found
        """
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.id == qso_id).first()
        
        if qso is None:
            return None
        
        # Apply only the specified changes
        for field, value in changes.items():
            if hasattr(qso, field):
                setattr(qso, field, value)
        
        self.db.commit()
        self.db.refresh(qso)
        
        return qso
