"""Reconciliation Engine - Corrected algorithm for matching QSOs from multiple sources.

Key corrections from the original implementation:

1. NEVER use CALL+DATE as unique ID for LogicalQSO - each gets UUID
2. Time matching is a STRONG condition:
   - <= 60 seconds: can auto-match if other fields consistent
   - 61s to 5 minutes: NEVER auto-merge, mark as REVISAO_MANUAL
   - > 5 minutes: do not reconcile automatically
3. Level E matches are CANDIDATE ONLY - never auto-merge
4. TIME_ON absent requires special handling with multiple candidate detection
5. Proper MODE/SUBMODE comparison with operating_mode and mode_family
6. Real duplicate detection vs reimport detection
7. Coverage type affects "missing QSO" determination
"""

import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

from ..models.models import (
    MatchLevel, MatchStatus, DuplicateType, CoverageType
)


@dataclass
class NormalizedQSOData:
    """Normalized QSO data for reconciliation."""
    id: int
    callsign: str
    qso_date: str  # YYYY-MM-DD
    time_on: Optional[str]  # HH:MM:SS
    band: Optional[str]
    freq_hz: Optional[int]  # Frequency in Hz
    mode: Optional[str]
    submode: Optional[str]
    operating_mode: Optional[str]
    mode_family: Optional[str]
    rst_sent: Optional[str]
    rst_rcvd: Optional[str]
    grid: Optional[str]
    source_id: int
    source_name: str
    
    @property
    def freq_khz(self) -> Optional[float]:
        """Convert freq_hz to kHz for comparison."""
        if self.freq_hz is None:
            return None
        return self.freq_hz / 1000.0
    
    @property
    def time_seconds(self) -> Optional[int]:
        """Convert time_on to seconds since midnight."""
        if not self.time_on:
            return None
        try:
            parts = self.time_on.split(':')
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            seconds = int(parts[2]) if len(parts) > 2 else 0
            return hours * 3600 + minutes * 60 + seconds
        except (ValueError, IndexError):
            return None
    
    @property
    def has_time(self) -> bool:
        return self.time_on is not None and self.time_seconds is not None


@dataclass
class MatchCandidate:
    """A potential match between two QSOs."""
    qso1_id: int
    qso2_id: int
    match_level: MatchLevel
    match_status: MatchStatus
    score: float
    time_diff_seconds: Optional[int] = None
    freq_diff: Optional[float] = None
    reasoning: List[str] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)


@dataclass
class ReconciliationResult:
    """Result of reconciliation run."""
    logical_qsos: List[Dict[str, Any]]
    matches: List[MatchCandidate]
    divergences: List[Dict[str, Any]]
    duplicates: List[Dict[str, Any]]
    total_processed: int
    total_matched: int
    total_divergences: int
    total_duplicates: int


