"""Tests for the reconciliation engine.

These tests verify the corrected reconciliation algorithm:
- Time-based blocking rules
- Match level E never auto-merges
- Multiple QSOs same call/date handled correctly
- Mode family matching (FT4, SSB, etc.)
"""

import pytest
from datetime import datetime

from app.reconciliation.engine import (
    ReconciliationEngine,
    NormalizedQSOData,
    MatchLevel,
    MatchStatus,
)


def make_qso(
    id_: int,
    callsign: str = "PU2BRU",
    date: str = "2024-01-15",
    time: str = "12:00:00",
    band: str = "20M",
    freq_hz: int = 14076000,  # Frequency in Hz (14.076 MHz * 1000000)
    mode: str = "FT4",
    mode_family: str = "DIGITAL",
    operating_mode: str = "FT4",
    source_id: int = 1,
    source_name: str = "QRZ",
    grid: str = "GG55",
):
    """Helper to create NormalizedQSOData."""
    return NormalizedQSOData(
        id=id_,
        callsign=callsign,
        qso_date=date,
        time_on=time,
        band=band,
        freq_hz=freq_hz,
        mode=mode,
        submode=None,
        operating_mode=operating_mode,
        mode_family=mode_family,
        rst_sent="599",
        rst_rcvd="599",
        grid=grid,
        source_id=source_id,
        source_name=source_name,
    )


class TestTimeBasedMatching:
    """TESTE A, B, C: Time-based matching rules."""
    
    def test_same_call_date_time_diff_23_seconds_match(self):
        """TESTE A: Same CALL/date/band, 23 second difference -> MATCH."""
        engine = ReconciliationEngine()
        
        qso1 = make_qso(id_=1, time="12:00:00", source_id=1, source_name="QRZ")
        qso2 = make_qso(id_=2, time="12:00:23", source_id=2, source_name="WRL")
        
        result = engine.reconcile([qso1, qso2])
        
        # Should have 1 match
        assert len(result.matches) == 1
        match = result.matches[0]
        
        # Should be auto-matched (level A or B)
        assert match.match_level in (MatchLevel.A, MatchLevel.B)
        assert match.match_status == MatchStatus.AUTO_MATCHED
        
        # Should have 1 logical QSO (merged)
        assert len(result.logical_qsos) == 1
    
    def test_same_call_date_time_diff_8_hours_no_match(self):
        """TESTE B: Same CALL/date/band, 8 hour difference -> NO MATCH."""
        engine = ReconciliationEngine()
        
        qso1 = make_qso(id_=1, time="08:00:00", source_id=1, source_name="QRZ")
        qso2 = make_qso(id_=2, time="16:00:00", source_id=2, source_name="WRL")
        
        result = engine.reconcile([qso1, qso2])
        
        # Time diff is 8 hours = 28800 seconds > 300 seconds threshold
        # Should NOT auto-match
        assert len(result.matches) >= 1  # May still create a candidate
        match = result.matches[0]
        
        # Should be level E (candidate only) with blocking reason
        assert match.match_level == MatchLevel.E
        assert match.match_status == MatchStatus.REVISAO_MANUAL
        assert len(match.blocking_reasons) > 0
        
        # Should have 2 separate logical QSOs
        assert len(result.logical_qsos) == 2
    
    def test_same_call_two_qsos_same_day_different_times(self):
        """TESTE C: Same CALL has 2 different QSOs same day -> 2 LogicalQSOs."""
        engine = ReconciliationEngine()
        
        # Two QSOs from QRZ at different times
        qso1_qrz = make_qso(id_=1, time="10:00:00", source_id=1, source_name="QRZ")
        qso2_qrz = make_qso(id_=2, time="14:00:00", source_id=1, source_name="QRZ")
        
        # One QSO from WRL matching first one
        qso1_wrl = make_qso(id_=3, time="10:00:15", source_id=2, source_name="WRL")
        
        result = engine.reconcile([qso1_qrz, qso2_qrz, qso1_wrl])
        
        # Should have at least 2 logical QSOs (the 14:00 one can't match anything)
        assert len(result.logical_qsos) >= 2
        
        # The 14:00 QSO should be separate
        logical_callsigns = [lq['callsign'] for lq in result.logical_qsos]
        assert len(logical_callsigns) >= 2


