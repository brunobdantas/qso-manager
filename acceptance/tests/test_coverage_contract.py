import importlib
from datetime import datetime

import pytest

from acceptance._helpers import adif_record, import_records, enum_value


def test_manual_import_defaults_to_partial_export(db):
    from app.models.models import Import, CoverageType

    # Deliberately omit coverage_type: manual upload default must be conservative.
    import_records(db, "MANUAL", [adif_record(time_on="123900")])
    row = db.query(Import).one()
    assert enum_value(row.coverage_type) == CoverageType.PARTIAL_EXPORT.value


def test_import_model_supports_explicit_coverage_window():
    from app.models.models import Import

    columns = set(Import.__table__.columns.keys())
    assert "coverage_start" in columns
    assert "coverage_end" in columns
    assert "coverage_metadata" in columns, "Coverage filters/metadata need persistent representation"


def _coverage_api():
    try:
        module = importlib.import_module("app.services.coverage_service")
    except ModuleNotFoundError:
        pytest.fail("CoverageService must exist at app.services.coverage_service")
    cls = getattr(module, "CoverageService", None)
    status_enum = getattr(module, "PresenceStatus", None)
    assert cls is not None, "coverage_service must expose CoverageService"
    assert status_enum is not None, "coverage_service must expose PresenceStatus"
    return cls(), status_enum


def _status(value):
    return getattr(value, "value", value)


def test_coverage_semantics_are_conservative():
    from app.models.models import CoverageType

    service, PresenceStatus = _coverage_api()
    qso_dt = datetime(2026, 9, 4, 12, 39)
    start = datetime(2026, 9, 4, 0, 0)
    end = datetime(2026, 9, 4, 23, 59, 59)

    assert _status(service.assess(
        is_present=True,
        coverage_type=CoverageType.PARTIAL_EXPORT,
        qso_datetime=qso_dt,
        coverage_start=None,
        coverage_end=None,
        coverage_metadata=None,
    )) == "PRESENT"

    assert _status(service.assess(
        is_present=False,
        coverage_type=CoverageType.FULL_EXPORT,
        qso_datetime=qso_dt,
        coverage_start=start,
        coverage_end=end,
        coverage_metadata=None,
    )) == "MISSING_HIGH_CONFIDENCE"

    assert _status(service.assess(
        is_present=False,
        coverage_type=CoverageType.DATE_RANGE,
        qso_datetime=datetime(2026, 9, 5, 12, 0),
        coverage_start=start,
        coverage_end=end,
        coverage_metadata=None,
    )) == "OUT_OF_COVERAGE"

    for coverage_type in (
        CoverageType.PARTIAL_EXPORT,
        CoverageType.FILTERED_EXPORT,
        CoverageType.API_INCREMENTAL,
    ):
        status = _status(service.assess(
            is_present=False,
            coverage_type=coverage_type,
            qso_datetime=qso_dt,
            coverage_start=start,
            coverage_end=end,
            coverage_metadata=None,
        ))
        assert status in {"INSUFFICIENT_COVERAGE", "POSSIBLY_MISSING"}
        assert status != "MISSING_HIGH_CONFIDENCE"


def test_1239_present_can_never_be_classified_missing():
    from app.models.models import CoverageType

    service, _ = _coverage_api()
    for coverage_type in CoverageType:
        status = _status(service.assess(
            is_present=True,
            coverage_type=coverage_type,
            qso_datetime=datetime(2026, 9, 4, 12, 39),
            coverage_start=None,
            coverage_end=None,
            coverage_metadata=None,
        ))
        assert status == "PRESENT", f"Present QSO was classified {status} for {coverage_type}"
