"""Models module for database entities.

Coverage window fields are attached here for backward-compatible schema evolution.
The package initializer runs before ``app.models.models`` is returned to callers,
so Base.metadata sees these columns without forcing a destructive model rewrite.
"""

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.sqlite import JSON

from .models import (
    Source,
    Import,
    ImportFile,
    RawQSO,
    NormalizedQSO,
    QSOIdentity,
    LogicalQSO,
    QSOSourceLink,
    ReconciliationRun,
    ReconciliationMatch,
    Divergence,
    DuplicateGroup,
    SyncJob,
    SyncAttempt,
    Backup,
    AuditEvent,
    Settings,
    LogicalQSOFieldOverride,
    DivergenceResolution,
    CoverageType,
    MatchLevel,
    MatchStatus,
    DuplicateType,
    QueueStatus,
    AuditOperation,
)

# Additive compatibility columns.  Existing SQLite databases can be migrated by
# the application migration/bootstrap path; fresh databases receive them directly
# from Base.metadata.create_all().
if "coverage_start" not in Import.__table__.c:
    Import.coverage_start = Column(DateTime)
if "coverage_end" not in Import.__table__.c:
    Import.coverage_end = Column(DateTime)
if "coverage_metadata" not in Import.__table__.c:
    Import.coverage_metadata = Column(JSON)

__all__ = [
    "Source", "Import", "ImportFile", "RawQSO", "NormalizedQSO",
    "QSOIdentity", "LogicalQSO", "QSOSourceLink", "ReconciliationRun",
    "ReconciliationMatch", "Divergence", "DuplicateGroup", "SyncJob",
    "SyncAttempt", "Backup", "AuditEvent", "Settings",
    "LogicalQSOFieldOverride", "DivergenceResolution", "CoverageType",
    "MatchLevel", "MatchStatus", "DuplicateType", "QueueStatus",
    "AuditOperation",
]