class TestCrossSourceMatching:
    """TESTE D, E: Cross-source matching."""
    
    def test_qrz_wrl_same_time_not_missing(self):
        """TESTE D: QRZ has QSO 12:39 and WRL has 12:39 -> not missing."""
        engine = ReconciliationEngine()
        
        qso_qrz = make_qso(id_=1, time="12:39:00", source_id=1, source_name="QRZ")
        qso_wrl = make_qso(id_=2, time="12:39:00", source_id=2, source_name="WRL")
        
        result = engine.reconcile([qso_qrz, qso_wrl])
        
        # Should match and merge
        assert len(result.logical_qsos) == 1
        assert len(result.matches) == 1
        assert result.matches[0].match_status == MatchStatus.AUTO_MATCHED
    
    def test_qrz_1239_wrl_only_1800_not_same_qso(self):
        """TESTE E: QRZ has 12:39, WRL only has 18:00 -> not same QSO."""
        engine = ReconciliationEngine()
        
        qso_qrz = make_qso(id_=1, time="12:39:00", source_id=1, source_name="QRZ")
        qso_wrl = make_qso(id_=2, time="18:00:00", source_id=2, source_name="WRL")
        
        result = engine.reconcile([qso_qrz, qso_wrl])
        
        # Should NOT be considered same QSO
        # Time difference is > 5 hours
        assert len(result.logical_qsos) == 2


class TestModeMatching:
    """TESTE F, G: Mode family matching."""
    
    def test_mfsk_submode_ft4_equivalent(self):
        """TESTE F: MFSK+SUBMODE=FT4 should equal FT4."""
        engine = ReconciliationEngine()
        
        qso1 = make_qso(
            id_=1, 
            mode="MFSK", 
            source_id=1, 
            source_name="QRZ",
            time="12:00:00"
        )
        qso1.submode = "FT4"
        qso1.operating_mode = "FT4"
        
        qso2 = make_qso(
            id_=2, 
            mode="FT4", 
            source_id=2, 
            source_name="WRL",
            time="12:00:10"
        )
        qso2.submode = None
        qso2.operating_mode = "FT4"
        
        result = engine.reconcile([qso1, qso2])
        
        # Should match well due to same operating mode
        assert len(result.matches) == 1
        assert result.matches[0].match_status == MatchStatus.AUTO_MATCHED
    
    def test_usb_ssb_same_family(self):
        """TESTE G: USB and SSB are same family."""
        engine = ReconciliationEngine()
        
        qso1 = make_qso(
            id_=1,
            mode="USB",
            mode_family="SSB",
            operating_mode="USB",
            source_id=1,
            source_name="QRZ",
            time="12:00:00",
            band="40M",
            freq_hz=7200000,
        )
        
        qso2 = make_qso(
            id_=2,
            mode="SSB",
            mode_family="SSB",
            operating_mode="SSB",
            source_id=2,
            source_name="WRL",
            time="12:00:10",
            band="40M",
            freq_hz=7200000,
        )
        
        result = engine.reconcile([qso1, qso2])
        
        # Should match - same mode family
        assert len(result.matches) == 1


class TestFrequencyTolerance:
    """TESTE H: Frequency tolerance."""
    
    def test_freq_210761_vs_210769_tolerance(self):
        """TESTE H: Frequency 21076100 vs 21076900 Hz (800 Hz diff) -> within tolerance."""
        engine = ReconciliationEngine()
        
        qso1 = make_qso(
            id_=1,
            freq_hz=21076100,
            source_id=1,
            source_name="QRZ",
            time="12:00:00",
        )
        
        qso2 = make_qso(
            id_=2,
            freq_hz=21076900,
            source_id=2,
            source_name="WRL",
            time="12:00:10",
        )
        
        result = engine.reconcile([qso1, qso2])
        
        # Difference is 800 Hz, within 1000 Hz tolerance
        assert len(result.matches) == 1
        assert result.matches[0].freq_diff == 800  # Hz


