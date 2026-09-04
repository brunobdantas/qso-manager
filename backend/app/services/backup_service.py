"""Backup Service - creates and manages database backups."""

import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from ..models.models import (
    Backup, LogicalQSO, NormalizedQSO, Source, AuditEvent, AuditOperation
)
from ..core.config import settings


class BackupService:
    """Service for creating and managing backups."""
    
    BACKUP_DIR = "backups"
    
    def __init__(self, db: Session):
        self.db = db
        self._ensure_backup_dir()
    
    def _ensure_backup_dir(self):
        """Ensure backup directory exists."""
        os.makedirs(self.BACKUP_DIR, exist_ok=True)
    
    def create_backup(
        self, 
        backup_type: str = "full",
        description: Optional[str] = None,
        include_raw: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a backup of QSO data.
        
        Args:
            backup_type: 'full', 'adif', or 'json'
            description: Optional description for the backup
            include_raw: Include raw QSO data (larger file)
        
        Returns:
            Dict with backup info including file_path
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        if backup_type == "adif":
            return self._create_adif_backup(timestamp, description)
        else:
            return self._create_json_backup(timestamp, description, include_raw)
    
    def _create_json_backup(
        self, timestamp: str, description: Optional[str], include_raw: bool
    ) -> Dict[str, Any]:
        """Create JSON format backup."""
        filename = f"backup_{timestamp}.json"
        filepath = os.path.join(self.BACKUP_DIR, filename)
        
        # Load all logical QSOs
        logical_qsos = self.db.query(LogicalQSO).all()
        
        backup_data = {
            "backup_type": "full",
            "created_at": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "record_count": len(logical_qsos),
            "description": description,
            "logical_qsos": [],
        }
        
        for lq in logical_qsos:
            qso_data = {
                "uuid": lq.uuid,
                "callsign": lq.callsign,
                "qso_date": lq.qso_date,
                "time_on": lq.time_on,
                "time_off": lq.time_off,
                "band": lq.band,
                "freq": lq.freq,
                "mode": lq.mode,
                "submode": lq.submode,
                "operating_mode": lq.operating_mode,
                "mode_family": lq.mode_family,
                "rst_sent": lq.rst_sent,
                "rst_rcvd": lq.rst_rcvd,
                "grid": lq.grid,
                "dxcc": lq.dxcc,
                "country": lq.country,
                "state": lq.state,
                "county": lq.county,
                "cqz": lq.cqz,
                "ituz": lq.ituz,
                "continent": lq.continent,
                "iota": lq.iota,
                "comment": lq.comment,
                "confirmations": lq.confirmations,
                "field_provenance": lq.field_provenance,
                "status": lq.status,
            }
            backup_data["logical_qsos"].append(qso_data)
        
        # Write to file
        content = json.dumps(backup_data, indent=2)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Calculate checksum
        checksum = hashlib.sha256(content.encode()).hexdigest()
        file_size = len(content.encode())
        
        # Create backup record
        backup = Backup(
            backup_type="full",
            file_path=filepath,
            file_size=file_size,
            record_count=len(logical_qsos),
            checksum=checksum,
            description=description,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),  # Auto-expire after 30 days
        )
        self.db.add(backup)
        
        # Log audit
        self._log_audit(backup, "success")
        
        self.db.commit()
        
        return {
            "backup_id": backup.id,
            "backup_type": "full",
            "file_path": filepath,
            "file_size": file_size,
            "record_count": len(logical_qsos),
            "checksum": checksum,
            "created_at": backup.created_at.isoformat(),
        }
    
    def _create_adif_backup(
        self, timestamp: str, description: Optional[str]
    ) -> Dict[str, Any]:
        """Create ADIF format backup."""
        filename = f"backup_{timestamp}.adi"
        filepath = os.path.join(self.BACKUP_DIR, filename)
        
        # Load all logical QSOs
        logical_qsos = self.db.query(LogicalQSO).all()
        
        # Build ADIF content
        lines = [
            "<ADIF_VER:5>3.1.7",
            "<PROGRAMID:15>QSO Manager",
            "<EOH>",
        ]
        
        for lq in logical_qsos:
            record = self._qso_to_adif_record(lq)
            lines.append(record)
        
        content = "\r\n".join(lines)
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Calculate checksum
        checksum = hashlib.sha256(content.encode()).hexdigest()
        file_size = len(content.encode())
        
        # Create backup record
        backup = Backup(
            backup_type="adif",
            file_path=filepath,
            file_size=file_size,
            record_count=len(logical_qsos),
            checksum=checksum,
            description=description,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        self.db.add(backup)
        
        # Log audit
        self._log_audit(backup, "success")
        
        self.db.commit()
        
        return {
            "backup_id": backup.id,
            "backup_type": "adif",
            "file_path": filepath,
            "file_size": file_size,
            "record_count": len(logical_qsos),
            "checksum": checksum,
            "created_at": backup.created_at.isoformat(),
        }
    
    def _qso_to_adif_record(self, lq: LogicalQSO) -> str:
        """Convert a LogicalQSO to ADIF record format."""
        fields = []
        
        def add_field(name: str, value: Any):
            if value is not None and value != "":
                str_value = str(value)
                fields.append(f"<{name}:{len(str_value)}>{str_value}")
        
        add_field("CALL", lq.callsign)
        add_field("QSO_DATE", lq.qso_date.replace("-", ""))
        add_field("TIME_ON", lq.time_on.replace(":", "") if lq.time_on else None)
        add_field("TIME_OFF", lq.time_off.replace(":", "") if lq.time_off else None)
        add_field("BAND", lq.band)
        add_field("FREQ", lq.freq)
        add_field("MODE", lq.mode)
        add_field("SUBMODE", lq.submode)
        add_field("RST_SENT", lq.rst_sent)
        add_field("RST_RCVD", lq.rst_rcvd)
        add_field("GRIDSQUARE", lq.grid)
        add_field("DXCC", lq.dxcc)
        add_field("COUNTRY", lq.country)
        add_field("STATE", lq.state)
        add_field("COUNTY", lq.county)
        add_field("CQZ", lq.cqz)
        add_field("ITUZ", lq.ituz)
        add_field("CONT", lq.continent)
        add_field("IOTA", lq.iota)
        add_field("COMMENT", lq.comment)
        
        return "".join(fields) + "<EOR>"
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """List all backups."""
        backups = self.db.query(Backup).order_by(Backup.created_at.desc()).all()
        return [
            {
                "id": b.id,
                "backup_type": b.backup_type,
                "file_path": b.file_path,
                "file_size": b.file_size,
                "record_count": b.record_count,
                "checksum": b.checksum,
                "description": b.description,
                "created_at": b.created_at.isoformat(),
                "expires_at": b.expires_at.isoformat() if b.expires_at else None,
            }
            for b in backups
        ]
    
    def delete_backup(self, backup_id: int) -> bool:
        """Delete a backup file and record."""
        backup = self.db.query(Backup).filter(Backup.id == backup_id).first()
        if not backup:
            return False
        
        # Delete file if exists
        if os.path.exists(backup.file_path):
            os.remove(backup.file_path)
        
        # Delete record
        self.db.delete(backup)
        self.db.commit()
        
        return True
    
    def _log_audit(self, backup: Backup, result: str):
        """Log audit event for backup operation."""
        audit = AuditEvent(
            operation=AuditOperation.BACKUP,
            entity_type="backup",
            entity_id=backup.id,
            source="system",
            after={
                "backup_id": backup.id,
                "backup_type": backup.backup_type,
                "file_path": backup.file_path,
                "record_count": backup.record_count,
            },
            result=result,
            reason="Backup creation",
        )
        self.db.add(audit)
