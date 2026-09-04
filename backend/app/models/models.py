"""SQLAlchemy database models."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.db.database import Base


class Source(Base):
    """Data source (QRZ, WRL, MSHV, etc.)."""
    __tablename__ = "sources"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    type = Column(String(50), nullable=False)  # LOGBOOK, SOFTWARE, EXPORT
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    imports = relationship("Import", back_populates="source")
    normalized_qsos = relationship("NormalizedQSO", back_populates="source")


class Import(Base):
    """Import job representing a single import operation."""
    __tablename__ = "imports"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    coverage_type = Column(String(50), default="PARTIAL_EXPORT")  # FULL_EXPORT, PARTIAL_EXPORT, DATE_RANGE, API_FULL_SYNC, API_INCREMENTAL, FILTERED_EXPORT
    coverage_start = Column(DateTime)
    coverage_end = Column(DateTime)
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    
    source = relationship("Source", back_populates="imports")
    files = relationship("ImportFile", back_populates="import_job")
    raw_qsos = relationship("RawQSO", back_populates="import_job")


class ImportFile(Base):
    """File associated with an import job."""
    __tablename__ = "import_files"
    
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey("imports.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), nullable=False)  # SHA256
    file_size = Column(Integer)
    imported_at = Column(DateTime, default=datetime.utcnow)
    
    import_job = relationship("Import", back_populates="files")


class RawQSO(Base):
    """Raw QSO record as imported from source."""
    __tablename__ = "raw_qsos"
    
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey("imports.id"), nullable=False)
    source_record_id = Column(String(255))  # External ID from source
    content = Column(Text, nullable=False)  # Original ADIF record
    fingerprint = Column(String(64))  # Hash for duplicate detection
    imported_at = Column(DateTime, default=datetime.utcnow)
    
    import_job = relationship("Import", back_populates="raw_qsos")
    
    __table_args__ = (
        UniqueConstraint('import_id', 'source_record_id', name='uq_import_source_record'),
    )


class NormalizedQSO(Base):
    """Normalized QSO data ready for reconciliation."""
    __tablename__ = "normalized_qsos"
    
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey("imports.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    
    # Core fields
    callsign = Column(String(20), nullable=False)
    qso_date = Column(String(10), nullable=False)  # YYYYMMDD
    time_on = Column(String(8))  # HHMMSS
    time_off = Column(String(8))
    band = Column(String(10))
    freq_hz = Column(Integer)  # Frequency in Hz
    mode = Column(String(20))
    submode = Column(String(20))
    rst_sent = Column(String(5))
    rst_rcvd = Column(String(5))
    grid = Column(String(6))
    comment = Column(Text)
    
    # Additional fields
    country = Column(String(50))
    dxcc = Column(Integer)
    state = Column(String(50))
    county = Column(String(50))
    cqz = Column(Integer)
    ituz = Column(Integer)
    
    # Metadata
    operating_mode = Column(String(20))  # Computed mode (e.g., FT4 from MFSK+FT4)
    mode_family = Column(String(20))  # e.g., SSB, DIGITAL
    level = Column(String(1), default="A")  # Confidence level A-E
    external_id = Column(String(255))  # Original source ID
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    source = relationship("Source", back_populates="normalized_qsos")
    logical_qso_links = relationship("QSOSourceLink", back_populates="normalized_qso")


class LogicalQSO(Base):
    """Reconciled logical QSO combining multiple sources."""
    __tablename__ = "logical_qsos"
    
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, nullable=False, index=True)
    cluster_fingerprint = Column(String(64), unique=True, index=True)  # Deterministic cluster ID
    
    # Canonical values (field-by-field reconciliation)
    callsign = Column(String(20))
    qso_date = Column(String(10))
    time_on = Column(String(8))
    time_off = Column(String(8))
    band = Column(String(10))
    freq_hz = Column(Integer)
    mode = Column(String(20))
    submode = Column(String(20))
    rst_sent = Column(String(5))
    rst_rcvd = Column(String(5))
    grid = Column(String(6))
    comment = Column(Text)
    country = Column(String(50))
    dxcc = Column(Integer)
    state = Column(String(50))
    county = Column(String(50))
    cqz = Column(Integer)
    ituz = Column(Integer)
    
    # Status
    status = Column(String(50), default="reconciled")  # reconciled, needs_review
    confidence = Column(String(20), default="high")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    source_links = relationship("QSOSourceLink", back_populates="logical_qso", cascade="all, delete-orphan")
    divergences = relationship("Divergence", back_populates="logical_qso", cascade="all, delete-orphan")


class QSOSourceLink(Base):
    """Links a NormalizedQSO to a LogicalQSO."""
    __tablename__ = "qso_source_links"
    
    id = Column(Integer, primary_key=True)
    logical_qso_id = Column(Integer, ForeignKey("logical_qsos.id"), nullable=False)
    normalized_qso_id = Column(Integer, ForeignKey("normalized_qsos.id"), nullable=False)
    match_type = Column(String(50))  # AUTO_MATCHED, REVISAO_MANUAL, POSSIBLE_MATCH
    score = Column(Float)
    
    logical_qso = relationship("LogicalQSO", back_populates="source_links")
    normalized_qso = relationship("NormalizedQSO", back_populates="logical_qso_links")
    
    __table_args__ = (
        UniqueConstraint('logical_qso_id', 'normalized_qso_id', name='uq_logical_normalized'),
    )


class Divergence(Base):
    """Field-level divergence between sources in a LogicalQSO."""
    __tablename__ = "divergences"
    
    id = Column(Integer, primary_key=True)
    logical_qso_id = Column(Integer, ForeignKey("logical_qsos.id"), nullable=False)
    field_name = Column(String(50), nullable=False)
    values = Column(Text, nullable=False)  # JSON of {source_id: value}
    resolution = Column(String(255))
    resolved = Column(Boolean, default=False)
    
    logical_qso = relationship("LogicalQSO", back_populates="divergences")


class ReconciliationRun(Base):
    """Record of a reconciliation execution."""
    __tablename__ = "reconciliation_runs"
    
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    status = Column(String(50), default="running")  # running, completed, failed
    total_normalized = Column(Integer)
    total_logical_created = Column(Integer)
    total_divergences = Column(Integer)
    
    matches = relationship("ReconciliationMatch", back_populates="run")


class ReconciliationMatch(Base):
    """Historical record of matches made during reconciliation."""
    __tablename__ = "reconciliation_matches"
    
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("reconciliation_runs.id"), nullable=False)
    normalized_qso_id_1 = Column(Integer, nullable=False)
    normalized_qso_id_2 = Column(Integer, nullable=False)
    match_type = Column(String(50))
    score = Column(Float)
    
    run = relationship("ReconciliationRun", back_populates="matches")


class DuplicateGroup(Base):
    """Group of duplicate QSOs within the same source."""
    __tablename__ = "duplicate_groups"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    duplicate_type = Column(String(50))  # REAL_DUPLICATE, REIMPORTACAO
    created_at = Column(DateTime, default=datetime.utcnow)
    
    members = relationship("NormalizedQSO", backref="duplicate_group")


class Backup(Base):
    """Backup record."""
    __tablename__ = "backups"
    
    id = Column(Integer, primary_key=True)
    backup_type = Column(String(50), nullable=False)  # ADI, JSON, FULL
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    checksum = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)
    description = Column(Text)


class AuditEvent(Base):
    """Append-only audit log."""
    __tablename__ = "audit_events"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    operation = Column(String(50), nullable=False)  # CREATE, UPDATE, DELETE, IMPORT, RECONCILE, BACKUP
    entity_type = Column(String(50), nullable=False)  # QSO, SOURCE, IMPORT, etc.
    entity_id = Column(String(100))
    source = Column(String(100))  # User, system, API
    before_value = Column(Text)  # JSON
    after_value = Column(Text)  # JSON
    reason = Column(Text)
    result = Column(String(50))  # SUCCESS, FAILURE
    error_message = Column(Text)


class Settings(Base):
    """Application settings stored in database."""
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncJob(Base):
    """External sync job (QRZ, LoTW, etc.)."""
    __tablename__ = "sync_jobs"
    
    id = Column(Integer, primary_key=True)
    service = Column(String(50), nullable=False)  # QRZ, LOTW, EQSL, CLUBLOG
    job_type = Column(String(50), nullable=False)  # FETCH, INSERT, REPLACE, DELETE
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    dry_run = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    result = Column(Text)  # JSON


class SyncAttempt(Base):
    """Individual sync attempt record."""
    __tablename__ = "sync_attempts"
    
    id = Column(Integer, primary_key=True)
    sync_job_id = Column(Integer, ForeignKey("sync_jobs.id"), nullable=False)
    status = Column(String(50), default="PENDING")  # PENDING, SENDING, SENT, CONFIRMED, FAILED, RETRY_REQUIRED, MANUAL_REVIEW
    attempt_number = Column(Integer, default=1)
    error_message = Column(Text)
    external_id = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    job = relationship("SyncJob", backref="attempts")
