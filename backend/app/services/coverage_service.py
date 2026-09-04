"""Conservative source coverage assessment.

The service never infers historical absence from a partial, filtered, or
incremental import. Presence always wins: if the QSO is observed, it is PRESENT
regardless of coverage metadata.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from ..models.models import CoverageType


class PresenceStatus(str, Enum):
    PRESENT = "PRESENT"
    MISSING_HIGH_CONFIDENCE = "MISSING_HIGH_CONFIDENCE"
    POSSIBLY_MISSING = "POSSIBLY_MISSING"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    OUT_OF_COVERAGE = "OUT_OF_COVERAGE"


class CoverageService:
    """Assess whether absence from a source is meaningful."""

    @staticmethod
    def _inside_window(
        qso_datetime: Optional[datetime],
        coverage_start: Optional[datetime],
        coverage_end: Optional[datetime],
    ) -> Optional[bool]:
        if qso_datetime is None:
            return None
        if coverage_start and qso_datetime < coverage_start:
            return False
        if coverage_end and qso_datetime > coverage_end:
            return False
        if coverage_start is not None or coverage_end is not None:
            return True
        return None

    def assess(
        self,
        *,
        is_present: bool,
        coverage_type: CoverageType,
        qso_datetime: Optional[datetime],
        coverage_start: Optional[datetime] = None,
        coverage_end: Optional[datetime] = None,
        coverage_metadata: Optional[dict[str, Any]] = None,
    ) -> PresenceStatus:
        if is_present:
            return PresenceStatus.PRESENT

        if not isinstance(coverage_type, CoverageType):
            coverage_type = CoverageType(coverage_type)

        inside = self._inside_window(qso_datetime, coverage_start, coverage_end)

        if coverage_type == CoverageType.DATE_RANGE:
            if coverage_start is None or coverage_end is None or qso_datetime is None:
                return PresenceStatus.INSUFFICIENT_COVERAGE
            if inside is False:
                return PresenceStatus.OUT_OF_COVERAGE
            return PresenceStatus.MISSING_HIGH_CONFIDENCE

        if coverage_type in (CoverageType.FULL_EXPORT, CoverageType.API_FULL_SYNC):
            # Explicit windows constrain a full export/sync. If no window is
            # supplied, the declaration itself is treated as complete coverage.
            if inside is False:
                return PresenceStatus.OUT_OF_COVERAGE
            return PresenceStatus.MISSING_HIGH_CONFIDENCE

        if coverage_type == CoverageType.FILTERED_EXPORT:
            # Filter metadata can describe scope, but absence outside a verified
            # filter cannot safely be promoted to a definite missing QSO.
            return PresenceStatus.INSUFFICIENT_COVERAGE

        if coverage_type in (CoverageType.PARTIAL_EXPORT, CoverageType.API_INCREMENTAL):
            return PresenceStatus.INSUFFICIENT_COVERAGE

        return PresenceStatus.INSUFFICIENT_COVERAGE
