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
    
    def build_safe_update(
        self, 
        qso_uuid: str, 
        changes: Dict[str, Any], 
        reason: str
    ) -> Optional[Dict[str, Any]]:
        """Build a safe update preview for a specific LogicalQSO by its UUID.
        
        Args:
            qso_uuid: The UUID of the LogicalQSO to update (string)
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
            
        Raises:
            ValueError: If changes contain protected or unknown fields
        """
        # Validate changes FIRST - reject protected/unknown fields explicitly
        self._validate_changes(changes)
        
        # Query by UUID, not by integer id
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
        
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
        
        # Filter changes: only allow editable fields
        safe_changes = {
            k: v for k, v in changes.items()
            if k in self.EDITABLE_FIELDS
        }
        
        # Build 'after' state by cloning before and applying safe changes
        after = before.copy()
        changed_fields = []
        
        for field, new_value in safe_changes.items():
            if field in all_fields:
                old_value = before.get(field)
                if old_value != new_value:
                    after[field] = new_value
                    changed_fields.append(field)
        
        # Determine preserved fields (all fields not being changed)
        preserved_fields = [f for f in all_fields if f not in changed_fields]
        
        return {
            "qso_uuid": getattr(qso, 'uuid', qso_uuid),
            "qso_id": qso.id,
            "before": before,
            "after": after,
            "changed_fields": changed_fields,
            "preserved_fields": preserved_fields,
            "reason": reason,
        }
    
    def apply_safe_update(
        self,
        qso_uuid: str,
        changes: Dict[str, Any],
        reason: str
    ) -> Optional[LogicalQSO]:
        """Apply a safe update to a LogicalQSO by UUID.
        
        Args:
            qso_uuid: The UUID of the LogicalQSO to update (string)
            changes: Dictionary of field changes to apply
            reason: Reason for the update
            
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
        
        # Filter changes: only allow editable fields, never protected fields
        safe_changes = {
            k: v for k, v in changes.items()
            if k in self.EDITABLE_FIELDS and k not in self.PROTECTED_FIELDS
        }
        
        # Apply only the specified changes
        for field, value in safe_changes.items():
            if hasattr(qso, field):
                setattr(qso, field, value)
        
        self.db.commit()
        self.db.refresh(qso)
        
        return qso
