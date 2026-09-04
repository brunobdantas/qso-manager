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
    
    # Allowlist of fields that can be edited
    EDITABLE_FIELDS = {
        'callsign', 'qso_date', 'time_on', 'time_off', 'band', 
        'freq_hz', 'mode', 'submode', 'operating_mode', 'mode_family',
        'rst_sent', 'rst_rcvd', 'grid', 'dxcc', 'country', 'state', 
        'county', 'cqz', 'ituz', 'continent', 'iota', 'comment',
        'confirmations', 'field_provenance', 'status', 'divergence_count'
    }
    
    # Fields that can NEVER be changed via update
    PROTECTED_FIELDS = {'id', 'uuid', 'created_at', 'updated_at'}
    
    def __init__(self, db: Session):
        self.db = db
    
    def update_by_uuid(
        self, 
        qso_uuid: str, 
        changes: Dict[str, Any],
        reason: str = ""
    ) -> Optional[LogicalQSO]:
        """Update a specific LogicalQSO by its UUID.
        
        Args:
            qso_uuid: The UUID of the LogicalQSO to update (string)
            changes: Dictionary of field changes to apply
            reason: Reason for the update (for audit)
            
        Returns:
            Updated LogicalQSO or None if not found
        """
        # Query by UUID, not by integer id
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
        
        if qso is None:
            return None
        
        # Filter out protected fields
        safe_changes = {
            k: v for k, v in changes.items() 
            if k in self.EDITABLE_FIELDS and k not in self.PROTECTED_FIELDS
        }
        
        # Apply changes only to the specified QSO
        for field, value in safe_changes.items():
            if hasattr(qso, field):
                setattr(qso, field, value)
        
        self.db.commit()
        self.db.refresh(qso)
        
        return qso
    
    def update_qso(self, qso_id: str, changes: Dict[str, Any]) -> Optional[LogicalQSO]:
        """Update a specific LogicalQSO by its UUID.
        
        Args:
            qso_id: The UUID of the LogicalQSO to update
            changes: Dictionary of field changes to apply
            
        Returns:
            Updated LogicalQSO or None if not found
        """
        # For backward compatibility, try UUID first, then int id
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_id).first()
        
        if qso is None:
            # Fallback to integer id lookup
            try:
                qso_id_int = int(qso_id)
                qso = self.db.query(LogicalQSO).filter(LogicalQSO.id == qso_id_int).first()
            except (ValueError, TypeError):
                return None
        
        if qso is None:
            return None
        
        # Apply changes only to the specified QSO
        for field, value in changes.items():
            if hasattr(qso, field):
                setattr(qso, field, value)
        
        self.db.commit()
        self.db.refresh(qso)
        
        return qso
    
    def get_qso_by_uuid(self, qso_uuid: str) -> Optional[LogicalQSO]:
        """Get a LogicalQSO by its exact UUID."""
        return self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
    
    def get_qso_by_id(self, qso_id: str) -> Optional[LogicalQSO]:
        """Get a LogicalQSO by its exact UUID."""
        return self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_id).first()