class ReconciliationEngine:
    """Corrected reconciliation engine for QSO matching."""
    
    # Score thresholds
    SCORE_AUTO_MATCH_A = 90  # Excellent match
    SCORE_AUTO_MATCH_B = 70  # Good match
    SCORE_REVIEW_C = 50     # Fair match
    SCORE_POSSIBLE_D = 30   # Poor match
    
    # Time thresholds (in seconds)
    TIME_EXACT_MATCH = 60       # Auto-match allowed
    TIME_REVIEW_THRESHOLD = 300  # 5 minutes - beyond this, no auto-match
    
    # Frequency tolerance (Hz) - 1000 Hz default
    FREQ_TOLERANCE_HZ = 1000  # Default tolerance in Hz
    FREQ_TOLERANCE_DIGITAL_HZ = 1000  # Hz for digital modes
    FREQ_TOLERANCE_PHONE_HZ = 3000    # Hz for phone modes
    FREQ_TOLERANCE_CW_HZ = 500        # Hz for CW
    
    def __init__(self):
        self.matches: List[MatchCandidate] = []
        self.logical_qsos: Dict[str, Dict[str, Any]] = {}
        self.divergences: List[Dict[str, Any]] = []
        self.duplicates: List[Dict[str, Any]] = []
    
    def reconcile(self, qsos: List[NormalizedQSOData]) -> ReconciliationResult:
        """Run reconciliation on a list of normalized QSOs."""
        self.matches = []
        self.logical_qsos = {}
        self.divergences = []
        self.duplicates = []
        
        # Group QSOs by callsign + date for initial candidate selection
        groups = self._group_by_callsign_date(qsos)
        
        # Process each group
        for (callsign, date), group_qsos in groups.items():
            self._process_group(callsign, date, group_qsos)
        
        # Build result
        return ReconciliationResult(
            logical_qsos=list(self.logical_qsos.values()),
            matches=self.matches,
            divergences=self.divergences,
            duplicates=self.duplicates,
            total_processed=len(qsos),
            total_matched=len(self.matches),
            total_divergences=len(self.divergences),
            total_duplicates=len(self.duplicates),
        )
    
    def _group_by_callsign_date(
        self, qsos: List[NormalizedQSOData]
    ) -> Dict[Tuple[str, str], List[NormalizedQSOData]]:
        """Group QSOs by callsign and date."""
        groups: Dict[Tuple[str, str], List[NormalizedQSOData]] = {}
        for qso in qsos:
            key = (qso.callsign.upper(), qso.qso_date)
            if key not in groups:
                groups[key] = []
            groups[key].append(qso)
        return groups
    
    def _process_group(
        self, 
        callsign: str, 
        date: str, 
        qsos: List[NormalizedQSOData]
    ):
        """Process a group of QSOs with same callsign and date.
        
        Uses COMPLETE-LINK clustering to properly handle:
        1. TIME_ON absent with multiple candidates - no auto-merge bridge
        2. Transitivity validation - A-B match + B-C match does NOT imply A-C match
           if A-C would be REVISAO_MANUAL or level E
        
        Key rule: A QSO can only join an auto-match cluster if it is AUTO_MATCH
        compatible with ALL existing members of that cluster.
        
        Special handling for TIME_ON absent:
        - If a QSO lacks TIME_ON and there are multiple time-separated candidates,
          the no-time QSO cannot auto-merge with any of them.
        """
        if len(qsos) == 1:
            # Single QSO - create logical QSO directly
            self._create_logical_qso([qsos[0]])
            return
        
        # Check for real duplicates within same source
        self._detect_real_duplicates(qsos)
        
        # Build complete match matrix
        n = len(qsos)
        match_matrix: Dict[Tuple[int, int], MatchCandidate] = {}
        
        # Track QSOs without time and those with time
        no_time_indices: Set[int] = set()
        has_time_indices: Set[int] = set()
        
        for i, qso in enumerate(qsos):
            if qso.has_time:
                has_time_indices.add(i)
            else:
                no_time_indices.add(i)
        
        for i, qso1 in enumerate(qsos):
            for j, qso2 in enumerate(qsos[i + 1:], i + 1):
                # Skip if same source (already handled by duplicate detection)
                if qso1.source_id == qso2.source_id:
                    continue
                
                candidate = self._evaluate_match(qso1, qso2)
                if candidate:
                    self.matches.append(candidate)
                    match_matrix[(i, j)] = candidate
                    match_matrix[(j, i)] = candidate
        
        # SPECIAL RULE: If a no-time QSO has multiple candidates with time
        # that are temporally incompatible (>5 min apart), mark all its matches
        # as requiring manual review
        blocked_no_time_matches: Set[Tuple[int, int]] = set()
        
        for no_time_idx in no_time_indices:
            # Find all candidates with time that could match this no-time QSO
            compatible_with_time: List[int] = []
            for time_idx in has_time_indices:
                key = (no_time_idx, time_idx) if no_time_idx < time_idx else (time_idx, no_time_idx)
                if key in match_matrix:
                    cand = match_matrix[key]
                    if cand.match_level in (MatchLevel.A, MatchLevel.B) and not cand.blocking_reasons:
                        compatible_with_time.append(time_idx)
            
            # If there are 2+ time-separated candidates, block auto-merge
            if len(compatible_with_time) >= 2:
                # Check if these candidates are temporally separated
                times_are_separated = False
                for idx1 in range(len(compatible_with_time)):
                    for idx2 in range(idx1 + 1, len(compatible_with_time)):
                        t1 = qsos[compatible_with_time[idx1]].time_seconds
                        t2 = qsos[compatible_with_time[idx2]].time_seconds
                        if t1 is not None and t2 is not None:
                            if abs(t1 - t2) > self.TIME_REVIEW_THRESHOLD:
                                times_are_separated = True
                                break
                    if times_are_separated:
                        break
                
                if times_are_separated:
                    # Block all auto-matches involving this no-time QSO
                    for time_idx in compatible_with_time:
                        key = (no_time_idx, time_idx) if no_time_idx < time_idx else (time_idx, no_time_idx)
                        blocked_no_time_matches.add(key)
                        # Update the match candidate to require manual review
                        if key in match_matrix:
                            old_cand = match_matrix[key]
                            new_cand = MatchCandidate(
                                qso1_id=old_cand.qso1_id,
                                qso2_id=old_cand.qso2_id,
                                match_level=MatchLevel.E,
                                match_status=MatchStatus.REVISAO_MANUAL,
                                score=old_cand.score,
                                time_diff_seconds=old_cand.time_diff_seconds,
                                freq_diff=old_cand.freq_diff,
                                reasoning=old_cand.reasoning + ["TIME_ON absent with multiple time-separated candidates"],
                                blocking_reasons=["Multiple plausible candidates exist with incompatible times"]
                            )
                            match_matrix[key] = new_cand
                            match_matrix[(key[1], key[0])] = new_cand
                            
                            # Also update in self.matches list
                            for idx, m in enumerate(self.matches):
                                if (m.qso1_id == new_cand.qso1_id and m.qso2_id == new_cand.qso2_id) or \
                                   (m.qso1_id == new_cand.qso2_id and m.qso2_id == new_cand.qso1_id):
                                    self.matches[idx] = new_cand
        
        # COMPLETE-LINK clustering: build clusters where ALL pairs are AUTO_MATCH compatible
        # Use iterative approach: start with singletons, merge only if complete-link condition holds
        clusters: List[Set[int]] = [{i} for i in range(n)]
        
        def can_merge_complete_link(cluster1: Set[int], cluster2: Set[int]) -> bool:
            """Check if all cross-pairs between clusters are AUTO_MATCH (A or B)."""
            for i in cluster1:
                for j in cluster2:
                    key = (i, j) if i < j else (j, i)
                    if key not in match_matrix:
                        return False
                    cand = match_matrix[key]
                    # Must be level A or B with no blocking reasons
                    if cand.match_level not in (MatchLevel.A, MatchLevel.B):
                        return False
                    if cand.blocking_reasons:
                        return False
                    # Also check if this match was explicitly blocked
                    if key in blocked_no_time_matches:
                        return False
            return True
        
        # Iteratively merge clusters using complete-link condition
        changed = True
        while changed:
            changed = False
            for i in range(len(clusters)):
                if not clusters[i]:  # Skip empty clusters
                    continue
                for j in range(i + 1, len(clusters)):
                    if not clusters[j]:  # Skip empty clusters
                        continue
                    
                    if can_merge_complete_link(clusters[i], clusters[j]):
                        # Merge cluster j into cluster i
                        clusters[i] = clusters[i].union(clusters[j])
                        clusters[j] = set()
                        changed = True
                        break
                if changed:
                    break
        
        # Create logical QSOs for each non-empty cluster
        for cluster in clusters:
            if cluster:
                cluster_qsos = [qsos[i] for i in sorted(cluster)]
                self._create_logical_qso(cluster_qsos)
    
    def _detect_real_duplicates(self, qsos: List[NormalizedQSOData]):
        """Detect real duplicates within the same source.
        
        CRITICAL: Only mark as REAL_DUPLICATE if duplicates are from SAME source.
        QSOs from different sources (QRZ vs WRL) with same data are NOT duplicates -
        they are the same QSO observed in multiple sources.
        """
        # Group by source first
        by_source: Dict[int, List[NormalizedQSOData]] = {}
        for qso in qsos:
            if qso.source_id not in by_source:
                by_source[qso.source_id] = []
            by_source[qso.source_id].append(qso)
        
        # Check for duplicates within each source
        for source_id, source_qsos in by_source.items():
            seen: Dict[str, List[NormalizedQSOData]] = {}
            
            for qso in source_qsos:
                # Fingerprint based on time if available, otherwise mode/band
                if qso.has_time:
                    key = f"{qso.time_on}|{qso.band}|{qso.mode}"
                else:
                    key = f"{qso.band}|{qso.mode}|{qso.grid}"
                
                if key not in seen:
                    seen[key] = []
                seen[key].append(qso)
            
            # Report duplicates only within this source
            for key, duplicates in seen.items():
                if len(duplicates) > 1:
                    self.duplicates.append({
                        'type': DuplicateType.REAL_DUPLICATE,
                        'source_id': source_id,
                        'qso_ids': [q.id for q in duplicates],
                        'description': f"Duplicate QSOs: {duplicates[0].callsign} "
                                       f"on {duplicates[0].qso_date}"
                    })
    
    def _evaluate_match(
        self, qso1: NormalizedQSOData, qso2: NormalizedQSOData
    ) -> Optional[MatchCandidate]:
        """Evaluate if two QSOs should be matched."""
        score = 0.0
        reasoning = []
        blocking_reasons = []
        
        # ========================================
        # CRITICAL: Time-based blocking rules
        # ========================================
        # When BOTH have time and differ by > 5 minutes => REVISAO_MANUAL
        # When ONE lacks time AND there are multiple candidates => mark for review
        
        time_diff = None
        both_have_time = qso1.has_time and qso2.has_time
        one_lacks_time = not (qso1.has_time and qso2.has_time) and (qso1.has_time or qso2.has_time)
        
        if both_have_time:
            time_diff = abs(qso1.time_seconds - qso2.time_seconds)
            
            if time_diff > self.TIME_REVIEW_THRESHOLD:
                # More than 5 minutes difference - NO AUTO MATCH
                blocking_reasons.append(
                    f"Time difference {time_diff}s exceeds 5 minute threshold"
                )
                return MatchCandidate(
                    qso1_id=qso1.id,
                    qso2_id=qso2.id,
                    match_level=MatchLevel.E,
                    match_status=MatchStatus.REVISAO_MANUAL,
                    score=0,
                    time_diff_seconds=time_diff,
                    blocking_reasons=blocking_reasons
                )
            
            elif time_diff > self.TIME_EXACT_MATCH:
                # Between 60s and 5 minutes - mark for manual review
                blocking_reasons.append(
                    f"Time difference {time_diff}s requires manual review"
                )
        
        # When one lacks time, we cannot auto-merge if the other has a time
        # that could conflict with another candidate. This is handled at cluster level,
        # but we flag it here as requiring extra scrutiny.
        # The actual blocking happens in complete-link clustering when multiple
        # time-separated candidates exist.
        
        # ========================================
        # Calculate match score
        # ========================================
        
        # Band match (strong evidence)
        if qso1.band and qso2.band:
            if qso1.band.upper() == qso2.band.upper():
                score += 25
                reasoning.append("Band matches")
            else:
                blocking_reasons.append(f"Band mismatch: {qso1.band} vs {qso2.band}")
                return self._create_low_level_candidate(qso1, qso2, blocking_reasons)
        
        # Mode family match
        if qso1.mode_family and qso2.mode_family:
            if qso1.mode_family == qso2.mode_family:
                score += 20
                reasoning.append(f"Mode family matches: {qso1.mode_family}")
            else:
                # Different mode families reduce score but don't block
                score -= 10
                reasoning.append(f"Mode family differs: {qso1.mode_family} vs {qso2.mode_family}")
        
        # Operating mode match (FT4 = FT4, MFSK+FT4 = FT4)
        if qso1.operating_mode and qso2.operating_mode:
            if qso1.operating_mode.upper() == qso2.operating_mode.upper():
                score += 15
                reasoning.append(f"Operating mode matches: {qso1.operating_mode}")
        
        # Frequency comparison (with tolerance in Hz)
        if qso1.freq_hz and qso2.freq_hz:
            freq_diff_hz = abs(qso1.freq_hz - qso2.freq_hz)  # Difference in Hz
            tolerance_hz = self._get_freq_tolerance(qso1.mode_family)
            
            if freq_diff_hz <= tolerance_hz:
                score += 15
                reasoning.append(f"Frequency within tolerance: {freq_diff_hz} Hz")
            else:
                score -= 5
                reasoning.append(f"Frequency difference: {freq_diff_hz} Hz")
        
        # Grid match (strong evidence if present)
        if qso1.grid and qso2.grid:
            if qso1.grid.upper() == qso2.grid.upper():
                score += 20
                reasoning.append("Grid matches")
            else:
                # Check if first 4 characters match
                if qso1.grid[:4].upper() == qso2.grid[:4].upper():
                    score += 10
                    reasoning.append("Grid partial match (4 chars)")
        
        # RST comparison
        if qso1.rst_sent and qso2.rst_sent:
            if qso1.rst_sent == qso2.rst_sent:
                score += 5
                reasoning.append("RST sent matches")
        
        # Time difference scoring (when both have time)
        if qso1.has_time and qso2.has_time:
            time_diff = abs(qso1.time_seconds - qso2.time_seconds)
            if time_diff <= 10:
                score += 25
                reasoning.append("Time match excellent (<10s)")
            elif time_diff <= 60:
                score += 20
                reasoning.append("Time match good (<60s)")
            elif time_diff <= 300:
                score += 10
                reasoning.append("Time match fair (<5min)")
        
        # ========================================
        # Determine match level
        # ========================================
        if blocking_reasons:
            # Has blocking reasons - cannot auto-merge
            match_level = MatchLevel.E
            match_status = MatchStatus.REVISAO_MANUAL
        elif score >= self.SCORE_AUTO_MATCH_A:
            match_level = MatchLevel.A
            match_status = MatchStatus.AUTO_MATCHED
        elif score >= self.SCORE_AUTO_MATCH_B:
            match_level = MatchLevel.B
            match_status = MatchStatus.AUTO_MATCHED
        elif score >= self.SCORE_REVIEW_C:
            match_level = MatchLevel.C
            match_status = MatchStatus.MANUAL_REVIEW
        elif score >= self.SCORE_POSSIBLE_D:
            match_level = MatchLevel.D
            match_status = MatchStatus.POSSIBLE_MATCH
        else:
            match_level = MatchLevel.E
            match_status = MatchStatus.REJECTED
        
        time_diff = None
        if qso1.has_time and qso2.has_time:
            time_diff = abs(qso1.time_seconds - qso2.time_seconds)
        
        freq_diff = None
        if qso1.freq_hz and qso2.freq_hz:
            freq_diff = abs(qso1.freq_hz - qso2.freq_hz)
        
        return MatchCandidate(
            qso1_id=qso1.id,
            qso2_id=qso2.id,
            match_level=match_level,
            match_status=match_status,
            score=score,
            time_diff_seconds=time_diff,
            freq_diff=freq_diff,
            reasoning=reasoning,
            blocking_reasons=blocking_reasons
        )
    
    def _get_freq_tolerance(self, mode_family: Optional[str]) -> int:
        """Get frequency tolerance in Hz based on mode family."""
        if mode_family == 'DIGITAL':
            return self.FREQ_TOLERANCE_DIGITAL_HZ
        elif mode_family == 'PHONE' or mode_family == 'SSB':
            return self.FREQ_TOLERANCE_PHONE_HZ
        elif mode_family == 'CW':
            return self.FREQ_TOLERANCE_CW_HZ
        return self.FREQ_TOLERANCE_HZ
    
    def _create_low_level_candidate(
        self, 
        qso1: NormalizedQSOData, 
        qso2: NormalizedQSOData,
        blocking_reasons: List[str]
    ) -> MatchCandidate:
        """Create a low-level match candidate when there are blocking issues."""
        time_diff = None
        if qso1.has_time and qso2.has_time:
            time_diff = abs(qso1.time_seconds - qso2.time_seconds)
        
        return MatchCandidate(
            qso1_id=qso1.id,
            qso2_id=qso2.id,
            match_level=MatchLevel.E,
            match_status=MatchStatus.REVISAO_MANUAL,
            score=0,
            time_diff_seconds=time_diff,
            blocking_reasons=blocking_reasons
        )
    
    def _create_logical_qso(
        self, 
        qsos: List[NormalizedQSOData],
        match: Optional[MatchCandidate] = None
    ):
        """Create a logical QSO from one or more normalized QSOs.
        
        IDEMPOTENCY: Uses deterministic UUID based on sorted normalized QSO IDs
        to ensure the same cluster always produces the same LogicalQSO.
        """
        import hashlib
        
        if not qsos:
            return
        
        # Use first QSO as base, then merge fields from others
        base = qsos[0]
        
        # Compute deterministic UUID from sorted normalized QSO IDs
        sorted_qso_ids = sorted([q.id for q in qsos])
        fingerprint_input = "|".join(str(id_) for id_ in sorted_qso_ids)
        cluster_fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()
        # Use first 36 chars of hex digest as UUID-like string
        deterministic_uuid = f"{cluster_fingerprint[:8]}-{cluster_fingerprint[8:12]}-{cluster_fingerprint[12:16]}-{cluster_fingerprint[16:20]}-{cluster_fingerprint[20:32]}"
        
        # Build canonical values field-by-field
        canonical = {
            'uuid': deterministic_uuid,
            'callsign': base.callsign,
            'qso_date': base.qso_date,
            'time_on': base.time_on,
            'time_off': base.time_off if hasattr(base, 'time_off') else None,
            'band': base.band,
            'freq_hz': base.freq_hz,
            'mode': base.mode,
            'submode': base.submode,
            'operating_mode': base.operating_mode,
            'mode_family': base.mode_family,
            'rst_sent': base.rst_sent,
            'rst_rcvd': base.rst_rcvd,
            'grid': base.grid,
            'dxcc': base.dxcc if hasattr(base, 'dxcc') else None,
            'country': base.country if hasattr(base, 'country') else None,
            'state': base.state if hasattr(base, 'state') else None,
            'county': base.county if hasattr(base, 'county') else None,
            'cqz': base.cqz if hasattr(base, 'cqz') else None,
            'ituz': base.ituz if hasattr(base, 'ituz') else None,
            'continent': base.continent if hasattr(base, 'continent') else None,
            'iota': base.iota if hasattr(base, 'iota') else None,
            'comment': base.comment if hasattr(base, 'comment') else None,
        }
        
        # Merge fields from additional QSOs (prefer non-null values)
        provenance = {
            'callsign': {'source': base.source_name, 'confidence': 1.0},
        }
        
        confirmations = {}
        
        for qso in qsos[1:]:
            # Fill in missing fields
            for field in ['time_on', 'band', 'freq_hz', 'mode', 'grid', 'rst_sent']:
                if not canonical.get(field) and getattr(qso, field, None):
                    canonical[field] = getattr(qso, field)
                    provenance[field] = {
                        'source': qso.source_name,
                        'confidence': 0.8
                    }
            
            # Track confirmations
            if hasattr(qso, 'qsl_rcvd') and qso.qsl_rcvd:
                confirmations[qso.source_name.lower()] = qso.qsl_rcvd
        
        canonical['confirmations'] = confirmations if confirmations else None
        canonical['field_provenance'] = provenance
        
        # Determine status based on match quality
        canonical['status'] = self._determine_cluster_status(qsos)
        canonical['divergence_count'] = 0
        canonical['source_links'] = [
            {'normalized_qso_id': q.id, 'source_name': q.source_name}
            for q in qsos
        ]
        
        # Check for divergences
        if len(qsos) > 1:
            self._detect_divergences(canonical['uuid'], qsos)
        
        self.logical_qsos[canonical['uuid']] = canonical
    
    def _determine_cluster_status(self, qsos: List[NormalizedQSOData]) -> str:
        """Determine the status of a LogicalQSO cluster.
        
        Rules:
        - Cluster with only AUTO_MATCHED A/B matches: "reconciled"
        - Singleton with no conflicting candidates: "reconciled"
        - QSO with REVISAO_MANUAL, POSSIBLE_MATCH, Level E, or time ambiguity: "needs_review"
        """
        if len(qsos) == 1:
            # Singleton - check if there are potential conflicts
            # For now, singletons are reconciled unless they have missing time
            # and there could be multiple candidates (handled during clustering)
            return 'reconciled'
        
        # Multi-source cluster - check match levels
        # If any pair would have been level E or requires manual review, mark as needs_review
        for i, qso1 in enumerate(qsos):
            for j, qso2 in enumerate(qsos[i+1:], i+1):
                if qso1.source_id == qso2.source_id:
                    continue
                
                # Evaluate match between these two
                candidate = self._evaluate_match(qso1, qso2)
                if candidate:
                    # Level E or manual review required
                    if candidate.match_level == MatchLevel.E:
                        return 'needs_review'
                    if candidate.match_status in (MatchStatus.REVISAO_MANUAL, MatchStatus.MANUAL_REVIEW, MatchStatus.POSSIBLE_MATCH):
                        return 'needs_review'
        
        # All pairs are auto-matched (A or B)
        return 'reconciled'
    
    def _detect_divergences(self, logical_uuid: str, qsos: List[NormalizedQSOData]):
        """Detect field divergences between sources."""
        fields_to_check = ['freq_hz', 'mode', 'band', 'grid', 'rst_sent', 'time_on']
        
        for field in fields_to_check:
            values = {}
            for qso in qsos:
                value = getattr(qso, field, None)
                if value:
                    values[qso.source_name] = str(value)
            
            # If we have different values from different sources
            unique_values = set(values.values())
            if len(unique_values) > 1:
                source_names = list(values.keys())
                self.divergences.append({
                    'logical_qso_uuid': logical_uuid,
                    'field_name': field,
                    'source_1_value': values.get(source_names[0]),
                    'source_1_name': source_names[0],
                    'source_2_value': values.get(source_names[1]),
                    'source_2_name': source_names[1],
                    'status': 'unresolved'
                })
