"""ADIF Parser - Sequential parser for ADIF 3.1.7 format.

This parser reads ADIF files sequentially:
1. Read tag name
2. Read tag length
3. Consume exactly N characters
4. Continue from there

Supports ADI format (not ADX which requires XML parser).
"""

import re
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime


class ADIFParser:
    """Sequential ADIF parser supporting ADIF 3.1.7 specification."""
    
    # ADIF field types
    STRING_FIELDS = {
        'CALL', 'QSO_DATE', 'TIME_ON', 'TIME_OFF', 'BAND', 'MODE', 'SUBMODE',
        'RST_SENT', 'RST_RCVD', 'GRID', 'COMMENT', 'COUNTRY', 'STATE', 'COUNTY',
        'QSL_SENT', 'QSL_RCVD', 'EQSL_SENT', 'EQSL_RCVD', 'LOTW_SENT', 'LOTW_RCVD',
        'CONT', 'IOTA', 'PFX', 'SOTA_REF', 'WWFF_REF', 'OPERATOR', 'STATION_CALLSIGN',
        'MY_CITY', 'MY_COUNTY', 'MY_STATE', 'MY_GRID', 'MY_COUNTRY', 'MY_CQ_ZONE',
        'MY_ITU_ZONE', 'QSL_VIA', 'NOTES', 'DXCC', 'CQZ', 'ITUZ', 'NAME', 'ELMAC'
    }
    
    NUMERIC_FIELDS = {'FREQ', 'DXCC', 'CQZ', 'ITUZ', 'AGE', 'YEAR'}
    
    # Mode families
    MODE_FAMILIES = {
        'SSB': ['SSB', 'USB', 'LSB', 'AM'],
        'CW': ['CW'],
        'DIGITAL': ['FT8', 'FT4', 'MFSK', 'RTTY', 'PSK31', 'PSK63', 'OLIVIA', 'CONTESTIA',
                  'DOMINO', 'HELL', 'THROB', 'JT9', 'JT65', 'Q65', 'ISCAT', 'MSK144',
                  'GREATH', 'MT63', 'PKT', 'PACKET'],
        'FM': ['FM', 'DFM', 'WFM'],
    }
    
    def __init__(self):
        self.records: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.current_position = 0
        self.file_content = ""
        
    def parse(self, content: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Parse ADIF content and return records and errors."""
        self.file_content = content
        self.records = []
        self.errors = []
        self.current_position = 0
        
        # Remove BOM if present
        if content.startswith('\ufeff'):
            content = content[1:]
        
        # Find header end
        header_end = content.find('<EOH>')
        if header_end == -1:
            # No header, start from beginning
            self.current_position = 0
        else:
            self.current_position = header_end + 5  # Skip <EOH>
        
        # Parse records
        while self.current_position < len(content):
            record = self._parse_record()
            if record:
                self.records.append(record)
            elif self.current_position < len(content):
                # Skip whitespace and try again
                self._skip_whitespace()
        
        return self.records, self.errors
    
    def _skip_whitespace(self):
        """Skip whitespace characters."""
        while self.current_position < len(self.file_content) and \
              self.file_content[self.current_position] in ' \t\n\r':
            self.current_position += 1
    
    def _parse_record(self) -> Optional[Dict[str, Any]]:
        """Parse a single ADIF record starting at current position."""
        record = {}
        
        while self.current_position < len(self.file_content):
            self._skip_whitespace()
            
            if self.current_position >= len(self.file_content):
                break
            
            # Check for end of record
            if self.file_content[self.current_position:self.current_position + 4] == '<EOR>':
                self.current_position += 4
                return record
            
            # Parse field
            field_name, field_value = self._parse_field()
            if field_name:
                record[field_name.upper()] = self._normalize_field(field_name, field_value)
            else:
                # Unable to parse field, skip character
                self.current_position += 1
        
        # Return partial record if we have data
        return record if record else None
    
    def _parse_field(self) -> Tuple[Optional[str], Optional[str]]:
        """Parse a single ADIF field: <TAG:length:type>value"""
        if self.current_position >= len(self.file_content):
            return None, None
        
        # Look for opening bracket
        if self.file_content[self.current_position] != '<':
            return None, None
        
        # Find closing bracket
        bracket_pos = self.file_content.find('>', self.current_position)
        if bracket_pos == -1:
            self.errors.append(f"Unclosed tag at position {self.current_position}")
            return None, None
        
        # Extract tag definition
        tag_def = self.file_content[self.current_position + 1:bracket_pos]
        self.current_position = bracket_pos + 1
        
        # Parse tag name, length, and optional type
        match = re.match(r'^([A-Z_]+)(?::(\d+))?(?::([A-Z]))?', tag_def, re.IGNORECASE)
        if not match:
            self.errors.append(f"Invalid tag definition: {tag_def}")
            return None, None
        
        field_name = match.group(1).upper()
        length = int(match.group(2)) if match.group(2) else 0
        field_type = match.group(3)
        
        # Read value (exactly 'length' characters)
        if length > 0:
            if self.current_position + length > len(self.file_content):
                self.errors.append(
                    f"Unexpected end of file reading {field_name} "
                    f"(expected {length} chars at position {self.current_position})"
                )
                return field_name, ""
            
            field_value = self.file_content[
                self.current_position:self.current_position + length
            ]
            self.current_position += length
        else:
            field_value = ""
        
        return field_name, field_value
    
    def _normalize_field(self, field_name: str, value: str) -> Any:
        """Normalize field value based on field type."""
        if not value:
            return None
        
        field_name = field_name.upper()
        
        # Numeric fields
        if field_name in self.NUMERIC_FIELDS:
            try:
                if '.' in value:
                    return float(value)
                return int(value)
            except ValueError:
                return value
        
        # Date normalization (YYYYMMDD -> YYYY-MM-DD)
        if field_name == 'QSO_DATE' and len(value) == 8:
            return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        
        # Time normalization (HHMMSS -> HH:MM:SS)
        if field_name in ('TIME_ON', 'TIME_OFF') and len(value) >= 4:
            if len(value) == 4:
                return f"{value[:2]}:{value[2:4]}:00"
            elif len(value) >= 6:
                return f"{value[:2]}:{value[2:4]}:{value[4:6]}"
            return value
        
        return value
    
    def compute_fingerprint(self, record: Dict[str, Any]) -> str:
        """Compute a fingerprint hash for a record for deduplication."""
        # Use key fields for fingerprint
        key_fields = ['CALL', 'QSO_DATE', 'TIME_ON', 'BAND', 'MODE', 'FREQ']
        fingerprint_data = "|".join(
            str(record.get(field, '')) for field in key_fields
        )
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()
    
    def classify_mode(self, mode: str, submode: Optional[str] = None) -> Tuple[str, str]:
        """Classify mode into operating_mode and mode_family.
        
        Returns:
            Tuple of (operating_mode, mode_family)
        """
        mode = mode.upper() if mode else ""
        submode = submode.upper() if submode else ""
        
        # Determine operating mode
        if submode:
            operating_mode = submode
        elif mode:
            operating_mode = mode
        else:
            operating_mode = ""
        
        # Determine mode family
        mode_family = "UNKNOWN"
        for family, modes in self.MODE_FAMILIES.items():
            if operating_mode in modes:
                mode_family = family
                break
        
        # Special handling for MFSK with submodes
        if mode == 'MFSK' and submode:
            operating_mode = submode
            if submode in ('FT4', 'FT8', 'MFSK8', 'MFSK16'):
                mode_family = 'DIGITAL'
        
        # USB/LSB are SSB
        if operating_mode in ('USB', 'LSB'):
            mode_family = 'SSB'
        
        return operating_mode, mode_family


def parse_adif_file(file_path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Parse an ADIF file and return records and errors."""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    parser = ADIFParser()
    return parser.parse(content)


def parse_adif_content(content: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Parse ADIF content string and return records and errors."""
    parser = ADIFParser()
    return parser.parse(content)
