"""ADIF Import Service - handles importing ADIF files into the database."""

import hashlib
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from ..db.database import SessionLocal
from ..models.models import (
    Source, Import, ImportFile, RawQSO, NormalizedQSO,
    CoverageType, AuditOperation
)
from ..adif.parser import ADIFParser, parse_adif_content
from ..schemas.schemas import ADIFImportRequest


class ADIFImportService:
    """Service for importing ADIF files."""
    
    def __init__(self, db: Session):
        self.db = db
        self.parser = ADIFParser()
    
    def import_adif(
        self,
        content: str,
        filename: str,
        source_name: str,
        source_type: str = "LOGBOOK",
        coverage_type: CoverageType = CoverageType.FULL_EXPORT,
        reliability_score: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Import ADIF content into the database.
        
        Returns dict with:
        - import_id
        - source_id
        - status
        - total_records
        - processed_records
        - already_imported_files
        - new_files
        - errors
        """
        errors = []
        
        try:
            # Get or create source
            source = self._get_or_create_source(
                source_name, source_type, reliability_score
            )
            
            # Create import record
            import_record = Import(
                source_id=source.id,
                coverage_type=coverage_type,
                status="processing",
                started_at=datetime.utcnow(),
            )
            self.db.add(import_record)
            self.db.flush()
            
            # Compute file hash
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            
            # Check if file already imported - use join instead of .has()
            existing_file = self.db.query(ImportFile).join(
                Import, ImportFile.import_id == Import.id
            ).filter(
                ImportFile.file_hash == file_hash,
                Import.source_id == source.id
            ).first()
            
            already_imported = existing_file is not None
            new_files = 0
            
            if already_imported:
                # File already imported - skip but record it
                import_record.status = "completed"
                import_record.completed_at = datetime.utcnow()
                import_record.error_message = "File already imported previously"
                
                # Create import file record marking as duplicate
                import_file = ImportFile(
                    import_id=import_record.id,
                    filename=filename,
                    file_hash=file_hash,
                    file_size=len(content),
                    already_imported=True,
                    imported_at=datetime.utcnow(),
                )
                self.db.add(import_file)
                already_imported_files = 1
                
            else:
                # Parse ADIF content
                records, parse_errors = self.parser.parse(content)
                errors.extend(parse_errors)
                
                # Create import file record
                import_file = ImportFile(
                    import_id=import_record.id,
                    filename=filename,
                    file_hash=file_hash,
                    file_size=len(content),
                    record_count=len(records),
                    already_imported=False,
                    imported_at=datetime.utcnow(),
                )
                self.db.add(import_file)
                self.db.flush()
                
                # Process records
                processed = self._process_records(
                    records, source, import_file
                )
                
                import_record.total_records = len(records)
                import_record.processed_records = processed
                import_record.status = "completed"
                import_record.completed_at = datetime.utcnow()
                
                new_files = 1
                already_imported_files = 0
            
            self.db.commit()
            
            # Log audit event
            self._log_audit(import_record, already_imported)
            
            return {
                "import_id": import_record.id,
                "source_id": source.id,
                "status": import_record.status,
                "total_records": import_record.total_records,
                "processed_records": import_record.processed_records,
                "already_imported_files": already_imported_files,
                "new_files": new_files,
                "errors": errors,
            }
            
        except Exception as e:
            self.db.rollback()
            errors.append(str(e))
            return {
                "import_id": None,
                "source_id": None,
                "status": "failed",
                "total_records": 0,
                "processed_records": 0,
                "already_imported_files": 0,
                "new_files": 0,
                "errors": errors,
            }
    
    def _get_or_create_source(
        self, name: str, type_: str, reliability: float
    ) -> Source:
        """Get existing source or create new one."""
        source = self.db.query(Source).filter(Source.name == name).first()
        
        if not source:
            source = Source(
                name=name,
                type=type_,
                reliability_score=reliability,
                is_active=True,
            )
            self.db.add(source)
            self.db.flush()
        
        return source
    
    def _process_records(
        self,
        records: List[Dict[str, Any]],
        source: Source,
        import_file: ImportFile,
    ) -> int:
        """Process parsed ADIF records and insert into database."""
        processed = 0
        
        for record in records:
            try:
                # Compute fingerprint for deduplication
                fingerprint = self.parser.compute_fingerprint(record)
                
                # Check for duplicate within this import
                existing = self.db.query(RawQSO).filter(
                    RawQSO.source_id == source.id,
                    RawQSO.record_fingerprint == fingerprint,
                ).first()
                
                if existing:
                    # Skip duplicate
                    continue
                
                # Create raw QSO
                raw_qso = RawQSO(
                    source_id=source.id,
                    import_file_id=import_file.id,
                    external_id=record.get('QSO_ID'),
                    raw_data=record,
                    record_fingerprint=fingerprint,
                )
                self.db.add(raw_qso)
                self.db.flush()
                
                # Create normalized QSO
                normalized = self._normalize_record(record, raw_qso.id, source.id)
                if normalized:
                    self.db.add(normalized)
                    processed += 1
                    
            except Exception as e:
                # Log error but continue processing
                pass
        
        return processed
    
    def _normalize_record(
        self, record: Dict[str, Any], raw_qso_id: int, source_id: int
    ) -> Optional[NormalizedQSO]:
        """Normalize an ADIF record into a NormalizedQSO."""
        callsign = record.get('CALL')
        qso_date = record.get('QSO_DATE')
        
        if not callsign or not qso_date:
            return None
        
        # Get mode classification
        mode = record.get('MODE', '')
        submode = record.get('SUBMODE', '')
        operating_mode, mode_family = self.parser.classify_mode(mode, submode)
        
        # Convert frequency from MHz (ADIF) to Hz for storage
        freq_mhz = record.get('FREQ')
        freq_hz = int(float(freq_mhz) * 1_000_000) if freq_mhz else None
        
        return NormalizedQSO(
            raw_qso_id=raw_qso_id,
            source_id=source_id,
            callsign=callsign.upper(),
            qso_date=qso_date,
            time_on=record.get('TIME_ON'),
            time_off=record.get('TIME_OFF'),
            band=record.get('BAND'),
            freq_hz=freq_hz,
            mode=mode.upper() if mode else None,
            submode=submode.upper() if submode else None,
            rst_sent=record.get('RST_SENT'),
            rst_rcvd=record.get('RST_RCVD'),
            grid=record.get('GRIDSQUARE') or record.get('GRID'),
            comment=record.get('COMMENT'),
            dxcc=record.get('DXCC'),
            country=record.get('COUNTRY'),
            state=record.get('STATE'),
            county=record.get('COUNTY'),
            cqz=record.get('CQZ'),
            ituz=record.get('ITUZ'),
            continent=record.get('CONT'),
            iota=record.get('IOTA'),
            qsl_sent=record.get('QSL_SENT'),
            qsl_rcvd=record.get('QSL_RCVD'),
            eqsl_sent=record.get('EQSL_SENT'),
            eqsl_rcvd=record.get('EQSL_RCVD'),
            lotw_sent=record.get('LOTW_SENT'),
            lotw_rcvd=record.get('LOTW_RCVD'),
            raw_mode=mode,
            raw_submode=submode,
            operating_mode=operating_mode,
            mode_family=mode_family,
            source_record_id=record.get('QSO_ID'),
        )
    
    def _log_audit(self, import_record: Import, already_imported: bool):
        """Log audit event for import operation."""
        from ..models.models import AuditEvent
        
        audit = AuditEvent(
            operation=AuditOperation.IMPORT,
            entity_type="import",
            entity_id=import_record.id,
            source="system",
            after={
                "import_id": import_record.id,
                "source_id": import_record.source_id,
                "status": import_record.status,
                "total_records": import_record.total_records,
                "already_imported": already_imported,
            },
            result="success" if not already_imported else "skipped",
            reason="ADIF file import" if not already_imported else "File already imported",
        )
        self.db.add(audit)
