"""Tests for ADIF parser."""

import pytest
from app.adif.parser import ADIFParser, parse_adif_content


class TestADIFParser:
    """Tests for ADIF parsing."""
    
    def test_parse_simple_record(self):
        """Test parsing a simple ADIF record."""
        content = """<ADIF_VER:5>3.1.7
<EOH>
<CALL:6>PU2BRU <QSO_DATE:8>20240115 <TIME_ON:6>120000 <BAND:3>20M <MODE:3>FT4 <FREQ:7>14.0760 <RST_SENT:3>599 <EOR>
"""
        records, errors = parse_adif_content(content)
        
        assert len(records) == 1
        assert len(errors) == 0
        
        record = records[0]
        assert record['CALL'] == 'PU2BRU'
        assert record['QSO_DATE'] == '2024-01-15'
        assert record['TIME_ON'] == '12:00:00'
        assert record['BAND'] == '20M'
        assert record['MODE'] == 'FT4'
    
    def test_parse_multiple_records(self):
        """Test parsing multiple ADIF records."""
        content = """<ADIF_VER:5>3.1.7
<EOH>
<CALL:6>PU2BRU <QSO_DATE:8>20240115 <TIME_ON:6>120000 <BAND:3>20M <MODE:3>FT4 <EOR>
<CALL:6>PU2BRU <QSO_DATE:8>20240115 <TIME_ON:6>130000 <BAND:3>20M <MODE:3>FT4 <EOR>
<CALL:6>PU2BRU <QSO_DATE:8>20240115 <TIME_ON:6>140000 <BAND:3>40M <MODE:2>SSB <EOR>
"""
        records, errors = parse_adif_content(content)
        
        assert len(records) == 3
    
    def test_mode_classification_ft4(self):
        """Test mode classification for FT4."""
        parser = ADIFParser()
        
        op_mode, family = parser.classify_mode('FT4')
        assert op_mode == 'FT4'
        assert family == 'DIGITAL'
    
    def test_mode_classification_mfsk_ft4(self):
        """Test mode classification for MFSK with FT4 submode."""
        parser = ADIFParser()
        
        op_mode, family = parser.classify_mode('MFSK', 'FT4')
        assert op_mode == 'FT4'
        assert family == 'DIGITAL'
    
    def test_mode_classification_usb_ssb(self):
        """Test mode classification for USB (should be SSB family)."""
        parser = ADIFParser()
        
        op_mode, family = parser.classify_mode('USB')
        assert op_mode == 'USB'
        assert family == 'SSB'
    
    def test_fingerprint_same_data(self):
        """Test that same data produces same fingerprint."""
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
        
        assert fp1 == fp2
    
    def test_fingerprint_different_data(self):
        """Test that different data produces different fingerprint."""
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
            'TIME_ON': '13:00:00',  # Different time
            'BAND': '20M',
            'MODE': 'FT4',
            'FREQ': 14076.0,
        }
        
        fp1 = parser.compute_fingerprint(record1)
        fp2 = parser.compute_fingerprint(record2)
        
        assert fp1 != fp2
