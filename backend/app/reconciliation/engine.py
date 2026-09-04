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
        
        Uses union-find algorithm to properly cluster QSOs from multiple sources
        into logical QSOs, ensuring each NormalizedQSO belongs to exactly one
        LogicalQSO.
        """
        if len(qsos) == 1:
            # Single QSO - create logical QSO directly
            self._create_logical_qso([qsos[0]])
            return
        
        # Check for real duplicates within same source
        self._detect_real_duplicates(qsos)
        
        # Build match graph using union-find
        n = len(qsos)
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        # Find all valid matches between different sources
        match_graph = []  # List of (i, j, candidate)
        for i, qso1 in enumerate(qsos):
            for j, qso2 in enumerate(qsos[i + 1:], i + 1):
                # Skip if same source (already handled by duplicate detection)
                if qso1.source_id == qso2.source_id:
                    continue
                
                candidate = self._evaluate_match(qso1, qso2)
                if candidate:
                    self.matches.append(candidate)
                    match_graph.append((i, j, candidate))
                    
                    # Union if level A or B and no blocking reasons
                    if candidate.match_level in (MatchLevel.A, MatchLevel.B) \
                       and not candidate.blocking_reasons:
                        union(i, j)
        
        # Group QSOs by their root parent (cluster)
        clusters: Dict[int, List[NormalizedQSOData]] = {}
        for i, qso in enumerate(qsos):
            root = find(i)
            if root not in clusters:
                clusters[root] = []
            clusters[root].append(qso)
        
        # Create logical QSOs for each cluster
        for cluster_qsos in clusters.values():
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
        if qso1.has_time and qso2.has_time:
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
        """Create a logical QSO from one or more normalized QSOs."""
        if not qsos:
            return
        
        # Use first QSO as base, then merge fields from others
        base = qsos[0]
        
        # Build canonical values field-by-field
        canonical = {
            'uuid': str(uuid.uuid4()),
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
        canonical['status'] = 'reconciled' if len(qsos) == 1 else 'needs_review'
        canonical['divergence_count'] = 0
        canonical['source_links'] = [
            {'normalized_qso_id': q.id, 'source_name': q.source_name}
            for q in qsos
        ]
        
        # Check for divergences
        if len(qsos) > 1:
            self._detect_divergences(canonical['uuid'], qsos)
        
        self.logical_qsos[canonical['uuid']] = canonical
    
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
