"""Safe, UUID-targeted updates for the materialized LogicalQSO view.

Human changes are persisted against QSOIdentity so reconciliation can rebuild the
materialized view without losing user decisions.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models.models import (
    AuditEvent,
    AuditOperation,
    LogicalQSO,
    LogicalQSOFieldOverride,
)


class SafeUpdateService:
    EDITABLE_FIELDS = {
        "callsign", "qso_date", "time_on", "time_off", "band",
        "freq_hz", "mode", "submode", "operating_mode", "mode_family",
        "rst_sent", "rst_rcvd", "grid", "dxcc", "country", "state",
        "county", "cqz", "ituz", "continent", "iota", "comment",
        "confirmations", "field_provenance", "status", "divergence_count",
    }
    PROTECTED_FIELDS = {"id", "uuid", "qso_identity_id", "created_at", "updated_at"}

    def __init__(self, db: Session):
        self.db = db

    def _validate_changes(self, changes: Dict[str, Any]) -> None:
        change_keys = set(changes)
        protected = change_keys & self.PROTECTED_FIELDS
        if protected:
            raise ValueError(
                f"Cannot modify protected fields: {sorted(protected)}. "
                f"Protected fields are: {sorted(self.PROTECTED_FIELDS)}"
            )
        invalid = change_keys - self.EDITABLE_FIELDS
        if invalid:
            raise ValueError(
                f"Cannot modify unknown/invalid fields: {sorted(invalid)}. "
                f"Editable fields are: {sorted(self.EDITABLE_FIELDS)}"
            )

    @staticmethod
    def _json_value(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def build_safe_update(
        self,
        qso_uuid: str,
        changes: Dict[str, Any],
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        self._validate_changes(changes)
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
        if qso is None:
            return None

        all_fields = [column.name for column in LogicalQSO.__table__.columns]
        before: Dict[str, Any] = {}
        for field in all_fields:
            value = getattr(qso, field, None)
            if isinstance(value, datetime):
                value = value.isoformat()
            before[field] = value

        after = before.copy()
        changed_fields = []
        for field, value in changes.items():
            if before.get(field) != value:
                after[field] = value
                changed_fields.append(field)

        return {
            "qso_uuid": qso.uuid,
            "qso_id": qso.id,
            "qso_identity_id": qso.qso_identity_id,
            "before": before,
            "after": after,
            "changed_fields": changed_fields,
            "preserved_fields": [f for f in all_fields if f not in changed_fields],
            "reason": reason,
        }

    def apply_safe_update(
        self,
        qso_uuid: str,
        changes: Dict[str, Any],
        reason: str,
    ) -> Optional[LogicalQSO]:
        self._validate_changes(changes)
        qso = self.db.query(LogicalQSO).filter(LogicalQSO.uuid == qso_uuid).first()
        if qso is None:
            return None

        before = {field: getattr(qso, field, None) for field in changes}
        applied: Dict[str, Any] = {}

        for field, value in changes.items():
            old_value = getattr(qso, field)
            if old_value == value:
                continue

            # Persist human intent against the stable identity. Legacy/unit-test
            # LogicalQSOs without an identity remain editable but cannot persist
            # an override across reconciliation.
            if qso.qso_identity_id is not None:
                override = self.db.query(LogicalQSOFieldOverride).filter(
                    LogicalQSOFieldOverride.qso_identity_id == qso.qso_identity_id,
                    LogicalQSOFieldOverride.field_name == field,
                    LogicalQSOFieldOverride.is_active.is_(True),
                ).first()
                if override is None:
                    override = LogicalQSOFieldOverride(
                        qso_identity_id=qso.qso_identity_id,
                        field_name=field,
                        original_value=self._json_value(old_value),
                        override_value=self._json_value(value),
                        reason=reason,
                        created_by="manual",
                        is_active=True,
                    )
                    self.db.add(override)
                else:
                    override.override_value = self._json_value(value)
                    override.reason = reason
                    override.created_by = "manual"
                    override.is_active = True

            setattr(qso, field, value)
            applied[field] = value

        if applied:
            self.db.add(AuditEvent(
                operation=AuditOperation.UPDATE,
                entity_type="logical_qso",
                entity_id=qso.id,
                source="manual",
                before={k: before[k] for k in applied},
                after=applied,
                reason=reason,
                result="success",
            ))

        self.db.commit()
        self.db.refresh(qso)
        return qso