class TestLevelENoAutoMerge:
    """TESTE J: Level E never auto-merges."""
    
    def test_level_e_never_auto_merge(self):
        """TESTE J: Level E matches are candidate only, never auto-merge."""
        engine = ReconciliationEngine()
        
        # Create QSOs that will get level E (poor match)
        qso1 = make_qso(
            id_=1,
            band="20M",
            source_id=1,
            source_name="QRZ",
            time="12:00:00",
        )
        
        qso2 = make_qso(
            id_=2,
            band="40M",  # Different band - blocking
            source_id=2,
            source_name="WRL",
            time="12:00:10",
        )
        
        result = engine.reconcile([qso1, qso2])
        
        # If there's a match, it must be level E
        for match in result.matches:
            if match.match_level == MatchLevel.E:
                assert match.match_status != MatchStatus.AUTO_MATCHED
                assert match.match_status in (MatchStatus.REVISAO_MANUAL, MatchStatus.REJECTED)


class TestDuplicateDetection:
    """TESTE K, L: Duplicate detection."""
    
    def test_same_file_imported_twice_no_duplicate(self):
        """TESTE K: Same file imported twice -> no duplicate records.
        
        This is tested at service level, but we verify fingerprint logic here.
        """
        from app.adif.parser import ADIFParser
        
        parser = ADIFParser()
        
        record1 = {
            'CALL': 'PU2BRU',
            'QSO_DATE': '2024-01-15',
            'TIME_ON': '12:00:00',
            'BAND': '20M',
            'MODE': 'FT4',
            'FREQ': 14076.0,
        }
        
        record2 = {
            'CALL': 'PU2BRU',
            'QSO_DATE': '2024-01-15',
            'TIME_ON': '12:00:00',
            'BAND': '20M',
            'MODE': 'FT4',
            'FREQ': 14076.0,
        }
        
        fp1 = parser.compute_fingerprint(record1)
        fp2 = parser.compute_fingerprint(record2)
        
        # Same data = same fingerprint
        assert fp1 == fp2
    
    def test_real_duplicates_within_source(self):
        """TESTE L: Two duplicate lines within same source -> DUPLICIDADE_REAL.
        
        This is tested at service level, but we verify fingerprint logic here.
        """
        from app.adif.parser import ADIFParser
        
        parser = ADIFParser()
        
        record1 = {
            'CALL': 'PU2BRU',
            'QSO_DATE': '2024-01-15',
            'TIME_ON': '12:00:00',
            'BAND': '20M',
            'MODE': 'FT4',
            'FREQ': 14076.0,
        }
        
        record2 = {
            'CALL': 'PU2BRU',
            'QSO_DATE': '2024-01-15',
            'TIME_ON': '12:00:00',
            'BAND': '20M',
            'MODE': 'FT4',
            'FREQ': 14076.0,
        }
        
        fp1 = parser.compute_fingerprint(record1)
        fp2 = parser.compute_fingerprint(record2)
        
        # Same data = same fingerprint
        assert fp1 == fp2
    
    def test_real_duplicates_within_source_engine(self):
        """TESTE L: Two identical QSOs from same source -> REAL_DUPLICATE detected by engine."""
        engine = ReconciliationEngine()
        
        # Two identical QSOs from same source
        qso1 = make_qso(id_=1, time="12:00:00", source_id=1, source_name="QRZ")
        qso2 = make_qso(id_=2, time="12:00:00", source_id=1, source_name="QRZ")
        
        result = engine.reconcile([qso1, qso2])
        
        # Should detect as real duplicate
        assert len(result.duplicates) >= 1
        assert result.duplicates[0]['type'].value == "REAL_DUPLICATE"


