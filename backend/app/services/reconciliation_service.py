"""Reconciliation orchestration and persistence.

QSOIdentity is the durable identity of a real contact. LogicalQSO and its source
links/divergences are a materialized active view rebuilt from normalized source
records. Human overrides and divergence resolutions are attached to QSOIdentity
and therefore survive rebuilds, cluster evolution, and process restarts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from ..models.models import (
    AuditEvent,
    AuditOperation,
    Divergence,
    DivergenceResolution,
    LogicalQSO,
    LogicalQSOFieldOverride,
    MatchLevel,
    MatchStatus,
    NormalizedQSO,
    QSOIdentity,
    QSOSourceLink,
    ReconciliationMatch,
    ReconciliationRun,
    Source,
)
from ..reconciliation.engine import NormalizedQSOData, ReconciliationEngine, ReconciliationResult


class ReconciliationService:
    def __init__(self, db: Session):
        self.db = db
        self.engine = ReconciliationEngine()

    def run_reconciliation(self) -> Dict[str, Any]:
        run = ReconciliationRun(status="running", started_at=datetime.utcnow(), parameters={})
        self.db.add(run)
        self.db.flush()

        try:
            normalized_qsos = self.db.query(NormalizedQSO).join(Source).all()
            qso_data = [
                NormalizedQSOData(
                    id=nq.id,
                    callsign=nq.callsign,
                    qso_date=nq.qso_date,
                    time_on=nq.time_on,
                    band=nq.band,
                    freq_hz=nq.freq_hz,
                    mode=nq.mode,
                    submode=nq.submode,
                    operating_mode=nq.operating_mode,
                    mode_family=nq.mode_family,
                    rst_sent=nq.rst_sent,
                    rst_rcvd=nq.rst_rcvd,
                    grid=nq.grid,
                    source_id=nq.source_id,
                    source_name=nq.source.name if nq.source else "Unknown",
                )
                for nq in normalized_qsos
            ]

            result = self.engine.reconcile(qso_data)
            self._mark_ambiguous_singletons_for_review(result, qso_data)
            self._save_matches(run.id, result.matches)
            self._atomic_rebuild_active_view(result)

            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.total_logical_qsos = len(result.logical_qsos)
            run.total_matches = len(result.matches)
            run.total_divergences = len(result.divergences)
            run.total_duplicates = len(result.duplicates)

            # Audit is part of the same transaction so a reported successful run
            # always has a durable append-only audit event.
            self._log_audit(run, result)
            self.db.commit()

            return {
                "run_id": run.id,
                "status": "completed",
                "total_processed": result.total_processed,
                "total_matched": result.total_matched,
                "total_logical_qsos": len(result.logical_qsos),
                "total_divergences": len(result.divergences),
                "total_duplicates": len(result.duplicates),
            }
        except Exception as exc:
            self.db.rollback()
            # The initial run row was rolled back as well. Persist a failure row
            # independently rather than mutating a detached/rolled-back object.
            failed = ReconciliationRun(
                status="failed",
                started_at=run.started_at,
                completed_at=datetime.utcnow(),
                parameters={},
            )
            self.db.add(failed)
            self.db.commit()
            return {"run_id": failed.id, "status": "failed", "error": str(exc)}

    def _mark_ambiguous_singletons_for_review(
        self, result: ReconciliationResult, qso_data: List[NormalizedQSOData]
    ) -> None:
        """Promote no-time singleton QSOs with plausible external candidates to review.

        The engine intentionally refuses to auto-merge a no-time record that can
        bridge multiple contacts.  Status belongs to the resulting materialized
        QSO, so apply the review signal here without changing cluster membership.
        """
        by_id = {q.id: q for q in qso_data}
        review_ids: Set[int] = set()
        review_statuses = {
            MatchStatus.REVISAO_MANUAL,
            MatchStatus.MANUAL_REVIEW,
            MatchStatus.POSSIBLE_MATCH,
        }
        for match in result.matches:
            if match.match_status not in review_statuses:
                continue
            for qid in (match.qso1_id, match.qso2_id):
                qso = by_id.get(qid)
                if qso is not None and not qso.has_time:
                    review_ids.add(qid)

        for logical in result.logical_qsos:
            member_ids = {
                link["normalized_qso_id"]
                for link in logical.get("source_links", [])
            }
            if member_ids & review_ids:
                logical["status"] = "needs_review"

    def _save_matches(self, run_id: int, matches: Iterable[Any]) -> None:
        for match in matches:
            self.db.add(ReconciliationMatch(
                run_id=run_id,
                normalized_qso_id_1=match.qso1_id,
                normalized_qso_id_2=match.qso2_id,
                match_level=match.match_level,
                match_status=match.match_status,
                match_score=match.score,
                time_difference_seconds=match.time_diff_seconds,
                frequency_difference=match.freq_diff,
                reasoning=", ".join(match.reasoning) if match.reasoning else None,
            ))

    @staticmethod
    def _seconds(time_on: Optional[str]) -> Optional[int]:
        if not time_on:
            return None
        try:
            h, m, *rest = time_on.split(":")
            sec = rest[0] if rest else "0"
            return int(h) * 3600 + int(m) * 60 + int(sec)
        except (TypeError, ValueError):
            return None

    def _capture_previous_memberships(self) -> Dict[int, int]:
        """Map normalized QSO id -> persistent identity id from the current view."""
        rows = self.db.query(QSOSourceLink, LogicalQSO).join(
            LogicalQSO, QSOSourceLink.logical_qso_id == LogicalQSO.id
        ).all()
        return {
            link.normalized_qso_id: logical.qso_identity_id
            for link, logical in rows
            if logical.qso_identity_id is not None
        }

    def _find_or_create_identity(
        self,
        lq: Dict[str, Any],
        member_ids: Set[int],
        previous_memberships: Dict[int, int],
        assigned_identity_ids: Set[int],
    ) -> QSOIdentity:
        candidate_ids = {
            previous_memberships[mid]
            for mid in member_ids
            if mid in previous_memberships and previous_memberships[mid] is not None
        }

        identity: Optional[QSOIdentity] = None
        if len(candidate_ids) == 1:
            identity = self.db.get(QSOIdentity, next(iter(candidate_ids)))
        elif len(candidate_ids) > 1:
            # A new auto-cluster spanning multiple previous real-QSO identities is
            # an identity merge. Do not silently overwrite either durable identity;
            # create a new review identity for the materialized view.
            identity = None
            lq["status"] = "needs_review"

        if identity is None and not candidate_ids:
            # Recovery fallback for an existing durable identity if the materialized
            # view was absent. Use call/date and time only when unambiguous.
            candidates = self.db.query(QSOIdentity).filter(
                QSOIdentity.callsign == lq["callsign"],
                QSOIdentity.qso_date == lq["qso_date"],
            ).all()
            target_seconds = self._seconds(lq.get("time_on"))
            plausible = []
            for candidate in candidates:
                if candidate.id in assigned_identity_ids:
                    continue
                candidate_seconds = self._seconds(candidate.time_on)
                if target_seconds is None or candidate_seconds is None:
                    plausible.append(candidate)
                elif abs(target_seconds - candidate_seconds) <= 60:
                    plausible.append(candidate)
            if len(plausible) == 1:
                identity = plausible[0]

        if identity is None:
            identity = QSOIdentity(
                callsign=lq["callsign"],
                qso_date=lq["qso_date"],
                time_on=lq.get("time_on"),
            )
            self.db.add(identity)
            self.db.flush()
        else:
            # Fill missing durable time from newly available source data, but never
            # replace an established time merely because the canonical source order
            # changed.
            if not identity.time_on and lq.get("time_on"):
                identity.time_on = lq.get("time_on")
            identity.callsign = lq["callsign"]
            identity.qso_date = lq["qso_date"]

        assigned_identity_ids.add(identity.id)
        return identity

    @staticmethod
    def _decode_override(text: Optional[str]) -> Any:
        if text is None:
            return None
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            # Backward compatibility with overrides saved as plain text.
            return text

    @staticmethod
    def divergence_key(identity_uuid: str, field_name: str, source_1: Optional[str], source_2: Optional[str]) -> str:
        sources = sorted([(source_1 or "").strip().upper(), (source_2 or "").strip().upper()])
        raw = "|".join([identity_uuid, field_name or "", *sources])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _apply_overrides(self, logical_qso: LogicalQSO, identity: QSOIdentity) -> None:
        overrides = self.db.query(LogicalQSOFieldOverride).filter(
            LogicalQSOFieldOverride.qso_identity_id == identity.id,
            LogicalQSOFieldOverride.is_active.is_(True),
        ).all()
        provenance = dict(logical_qso.field_provenance or {})
        for override in overrides:
            if not hasattr(logical_qso, override.field_name):
                continue
            setattr(logical_qso, override.field_name, self._decode_override(override.override_value))
            provenance[override.field_name] = {
                "source": "MANUAL_OVERRIDE",
                "confidence": 1.0,
                "reason": override.reason,
            }
        logical_qso.field_provenance = provenance or None

    def _apply_resolution(self, divergence: Divergence, identity: QSOIdentity) -> None:
        key = self.divergence_key(
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
            # Source membership can evolve; a resolution for the same durable QSO
            # field remains meaningful even when an additional agreeing source joins.
            resolution = self.db.query(DivergenceResolution).filter(
                DivergenceResolution.qso_identity_id == identity.id,
                DivergenceResolution.field_name == divergence.field_name,
                DivergenceResolution.status.in_(["resolved", "ignored"]),
            ).order_by(DivergenceResolution.updated_at.desc()).first()
        if resolution is not None:
            divergence.status = resolution.status
            divergence.resolution = resolution.resolved_value
            divergence.resolution_reason = resolution.reason

    def _atomic_rebuild_active_view(self, result: ReconciliationResult) -> None:
        previous_memberships = self._capture_previous_memberships()

        # Objects from the previous materialized view may still be present in the
        # Session identity map (including objects held by callers). SQLite can reuse
        # integer primary keys after DELETE, so detach those transient-view objects
        # before rebuilding to prevent identity-map replacement warnings/stale rows.
        for obj in list(self.db.identity_map.values()):
            if isinstance(obj, (Divergence, QSOSourceLink, LogicalQSO)):
                self.db.expunge(obj)

        self.db.query(Divergence).delete(synchronize_session=False)
        self.db.query(QSOSourceLink).delete(synchronize_session=False)
        self.db.query(LogicalQSO).delete(synchronize_session=False)
        self.db.flush()

        assigned_identity_ids: Set[int] = set()
        engine_uuid_to_logical: Dict[str, LogicalQSO] = {}

        for lq in result.logical_qsos:
            member_ids = {link["normalized_qso_id"] for link in lq.get("source_links", [])}
            identity = self._find_or_create_identity(
                lq, member_ids, previous_memberships, assigned_identity_ids
            )

            # Externally visible LogicalQSO UUID follows the durable QSO identity,
            # not the transient set of source-member ids.
            logical_qso = LogicalQSO(
                uuid=identity.uuid,
                qso_identity_id=identity.id,
                callsign=lq["callsign"],
                qso_date=lq["qso_date"],
                time_on=lq.get("time_on"),
                time_off=lq.get("time_off"),
                band=lq.get("band"),
                freq_hz=lq.get("freq_hz"),
                mode=lq.get("mode"),
                submode=lq.get("submode"),
                operating_mode=lq.get("operating_mode"),
                mode_family=lq.get("mode_family"),
                rst_sent=lq.get("rst_sent"),
                rst_rcvd=lq.get("rst_rcvd"),
                grid=lq.get("grid"),
                dxcc=lq.get("dxcc"),
                country=lq.get("country"),
                state=lq.get("state"),
                county=lq.get("county"),
                cqz=lq.get("cqz"),
                ituz=lq.get("ituz"),
                continent=lq.get("continent"),
                iota=lq.get("iota"),
                comment=lq.get("comment"),
                confirmations=lq.get("confirmations"),
                field_provenance=lq.get("field_provenance"),
                status=lq.get("status", "reconciled"),
                divergence_count=sum(
                    1 for d in result.divergences
                    if d.get("logical_qso_uuid") == lq["uuid"]
                ),
            )
            self._apply_overrides(logical_qso, identity)
            self.db.add(logical_qso)
            self.db.flush()
            engine_uuid_to_logical[lq["uuid"]] = logical_qso

            num_sources = len(lq.get("source_links", []))
            for link_data in lq.get("source_links", []):
                norm_qso = self.db.get(NormalizedQSO, link_data["normalized_qso_id"])
                if norm_qso is None:
                    continue
                self.db.add(QSOSourceLink(
                    logical_qso_id=logical_qso.id,
                    normalized_qso_id=norm_qso.id,
                    match_level=MatchLevel.A if num_sources == 1 else MatchLevel.B,
                    match_status=MatchStatus.CONFIRMED if num_sources == 1 else MatchStatus.AUTO_MATCHED,
                    match_score=1.0,
                ))

        self.db.flush()

        for div in result.divergences:
            logical_qso = engine_uuid_to_logical.get(div.get("logical_qso_uuid"))
            if logical_qso is None or logical_qso.identity is None:
                continue
            divergence = Divergence(
                logical_qso_id=logical_qso.id,
                field_name=div.get("field_name"),
                source_1_value=div.get("source_1_value"),
                source_1_name=div.get("source_1_name"),
                source_2_value=div.get("source_2_value"),
                source_2_name=div.get("source_2_name"),
                status=div.get("status", "unresolved"),
            )
            self._apply_resolution(divergence, logical_qso.identity)
            self.db.add(divergence)

    def _log_audit(self, run: ReconciliationRun, result: ReconciliationResult) -> None:
        self.db.add(AuditEvent(
            operation=AuditOperation.RECONCILIATION,
            entity_type="reconciliation_run",
            entity_id=run.id,
            source="system",
            after={
                "run_id": run.id,
                "total_processed": result.total_processed,
                "total_matched": result.total_matched,
                "total_logical_qsos": len(result.logical_qsos),
                "total_divergences": len(result.divergences),
                "total_duplicates": len(result.duplicates),
            },
            result="success",
            reason="Automated reconciliation run",
        ))
