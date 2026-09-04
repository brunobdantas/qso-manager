"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class CoverageType(str, Enum):
    FULL_EXPORT = "FULL_EXPORT"
    PARTIAL_EXPORT = "PARTIAL_EXPORT"
    FILTERED_EXPORT = "FILTERED_EXPORT"
    DATE_RANGE = "DATE_RANGE"
    API_FULL_SYNC = "API_FULL_SYNC"
    API_INCREMENTAL = "API_INCREMENTAL"


class MatchLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class MatchStatus(str, Enum):
    AUTO_MATCHED = "AUTO_MATCHED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    REVISAO_MANUAL = "REVISAO_MANUAL"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class DuplicateType(str, Enum):
    REAL_DUPLICATE = "REAL_DUPLICATE"
    REIMPORT = "REIMPORT"


class QueueStatus(str, Enum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AuditOperation(str, Enum):
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
# SOURCE SCHEMAS
# ============================================================================

class SourceBase(BaseModel):
    name: str
    type: str
    is_active: bool = True
    reliability_score: float = 0.5


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    is_active: Optional[bool] = None
    reliability_score: Optional[float] = None


class SourceResponse(SourceBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================================
# IMPORT SCHEMAS
# ============================================================================

class ImportFileBase(BaseModel):
    filename: str
    file_hash: Optional[str] = None
    record_count: int = 0
    already_imported: bool = False


class ImportFileResponse(ImportFileBase):
    id: int
    import_id: int
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    imported_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ImportBase(BaseModel):
    source_id: int
    coverage_type: CoverageType


class ImportCreate(ImportBase):
    pass


class ImportResponse(ImportBase):
    id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    total_records: int
    processed_records: int
    error_message: Optional[str] = None
    files: List[ImportFileResponse] = []
    
    class Config:
        from_attributes = True


# ============================================================================
# QSO SCHEMAS
# ============================================================================

class RawQSOResponse(BaseModel):
    id: int
    source_id: int
    import_file_id: Optional[int] = None
    external_id: Optional[str] = None
    raw_data: Dict[str, Any]
    record_fingerprint: Optional[str] = None
    imported_at: datetime
    
    class Config:
        from_attributes = True


class NormalizedQSOBase(BaseModel):
    callsign: str
    qso_date: str
    time_on: Optional[str] = None
    time_off: Optional[str] = None
    band: Optional[str] = None
    freq: Optional[float] = None
    mode: Optional[str] = None
    submode: Optional[str] = None
    rst_sent: Optional[str] = None
    rst_rcvd: Optional[str] = None
    grid: Optional[str] = None
    comment: Optional[str] = None
    dxcc: Optional[int] = None
    country: Optional[str] = None
    state: Optional[str] = None
    county: Optional[str] = None
    cqz: Optional[int] = None
    ituz: Optional[int] = None
    continent: Optional[str] = None
    iota: Optional[str] = None
    operating_mode: Optional[str] = None
    mode_family: Optional[str] = None


class NormalizedQSOCreated(NormalizedQSOBase):
    id: int
    source_id: int
    raw_qso_id: int
    confidence: float = 1.0
    normalized_at: datetime
    
    class Config:
        from_attributes = True


class NormalizedQSOFull(NormalizedQSOCreated):
    source: Optional[SourceResponse] = None
    raw_qso: Optional[RawQSOResponse] = None


class LogicalQSOBase(BaseModel):
    callsign: str
    qso_date: str
    time_on: Optional[str] = None
    time_off: Optional[str] = None
    band: Optional[str] = None
    freq: Optional[float] = None
    mode: Optional[str] = None
    submode: Optional[str] = None
    operating_mode: Optional[str] = None
    mode_family: Optional[str] = None
    rst_sent: Optional[str] = None
    rst_rcvd: Optional[str] = None
    grid: Optional[str] = None
    dxcc: Optional[int] = None
    country: Optional[str] = None
    state: Optional[str] = None
    county: Optional[str] = None
    cqz: Optional[int] = None
    ituz: Optional[int] = None
    continent: Optional[str] = None
    iota: Optional[str] = None
    comment: Optional[str] = None


class LogicalQSOResponse(LogicalQSOBase):
    id: int
    uuid: str
    confirmations: Optional[Dict[str, Any]] = None
    field_provenance: Optional[Dict[str, Any]] = None
    status: str
    divergence_count: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class QSOSourceLinkResponse(BaseModel):
    id: int
    logical_qso_id: int
    normalized_qso_id: int
    match_level: MatchLevel
    match_status: MatchStatus
    match_score: Optional[float] = None
    matched_at: datetime
    
    class Config:
        from_attributes = True


class LogicalQSODetail(LogicalQSOResponse):
    source_links: List[QSOSourceLinkResponse] = []
    divergences: List["DivergenceResponse"] = []


# ============================================================================
# RECONCILIATION SCHEMAS
# ============================================================================

class ReconciliationMatchResponse(BaseModel):
    id: int
    run_id: int
    normalized_qso_id_1: int
    normalized_qso_id_2: int
    match_level: MatchLevel
    match_status: MatchStatus
    match_score: float
    time_difference_seconds: Optional[int] = None
    frequency_difference: Optional[float] = None
    reasoning: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ReconciliationRunResponse(BaseModel):
    id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    total_logical_qsos: int
    total_matches: int
    total_divergences: int
    total_duplicates: int
    parameters: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True


class DivergenceResponse(BaseModel):
    id: int
    logical_qso_id: int
    field_name: str
    source_1_value: Optional[str] = None
    source_1_name: Optional[str] = None
    source_2_value: Optional[str] = None
    source_2_name: Optional[str] = None
    resolution: Optional[str] = None
    resolution_reason: Optional[str] = None
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class DuplicateGroupResponse(BaseModel):
    id: int
    duplicate_type: DuplicateType
    source_id: Optional[int] = None
    description: Optional[str] = None
    qso_ids: List[int]
    action_taken: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================================
# SYNC JOB SCHEMAS
# ============================================================================

class SyncJobResponse(BaseModel):
    id: int
    destination: str
    logical_qso_id: Optional[int] = None
    operation: str
    status: QueueStatus
    retry_count: int
    last_attempt_at: Optional[datetime] = None
    error_message: Optional[str] = None
    dry_run: bool
    result_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SyncAttemptResponse(BaseModel):
    id: int
    sync_job_id: int
    attempt_number: int
    status: str
    request_data: Optional[Dict[str, Any]] = None
    response_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    attempted_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================================
# BACKUP SCHEMAS
# ============================================================================

class BackupResponse(BaseModel):
    id: int
    backup_type: str
    file_path: str
    file_size: Optional[int] = None
    record_count: Optional[int] = None
    checksum: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ============================================================================
# AUDIT SCHEMAS
# ============================================================================

class AuditEventResponse(BaseModel):
    id: int
    timestamp: datetime
    operation: AuditOperation
    entity_type: str
    entity_id: Optional[int] = None
    source: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    result: str
    error: Optional[str] = None
    
    class Config:
        from_attributes = True


# ============================================================================
# SETTINGS SCHEMAS
# ============================================================================

class SettingsResponse(BaseModel):
    id: int
    key: str
    value: Optional[str] = None
    value_type: str
    description: Optional[str] = None
    is_sensitive: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SettingsCreate(BaseModel):
    key: str
    value: str
    value_type: str = "string"
    description: Optional[str] = None
    is_sensitive: bool = False


class SettingsUpdate(BaseModel):
    value: Optional[str] = None
    description: Optional[str] = None


# ============================================================================
# ADIF IMPORT SCHEMAS
# ============================================================================

class ADIFImportRequest(BaseModel):
    source_name: str
    source_type: str = "LOGBOOK"
    coverage_type: CoverageType = CoverageType.FULL_EXPORT
    reliability_score: float = 0.5


class ADIFImportResponse(BaseModel):
    import_id: int
    source_id: int
    status: str
    total_records: int
    processed_records: int
    already_imported_files: int
    new_files: int
    errors: List[str] = []


# ============================================================================
# QRZ SCHEMAS
# ============================================================================

class QRZTestRequest(BaseModel):
    api_key: str
    username: str


class QRZTestResponse(BaseModel):
    success: bool
    message: str
    callsign: Optional[str] = None


class QRZSyncRequest(BaseModel):
    dry_run: bool = True
    full_sync: bool = False


class QRZSyncResponse(BaseModel):
    success: bool
    message: str
    qsos_to_insert: int
    qsos_to_replace: int
    qsos_to_delete: int
    preview: List[Dict[str, Any]] = []


class QRZOperationRequest(BaseModel):
    logical_qso_id: int
    operation: str  # insert, replace, delete
    dry_run: bool = True


class QRZOperationResponse(BaseModel):
    success: bool
    message: str
    qrz_log_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


# ============================================================================
# HEALTH CHECK
# ============================================================================

class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    qrz_enabled: bool
    environment: str
