"""Reconciliation Service - orchestrates the reconciliation process."""

from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from ..models.models import (
    NormalizedQSO, Source, ReconciliationRun, ReconciliationMatch,
    LogicalQSO, QSOSourceLink, Divergence, AuditEvent,
    MatchLevel, MatchStatus, AuditOperation
)
from ..reconciliation.engine import (
    ReconciliationEngine, NormalizedQSOData, ReconciliationResult
)


class ReconciliationService:
    """Service for running QSO reconciliation."""
    
    def __init__(self, db: Session):
        self.db = db
        self.engine = ReconciliationEngine()
    
    def run_reconciliation(self) -> Dict[str, Any]:
        """
        Run reconciliation on all normalized QSOs.
        
        Returns summary of reconciliation results.
        
        IDEMPOTENCY: Uses atomic rebuild of active view (LogicalQSO, QSOSourceLink, Divergence).
        Historical data (ReconciliationRun, ReconciliationMatch, AuditEvent) is preserved.
        """
        # Create reconciliation run record
        run = ReconciliationRun(
            status="running",
            started_at=datetime.utcnow(),
            parameters={},
        )
        self.db.add(run)
        self.db.flush()
        
        try:
            # Load all normalized QSOs with source info
            normalized_qsos = self.db.query(NormalizedQSO).join(Source).all()
            
            # Convert to engine format
            qso_data = []
            for nq in normalized_qsos:
                qso_data.append(NormalizedQSOData(
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
                ))
            
            # Run reconciliation engine
            result = self.engine.reconcile(qso_data)
            
            # Save matches to database (historical - never cleaned)
            self._save_matches(run.id, result.matches)
            
            # ATOMIC REBUILD OF ACTIVE VIEW
            # Within a single transaction, replace the entire active view
            self._atomic_rebuild_active_view(result)
            
            # Update run record
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.total_logical_qsos = len(result.logical_qsos)
            run.total_matches = len(result.matches)
            run.total_divergences = len(result.divergences)
            run.total_duplicates = len(result.duplicates)
            
            self.db.commit()
            
            # Log audit event
            self._log_audit(run, result)
            
            return {
                "run_id": run.id,
                "status": "completed",
                "total_processed": result.total_processed,
                "total_matched": result.total_matched,
                "total_logical_qsos": len(result.logical_qsos),
                "total_divergences": len(result.divergences),
                "total_duplicates": len(result.duplicates),
            }
            
        except Exception as e:
            self.db.rollback()
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            self.db.commit()
            
            return {
                "run_id": run.id,
                "status": "failed",
                "error": str(e),
            }
    
    def _save_matches(self, run_id: int, matches: List):
        """Save reconciliation matches to database."""
        for match in matches:
            db_match = ReconciliationMatch(
                run_id=run_id,
                normalized_qso_id_1=match.qso1_id,
                normalized_qso_id_2=match.qso2_id,
                match_level=match.match_level,
                match_status=match.match_status,
                match_score=match.score,
                time_difference_seconds=match.time_diff_seconds,
                frequency_difference=match.freq_diff,
                reasoning=", ".join(match.reasoning) if match.reasoning else None,
            )
            self.db.add(db_match)
    
    def _atomic_rebuild_active_view(self, result: ReconciliationResult):
        """
        Atomically rebuild the active view (LogicalQSO, QSOSourceLink, Divergence).
        
        This ensures idempotency: after each reconciliation run, the active view
        reflects exactly the current state of normalized QSOs, without duplicates
        from previous runs.
        
        Historical data (ReconciliationRun, ReconciliationMatch, AuditEvent) is preserved.
        """
        import hashlib
        
        # Step 1: Delete all current active view records
        # Delete divergences first (they reference LogicalQSO)
        self.db.query(Divergence).delete()
        
        # Delete source links (they reference LogicalQSO)
        self.db.query(QSOSourceLink).delete()
        
        # Delete logical QSOs
        self.db.query(LogicalQSO).delete()
        
        # Flush to ensure deletes are applied
        self.db.flush()
        
        # Step 2: Recreate LogicalQSOs and QSOSourceLinks from result
        for lq in result.logical_qsos:
            # Compute stable cluster fingerprint from sorted normalized QSO IDs
            sorted_qso_ids = sorted([link['normalized_qso_id'] for link in lq.get('source_links', [])])
            fingerprint_input = "|".join(str(id_) for id_ in sorted_qso_ids)
            cluster_fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()
            
            # Create logical QSO with deterministic UUID based on cluster fingerprint
            logical_qso = LogicalQSO(
                uuid=lq['uuid'],
                callsign=lq['callsign'],
                qso_date=lq['qso_date'],
                time_on=lq.get('time_on'),
                time_off=lq.get('time_off'),
                band=lq.get('band'),
                freq_hz=lq.get('freq_hz'),
                mode=lq.get('mode'),
                submode=lq.get('submode'),
                operating_mode=lq.get('operating_mode'),
                mode_family=lq.get('mode_family'),
                rst_sent=lq.get('rst_sent'),
                rst_rcvd=lq.get('rst_rcvd'),
                grid=lq.get('grid'),
                dxcc=lq.get('dxcc'),
                country=lq.get('country'),
                state=lq.get('state'),
                county=lq.get('county'),
                cqz=lq.get('cqz'),
                ituz=lq.get('ituz'),
                continent=lq.get('continent'),
                iota=lq.get('iota'),
                comment=lq.get('comment'),
                confirmations=lq.get('confirmations'),
                field_provenance=lq.get('field_provenance'),
                status=lq.get('status', 'reconciled'),
                divergence_count=len([
                    d for d in result.divergences 
                    if d.get('logical_qso_uuid') == lq['uuid']
                ]),
            )
            self.db.add(logical_qso)
            self.db.flush()
            
            # Create source links
            for link_data in lq.get('source_links', []):
                norm_qso = self.db.query(NormalizedQSO).filter(
                    NormalizedQSO.id == link_data['normalized_qso_id']
                ).first()
                
                if norm_qso:
                    # Determine match level based on number of sources
                    num_sources = len(lq.get('source_links', []))
                    if num_sources == 1:
                        match_level = MatchLevel.A
                        match_status = MatchStatus.CONFIRMED
                    else:
                        match_level = MatchLevel.B
                        match_status = MatchStatus.AUTO_MATCHED
                    
                    link = QSOSourceLink(
                        logical_qso_id=logical_qso.id,
                        normalized_qso_id=norm_qso.id,
                        match_level=match_level,
                        match_status=match_status,
                        match_score=1.0,
                    )
                    self.db.add(link)
        
        # Step 3: Recreate divergences
        for div in result.divergences:
            # Find logical QSO by UUID
            logical_qso = self.db.query(LogicalQSO).filter(
                LogicalQSO.uuid == div.get('logical_qso_uuid')
            ).first()
            
            if logical_qso:
                divergence = Divergence(
                    logical_qso_id=logical_qso.id,
                    field_name=div.get('field_name'),
                    source_1_value=div.get('source_1_value'),
                    source_1_name=div.get('source_1_name'),
                    source_2_value=div.get('source_2_value'),
                    source_2_name=div.get('source_2_name'),
                    status=div.get('status', 'unresolved'),
                )
                self.db.add(divergence)
    
    def _log_audit(self, run: ReconciliationRun, result: ReconciliationResult):
        """Log audit event for reconciliation run."""
        audit = AuditEvent(
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
        )
        self.db.add(audit)
