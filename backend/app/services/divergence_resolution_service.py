"""Persistence for human divergence resolutions."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..models.models import Divergence, DivergenceResolution, LogicalQSO
from .reconciliation_service import ReconciliationService


class DivergenceResolutionService:
    def __init__(self, db: Session):
        self.db = db

    def resolve_divergence(
        self,
        divergence_id: int,
        *,
        resolved_value: str,
        reason: str,
        status: str = "resolved",
    ) -> Optional[DivergenceResolution]:
        if status not in {"resolved", "ignored"}:
            raise ValueError("status must be 'resolved' or 'ignored'")

        divergence = self.db.query(Divergence).filter(Divergence.id == divergence_id).first()
        if divergence is None:
            return None

        logical = self.db.query(LogicalQSO).filter(LogicalQSO.id == divergence.logical_qso_id).first()
        if logical is None or logical.identity is None:
            raise ValueError("Divergence is not linked to a persistent QSOIdentity")

        identity = logical.identity
        key = ReconciliationService.divergence_key(
            identity.uuid,
            divergence.field_name,
            divergence.source_1_name,
            divergence.source_2_name,
        )
        resolution = self.db.query(DivergenceResolution).filter(
            DivergenceResolution.qso_identity_id == identity.id,
            DivergenceResolution.divergence_key == key,
        ).first()
        if resolution is None:
            resolution = DivergenceResolution(
                qso_identity_id=identity.id,
                divergence_key=key,
                field_name=divergence.field_name,
                source_1_name=divergence.source_1_name,
                source_2_name=divergence.source_2_name,
                resolved_value=str(resolved_value),
                reason=reason,
                status=status,
            )
            self.db.add(resolution)
        else:
            resolution.resolved_value = str(resolved_value)
            resolution.reason = reason
            resolution.status = status

        divergence.status = status
        divergence.resolution = str(resolved_value)
        divergence.resolution_reason = reason
        self.db.commit()
        self.db.refresh(resolution)
        return resolution
