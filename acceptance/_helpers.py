from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


def tag(name: str, value) -> str:
    if value is None:
        return ""
    text = str(value)
    return f"<{name}:{len(text)}>{text}"


def adif_record(
    *,
    call: str = "K1ABC",
    qso_date: str = "20260904",
    time_on: Optional[str] = "120000",
    band: str = "20M",
    freq_mhz: Optional[str] = "14.076000",
    mode: str = "FT8",
    submode: Optional[str] = None,
    grid: Optional[str] = None,
    county: Optional[str] = None,
    comment: Optional[str] = None,
    extras: Optional[dict] = None,
) -> str:
    fields = [
        tag("CALL", call),
        tag("QSO_DATE", qso_date),
        tag("TIME_ON", time_on),
        tag("BAND", band),
        tag("FREQ", freq_mhz),
        tag("MODE", mode),
        tag("SUBMODE", submode),
        tag("GRIDSQUARE", grid),
        tag("COUNTY", county),
        tag("COMMENT", comment),
    ]
    for key, value in (extras or {}).items():
        fields.append(tag(key, value))
    return "".join(fields) + "<EOR>"


def adif_file(records: Iterable[str]) -> str:
    return "<ADIF_VER:5>3.1.7<EOH>" + "".join(records)


def import_records(
    db,
    source_name: str,
    records: Iterable[str],
    *,
    filename: Optional[str] = None,
    coverage_type=None,
):
    from app.models.models import CoverageType
    from app.services.import_service import ADIFImportService

    kwargs = {}
    if coverage_type is not None:
        kwargs["coverage_type"] = coverage_type
    result = ADIFImportService(db).import_adif(
        content=adif_file(records),
        filename=filename or f"{source_name.lower()}-acceptance.adi",
        source_name=source_name,
        source_type="LOGBOOK",
        **kwargs,
    )
    assert result["status"] == "completed", result
    return result


def reconcile(db):
    from app.services.reconciliation_service import ReconciliationService

    result = ReconciliationService(db).run_reconciliation()
    assert result["status"] == "completed", result
    db.expire_all()
    return result


def logical_source_names(logical_qso):
    return {
        link.normalized_qso.source.name
        for link in logical_qso.source_links
        if link.normalized_qso is not None and link.normalized_qso.source is not None
    }


def enum_value(value):
    return getattr(value, "value", value)
