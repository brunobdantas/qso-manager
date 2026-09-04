"""QRZ integration primitives.

Release 3 deliberately separates *planning* from *transport*.  Planning is fully
functional and deterministic.  Live QRZ mutation remains fail-closed until a
real transport is explicitly implemented and separately validated with user
credentials; no test or UI action can silently write to QRZ.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


class QRZSafetyError(RuntimeError):
    """Raised when a QRZ operation cannot be proven safe."""


@dataclass(frozen=True)
class QRZPlan:
    operation: str
    dry_run: bool
    locator: Dict[str, str]
    adif_record: str
    fields: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "destination": "QRZ",
            "operation": self.operation,
            "dry_run": self.dry_run,
            "locator": self.locator,
            "adif_record": self.adif_record,
            "fields": self.fields,
        }


class QRZAdapter:
    """Build safe QRZ operation plans without performing network I/O."""

    @staticmethod
    def _adif_value(name: str, value: Any) -> str:
        if value is None or value == "":
            return ""
        text = str(value)
        return f"<{name}:{len(text)}>{text}"

    @staticmethod
    def _date(value: str | None) -> str | None:
        return value.replace("-", "") if value else None

    @staticmethod
    def _time(value: str | None) -> str | None:
        return value.replace(":", "") if value else None

    def fields_from_qso(self, qso) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "CALL": qso.callsign,
            "QSO_DATE": self._date(qso.qso_date),
            "TIME_ON": self._time(qso.time_on),
            "TIME_OFF": self._time(qso.time_off),
            "BAND": qso.band,
            "FREQ": f"{qso.freq_hz / 1_000_000:.6f}" if qso.freq_hz else None,
            "MODE": qso.mode,
            "SUBMODE": qso.submode,
            "RST_SENT": qso.rst_sent,
            "RST_RCVD": qso.rst_rcvd,
            "GRIDSQUARE": qso.grid,
            "DXCC": qso.dxcc,
            "COUNTRY": qso.country,
            "STATE": qso.state,
            "COUNTY": qso.county,
            "CQZ": qso.cqz,
            "ITUZ": qso.ituz,
            "CONT": qso.continent,
            "IOTA": qso.iota,
            "COMMENT": qso.comment,
        }
        return {k: v for k, v in fields.items() if v is not None and v != ""}

    def build_adif(self, qso) -> str:
        fields = self.fields_from_qso(qso)
        order = (
            "CALL", "QSO_DATE", "TIME_ON", "TIME_OFF", "BAND", "FREQ",
            "MODE", "SUBMODE", "RST_SENT", "RST_RCVD", "GRIDSQUARE",
            "DXCC", "COUNTRY", "STATE", "COUNTY", "CQZ", "ITUZ",
            "CONT", "IOTA", "COMMENT",
        )
        return "".join(self._adif_value(name, fields.get(name)) for name in order) + "<EOR>"

    def plan(self, qso, operation: str = "replace") -> QRZPlan:
        operation = operation.lower().strip()
        if operation not in {"insert", "replace"}:
            raise QRZSafetyError("Release 3 QRZ planner supports only insert/replace; delete is intentionally blocked")
        if not qso.callsign or not qso.qso_date or not qso.time_on:
            raise QRZSafetyError("QRZ exact targeting requires CALL, QSO_DATE and TIME_ON")

        locator = {
            "CALL": str(qso.callsign).upper(),
            "QSO_DATE": self._date(qso.qso_date),
            "TIME_ON": self._time(qso.time_on),
        }
        fields = self.fields_from_qso(qso)
        return QRZPlan(
            operation=operation,
            dry_run=True,
            locator=locator,
            adif_record=self.build_adif(qso),
            fields=fields,
        )

    def execute_live(self, plan: QRZPlan) -> None:
        """Fail closed: live transport is not silently available in Release 3."""
        raise QRZSafetyError(
            "Live QRZ mutation is locked. Use dry-run preview; a separately validated QRZ transport is required before real writes."
        )