class TestTimeOnAbsent:
    """TESTE I: TIME_ON absent with multiple candidates -> REVISAO_MANUAL."""
    
    def test_time_on_absent_multiple_candidates_manual_review(self):
        """TESTE I: TIME_ON ausente + múltiplos candidatos plausíveis => REVISAO_MANUAL.
        
        Scenario:
        QRZ: K1ABC sem TIME_ON, 20M, FT8
        WRL: K1ABC 12:00, 20M, FT8
        MSHV: K1ABC 18:00, 20M, FT8
        
        Result: No auto-merge for the one without time. Mark as REVISAO_MANUAL.
        """
        engine = ReconciliationEngine()
        
        # QRZ without time
        qso_qrz = make_qso(
            id_=1, 
            time="",  # No time
            source_id=1, 
            source_name="QRZ",
            band="20M",
            freq_hz=14076000,
        )
        qso_qrz.time_on = None
        qso_qrz.has_time  # Recalculate property
        
        # WRL at 12:00
        qso_wrl = make_qso(
            id_=2, 
            time="12:00:00", 
            source_id=2, 
            source_name="WRL",
            band="20M",
            freq_hz=14076000,
        )
        
        # MSHV at 18:00
        qso_mshv = make_qso(
            id_=3, 
            time="18:00:00", 
            source_id=3, 
            source_name="MSHV",
            band="20M",
            freq_hz=14076000,
        )
        
        result = engine.reconcile([qso_qrz, qso_wrl, qso_mshv])
        
        # Should have matches but the one without time should not auto-merge
        # There should be at least 2 logical QSOs since 12:00 and 18:00 are different
        assert len(result.logical_qsos) >= 2
        
        # Check that matches involving the no-time QSO are marked for review
        for match in result.matches:
            if match.qso1_id == 1 or match.qso2_id == 1:
                # The QSO without time should not auto-merge when there are multiple candidates
                assert match.match_status in (
                    MatchStatus.REVISAO_MANUAL, 
                    MatchStatus.MANUAL_REVIEW,
                    MatchStatus.POSSIBLE_MATCH
                ), f"Expected manual review for match involving no-time QSO, got {match.match_status}"


class TestUpdateCorrectQSO:
    """TESTE M: Updating one of two QSOs with same CALL/date affects only correct one."""
    
    def test_update_affects_only_correct_qso(self):
        """TESTE M: dois QSOs do mesmo CALL/data; alterar um deve atingir SOMENTE o QSO correto.
        
        Scenario:
        K1ABC 2026-09-03 12:00
        K1ABC 2026-09-03 18:00
        
        Update operation on first should only affect the 12:00 QSO.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base, get_db
        from app.models.models import LogicalQSO, Source
        from app.services.qso_update_service import QSOUpdateService
        from datetime import datetime
        
        # Create test database
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        try:
            # Create source
            source = Source(name="TEST", description="Test source")
            db.add(source)
            db.commit()
            
            # Create two logical QSOs same call/date different times
            lq1 = LogicalQSO(
                uuid="test-uuid-1",
                callsign="K1ABC",
                qso_date="2026-09-03",
                time_on="12:00:00",
                band="20M",
                freq_hz=14076000,
                mode="FT4",
            )
            lq2 = LogicalQSO(
                uuid="test-uuid-2",
                callsign="K1ABC",
                qso_date="2026-09-03",
                time_on="18:00:00",
                band="20M",
                freq_hz=14076000,
                mode="FT4",
            )
            db.add(lq1)
            db.add(lq2)
            db.commit()
            
            # Now update ONLY the first one (12:00)
            update_data = {
                "grid": "GG55AA",
                "comment": "Updated QSO at 12:00",
            }
            
            service = QSOUpdateService(db)
            updated_qso = service.update_logical_qso(lq1.id, update_data, reason="Test update")
            
            # Verify only the first QSO was updated
            db.refresh(lq1)
            db.refresh(lq2)
            
            assert lq1.grid == "GG55AA"
            assert lq1.comment == "Updated QSO at 12:00"
            
            # Second QSO should remain unchanged
            assert lq2.grid is None or lq2.grid != "GG55AA"
            assert lq2.comment is None or lq2.comment != "Updated QSO at 12:00"
            
        finally:
            db.close()


class TestSafeCountyUpdate:
    """TESTE N: REPLACE CNTY preserves all other fields."""
    
    def test_county_update_preserves_other_fields(self):
        """TESTE N: REPLACE de CNTY deve preservar todos os demais campos.
        
        Build a safe update where:
        - CNTY changes from empty to "Campinas"
        - All other fields remain identical
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base
        from app.models.models import LogicalQSO, Source
        from app.services.safe_update_service import SafeUpdateService
        from datetime import datetime
        
        # Create test database
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        try:
            # Create source
            source = Source(name="TEST", description="Test source")
            db.add(source)
            db.commit()
            
            # Create a logical QSO with full data
            original_qso = LogicalQSO(
                uuid="test-uuid-cnty",
                callsign="PU2BRU",
                qso_date="2024-01-15",
                time_on="12:00:00",
                time_off="12:30:00",
                band="20M",
                freq_hz=14076000,
                mode="FT4",
                submode=None,
                operating_mode="FT4",
                mode_family="DIGITAL",
                rst_sent="599",
                rst_rcvd="599",
                grid="GG55",
                dxcc=108,
                country="Brazil",
                state="SP",
                county="",  # Empty initially
                cqz=11,
                ituz=15,
                continent="SA",
                iota=None,
                comment="Original comment",
            )
            db.add(original_qso)
            db.commit()
            db.refresh(original_qso)
            
            # Build safe update for CNTY only
            service = SafeUpdateService(db)
            
            update_spec = {
                "county": "Campinas",
            }
            
            # Use the safe update service which preserves other fields
            result = service.build_safe_update(
                original_qso.id,
                update_spec,
                reason="Adding county information",
            )
            
            # Verify the update preserves all other fields
            assert result['preserved_fields'] is not None
            
            # Check that critical fields are preserved
            preserved = result['before']
            assert preserved['callsign'] == "PU2BRU"
            assert preserved['qso_date'] == "2024-01-15"
            assert preserved['time_on'] == "12:00:00"
            assert preserved['band'] == "20M"
            assert preserved['freq_hz'] == 14076000
            assert preserved['mode'] == "FT4"
            assert preserved['grid'] == "GG55"
            assert preserved['dxcc'] == 108
            assert preserved['comment'] == "Original comment"
            
            # County should change
            assert result['after']['county'] == "Campinas"
            
            # All other fields should remain the same
            assert result['after']['callsign'] == preserved['callsign']
            assert result['after']['qso_date'] == preserved['qso_date']
            assert result['after']['time_on'] == preserved['time_on']
            assert result['after']['band'] == preserved['band']
            assert result['after']['freq_hz'] == preserved['freq_hz']
            assert result['after']['mode'] == preserved['mode']
            assert result['after']['grid'] == preserved['grid']
            assert result['after']['dxcc'] == preserved['dxcc']
            assert result['after']['comment'] == preserved['comment']
            
        finally:
            db.close()


