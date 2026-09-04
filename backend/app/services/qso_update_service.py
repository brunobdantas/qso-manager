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
    
    def _validate_changes(self, changes: Dict[str, Any]) -> None:
        """Validate that changes only contain editable fields.
        
        Args:
            changes: Dictionary of field changes to validate
            
        Raises:
            ValueError: If any protected or unknown fields are present
        """
        change_keys = set(changes.keys())
        
        # Check for protected fields first
        protected_found = change_keys & self.PROTECTED_FIELDS
        if protected_found:
            raise ValueError(
                f"Cannot modify protected fields: {sorted(protected_found)}. "
                f"Protected fields are: {sorted(self.PROTECTED_FIELDS)}"
            )
        
        # Check for unknown fields (not in EDITABLE_FIELDS and not model fields)
        all_model_fields = {c.name for c in LogicalQSO.__table__.columns}
        unknown_found = change_keys - self.EDITABLE_FIELDS - all_model_fields
        
        if unknown_found:
            raise ValueError(
                f"Cannot modify unknown/invalid fields: {sorted(unknown_found)}. "
                f"Editable fields are: {sorted(self.EDITABLE_FIELDS)}"
            )
    
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
            
        Raises:
            ValueError: If changes contain protected or unknown fields
        """
        # Validate changes FIRST - reject protected/unknown fields explicitly
        self._validate_changes(changes)
        
        # Query by UUID, not by integer id
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
        
        if qso is None:
            return None
        
        # Filter out protected fields (already validated, but be safe)
        safe_changes = {
            k: v for k, v in changes.items() 
            if k in self.EDITABLE_FIELDS
        }
        
        # Apply changes only to the specified QSO
        for field, value in safe_changes.items():
            if hasattr(qso, field):
                setattr(qso, field, value)
        
        self.db.commit()
        self.db.refresh(qso)
        
        return qso
    
    def build_safe_update(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Build a preview of safe changes without applying them.
        
        Args:
            changes: Dictionary of field changes to preview
            
        Returns:
            Dictionary with validated changes
            
        Raises:
            ValueError: If changes contain protected or unknown fields
        """
        # Validate changes FIRST
        self._validate_changes(changes)
        return changes.copy()
    
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
