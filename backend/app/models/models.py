"""SQLAlchemy models for QSO Manager database."""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, Text, 
    ForeignKey, Enum, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.sqlite import JSON
import enum

from ..db.database import Base


class CoverageType(str, enum.Enum):
    """Type of coverage for an import/sync."""
    FULL_EXPORT = "FULL_EXPORT"
    PARTIAL_EXPORT = "PARTIAL_EXPORT"
    FILTERED_EXPORT = "FILTERED_EXPORT"
    DATE_RANGE = "DATE_RANGE"
    API_FULL_SYNC = "API_FULL_SYNC"
    API_INCREMENTAL = "API_INCREMENTAL"


class MatchLevel(str, enum.Enum):
    """Confidence level for reconciliation matches."""
    A = "A"  # Excellent match - auto-merge
    B = "B"  # Good match - auto-merge
    C = "C"  # Fair match - review suggested
    D = "D"  # Poor match - manual review required
    E = "E"  # Candidate only - never auto-merge


class MatchStatus(str, enum.Enum):
    """Status of a reconciliation match."""
    AUTO_MATCHED = "AUTO_MATCHED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    REVISAO_MANUAL = "REVISAO_MANUAL"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class DuplicateType(str, enum.Enum):
    """Type of duplicate detection."""
    REAL_DUPLICATE = "REAL_DUPLICATE"  # Actual duplicate in source
    REIMPORT = "REIMPORT"  # Same file imported again