class TestMultiSourceClustering:
    """Test multi-source clustering - QRZ+WRL+MSHV should produce exactly 1 LogicalQSO."""
    
    def test_three_sources_one_logical_qso(self):
        """Multi-source test: QRZ 12:00:00, WRL 12:00:10, MSHV 12:00:05 => 1 LogicalQSO with 3 source_links."""
        engine = ReconciliationEngine()
        
        qso_qrz = make_qso(
            id_=1, 
            time="12:00:00", 
            source_id=1, 
            source_name="QRZ",
            band="20M",
            freq_hz=14076000,
        )
        qso_wrl = make_qso(
            id_=2, 
            time="12:00:10", 
            source_id=2, 
            source_name="WRL",
            band="20M",
            freq_hz=14076000,
        )
        qso_mshv = make_qso(
            id_=3, 
            time="12:00:05", 
            source_id=3, 
            source_name="MSHV",
            band="20M",
            freq_hz=14076000,
        )
        
        result = engine.reconcile([qso_qrz, qso_wrl, qso_mshv])
        
        # Should produce EXACTLY 1 LogicalQSO
        assert len(result.logical_qsos) == 1, f"Expected 1 LogicalQSO, got {len(result.logical_qsos)}"
        
        # Each NormalizedQSO should appear exactly once
        logical_qso = result.logical_qsos[0]
        source_links = logical_qso.get('source_links', [])
        
        # Should have 3 source links
        assert len(source_links) == 3, f"Expected 3 source_links, got {len(source_links)}"
        
        # Verify all three sources are present
        source_names = [link.get('source_name') for link in source_links]
        assert "QRZ" in source_names
        assert "WRL" in source_names
        assert "MSHV" in source_names