class QueueStatus(str, enum.Enum):
    """Status for sync job queue items."""
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AuditOperation(str, enum.Enum):
    """Types of audit operations."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    IMPORT = "IMPORT"
    EXPORT = "EXPORT"
    RECONCILIATION = "RECONCILIATION"
    SYNC = "SYNC"
    BACKUP = "BACKUP"
    QRZ_INSERT = "QRZ_INSERT"
    QRZ_REPLACE = "QRZ_REPLACE"
    QRZ_DELETE = "QRZ_DELETE"


# ============================================================================
# SOURCE MODELS
# ============================================================================

class Source(Base):
    """Represents a QSO source (e.g., QRZ, WRL, MSHV, HRD)."""
    __tablename__ = "sources"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    type = Column(String(50), nullable=False)  # LOGBOOK, SOFTWARE, etc.
    is_active = Column(Boolean, default=True)
    reliability_score = Column(Float, default=0.5)  # 0.0 to 1.0
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    imports = relationship("Import", back_populates="source")
    raw_qsos = relationship("RawQSO", back_populates="source")
    normalized_qsos = relationship("NormalizedQSO", back_populates="source")


# ============================================================================
# IMPORT MODELS
# ============================================================================

class Import(Base):
    """Represents an import operation from a source."""
    __tablename__ = "imports"
    
    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    coverage_type = Column(Enum(CoverageType), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    error_message = Column(Text)
    
    # Relationships
    source = relationship("Source", back_populates="imports")
    files = relationship("ImportFile", back_populates="import_op")


class ImportFile(Base):
    """Represents a file associated with an import operation."""
    __tablename__ = "import_files"
    
    id = Column(Integer, primary_key=True, index=True)
    import_id = Column(Integer, ForeignKey("imports.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500))
    file_hash = Column(String(64), index=True)  # SHA-256 hash
    file_size = Column(Integer)
    record_count = Column(Integer, default=0)
    already_imported = Column(Boolean, default=False)
    imported_at = Column(DateTime)
    
    # Relationships
    import_op = relationship("Import", back_populates="files")
    raw_qsos = relationship("RawQSO", back_populates="import_file")


# ============================================================================
# QSO MODELS
# ============================================================================

class RawQSO(Base):
    """Raw QSO record as imported from source, preserving original data."""
    __tablename__ = "raw_qsos"
    
    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    import_file_id = Column(Integer, ForeignKey("import_files.id"))
    external_id = Column(String(255), index=True)  # Original ID from source
    raw_data = Column(JSON, nullable=False)  # Complete original record
    record_fingerprint = Column(String(64), index=True)  # Hash for deduplication
    
    # Timestamps
    imported_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    source = relationship("Source", back_populates="raw_qsos")
    import_file = relationship("ImportFile", back_populates="raw_qsos")
    normalized_qsos = relationship("NormalizedQSO", back_populates="raw_qso")
    
    __table_args__ = (
        UniqueConstraint('source_id', 'external_id', name='uq_source_external_id'),
        Index('idx_raw_fingerprint', 'record_fingerprint'),
    )


class NormalizedQSO(Base):
    """Normalized QSO record with standardized fields."""
    __tablename__ = "normalized_qsos"
    
    id = Column(Integer, primary_key=True, index=True)
    raw_qso_id = Column(Integer, ForeignKey("raw_qsos.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    
    # Core fields
    callsign = Column(String(20), nullable=False, index=True)
    qso_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    time_on = Column(String(8))  # HH:MM:SS
    time_off = Column(String(8))
    band = Column(String(10), index=True)
    freq = Column(Float)
    mode = Column(String(20))
    submode = Column(String(20))
    rst_sent = Column(String(5))
    rst_rcvd = Column(String(5))
    grid = Column(String(6))
    comment = Column(Text)
    
    # Additional ADIF fields
    qsl_sent = Column(String(1))
    qsl_rcvd = Column(String(1))
    eqsl_sent = Column(String(1))
    eqsl_rcvd = Column(String(1))
    lotw_sent = Column(String(1))
    lotw_rcvd = Column(String(1))
    dxcc = Column(Integer)
    country = Column(String(50))
    state = Column(String(50))
    county = Column(String(50))
    cqz = Column(Integer)
    ituz = Column(Integer)
    continent = Column(String(2))
    iota = Column(String(10))
    
    # Operating mode classification
    raw_mode = Column(String(20))
    raw_submode = Column(String(20))
    operating_mode = Column(String(20))  # e.g., FT4, SSB, CW
    mode_family = Column(String(20))  # e.g., DIGITAL, PHONE, CW
    
    # Metadata
    source_record_id = Column(String(255))  # Original record identifier
    confidence = Column(Float, default=1.0)
    
    # Timestamps
    normalized_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    raw_qso = relationship("RawQSO", back_populates="normalized_qsos")
    source = relationship("Source", back_populates="normalized_qsos")
    logical_qso_links = relationship("QSOSourceLink", back_populates="normalized_qso")
    
    __table_args__ = (
        Index('idx_normalized_callsign_date', 'callsign', 'qso_date'),
        Index('idx_normalized_time', 'time_on'),
    )


class LogicalQSO(Base):
    """Canonical QSO constructed from reconciled sources."""
    __tablename__ = "logical_qsos"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Canonical values (field-by-field reconciliation)
    callsign = Column(String(20), nullable=False, index=True)
    qso_date = Column(String(10), nullable=False, index=True)
    time_on = Column(String(8))
    time_off = Column(String(8))
    band = Column(String(10))
    freq = Column(Float)
    mode = Column(String(20))
    submode = Column(String(20))
    operating_mode = Column(String(20))
    mode_family = Column(String(20))
    rst_sent = Column(String(5))
    rst_rcvd = Column(String(5))
    grid = Column(String(6))
    dxcc = Column(Integer)
    country = Column(String(50))
    state = Column(String(50))
    county = Column(String(50))
    cqz = Column(Integer)
    ituz = Column(Integer)
    continent = Column(String(2))
    iota = Column(String(10))
    comment = Column(Text)
    
    # Confirmations (union from all sources)
    confirmations = Column(JSON)  # {"qrz": "Y", "lotw": "Q", ...}
    
    # Provenance tracking (which source provided each field)
    field_provenance = Column(JSON)  # {"callsign": {"source": "qrz", "confidence": 0.9}, ...}
    
    # Status
    status = Column(String(20), default="reconciled")  # reconciled, needs_review, confirmed
    divergence_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    source_links = relationship("QSOSourceLink", back_populates="logical_qso")
    divergences = relationship("Divergence", back_populates="logical_qso")


class QSOSourceLink(Base):
    """Links a NormalizedQSO to a LogicalQSO."""
    __tablename__ = "qso_source_links"
    
    id = Column(Integer, primary_key=True, index=True)
    logical_qso_id = Column(Integer, ForeignKey("logical_qsos.id"), nullable=False)
    normalized_qso_id = Column(Integer, ForeignKey("normalized_qsos.id"), nullable=False)
    match_level = Column(Enum(MatchLevel), nullable=False)
    match_status = Column(Enum(MatchStatus), nullable=False)
    match_score = Column(Float)
    matched_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    logical_qso = relationship("LogicalQSO", back_populates="source_links")
    normalized_qso = relationship("NormalizedQSO", back_populates="logical_qso_links")
    
    __table_args__ = (
        UniqueConstraint('logical_qso_id', 'normalized_qso_id', name='uq_logical_normalized'),
    )


# ============================================================================
# RECONCILIATION MODELS
# ============================================================================

class ReconciliationRun(Base):
    """Represents a reconciliation execution."""
    __tablename__ = "reconciliation_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    status = Column(String(20), default="running")
    total_logical_qsos = Column(Integer, default=0)
    total_matches = Column(Integer, default=0)
    total_divergences = Column(Integer, default=0)
    total_duplicates = Column(Integer, default=0)
    parameters = Column(JSON)
    
    # Relationships
    matches = relationship("ReconciliationMatch", back_populates="run")


class ReconciliationMatch(Base):
    """Represents a match found during reconciliation."""
    __tablename__ = "reconciliation_matches"
    
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("reconciliation_runs.id"), nullable=False)
    normalized_qso_id_1 = Column(Integer, ForeignKey("normalized_qsos.id"), nullable=False)
    normalized_qso_id_2 = Column(Integer, ForeignKey("normalized_qsos.id"), nullable=False)
    match_level = Column(Enum(MatchLevel), nullable=False)
    match_status = Column(Enum(MatchStatus), nullable=False)
    match_score = Column(Float, nullable=False)
    time_difference_seconds = Column(Integer)
    frequency_difference = Column(Float)
    reasoning = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    run = relationship("ReconciliationRun", back_populates="matches")


class Divergence(Base):
    """Represents a field divergence between sources."""
    __tablename__ = "divergences"
    
    id = Column(Integer, primary_key=True, index=True)
    logical_qso_id = Column(Integer, ForeignKey("logical_qsos.id"), nullable=False)
    field_name = Column(String(50), nullable=False)
    source_1_value = Column(String(255))
    source_1_name = Column(String(100))
    source_2_value = Column(String(255))
    source_2_name = Column(String(100))
    resolution = Column(String(255))  # Resolved value
    resolution_reason = Column(Text)
    status = Column(String(20), default="unresolved")  # unresolved, resolved, ignored
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    logical_qso = relationship("LogicalQSO", back_populates="divergences")
    
    __table_args__ = (
        Index('idx_divergence_logical_field', 'logical_qso_id', 'field_name'),
    )


class DuplicateGroup(Base):
    """Represents a group of duplicate QSOs."""
    __tablename__ = "duplicate_groups"
    
    id = Column(Integer, primary_key=True, index=True)
    duplicate_type = Column(Enum(DuplicateType), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"))
    description = Column(Text)
    qso_ids = Column(JSON)  # List of NormalizedQSO IDs
    action_taken = Column(String(50))  # merged, ignored, flagged
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================================
# SYNC JOB MODELS
# ============================================================================

class SyncJob(Base):
    """Represents a synchronization job to external service."""
    __tablename__ = "sync_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    destination = Column(String(50), nullable=False)  # qrz, lotw, eqsl
    logical_qso_id = Column(Integer, ForeignKey("logical_qsos.id"))
    operation = Column(String(20), nullable=False)  # insert, replace, delete
    status = Column(Enum(QueueStatus), default=QueueStatus.PENDING)
    retry_count = Column(Integer, default=0)
    last_attempt_at = Column(DateTime)
    error_message = Column(Text)
    dry_run = Column(Boolean, default=True)
    result_data = Column(JSON)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncAttempt(Base):
    """Records individual sync attempts."""
    __tablename__ = "sync_attempts"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_job_id = Column(Integer, ForeignKey("sync_jobs.id"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    request_data = Column(JSON)
    response_data = Column(JSON)
    error_message = Column(Text)
    duration_ms = Column(Integer)
    
    # Timestamps
    attempted_at = Column(DateTime, default=datetime.utcnow)


# ============================================================================
# BACKUP MODELS
# ============================================================================

class Backup(Base):
    """Represents a backup file."""
    __tablename__ = "backups"
    
    id = Column(Integer, primary_key=True, index=True)
    backup_type = Column(String(20), nullable=False)  # full, incremental, adif, json
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    record_count = Column(Integer)
    checksum = Column(String(64))
    description = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


# ============================================================================
# AUDIT MODELS
# ============================================================================

class AuditEvent(Base):
    """Append-only audit log."""
    __tablename__ = "audit_events"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    operation = Column(Enum(AuditOperation), nullable=False)
    entity_type = Column(String(50), nullable=False)  # qso, import, source, etc.
    entity_id = Column(Integer)
    source = Column(String(100))  # user, system, api, etc.
    before = Column(JSON)  # Previous state
    after = Column(JSON)  # New state
    reason = Column(Text)
    result = Column(String(20))  # success, failure, partial
    error = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(String(255))
    
    __table_args__ = (
        Index('idx_audit_entity', 'entity_type', 'entity_id'),
        Index('idx_audit_operation', 'operation'),
    )


# ============================================================================
# SETTINGS MODEL
# ============================================================================

class Settings(Base):
    """Application settings stored in database."""
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text)
    value_type = Column(String(20), default="string")  # string, int, float, bool, json
    description = Column(Text)
    is_sensitive = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
