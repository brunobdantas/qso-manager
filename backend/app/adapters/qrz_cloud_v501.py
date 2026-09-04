"""QRZ cloud adapter with production validation and resilient FETCH paging.

Release 5.0.2 keeps the Release 5 safety model intact.  The QRZ API checker can
validate a Logbook API key even when a synthetic FETCH/MAX:0 probe returns a
bare RESULT=FAIL, so connection validation uses STATUS and real synchronization
uses the paging pattern recommended by QRZ: MAX:250,AFTERLOGID:n.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .cloud_logs import ADIFParser, CloudProviderError, QRZCloudAdapter


class QRZCloudAdapterV501(QRZCloudAdapter):
    """Production QRZ adapter with STATUS validation and resilient full sync."""

    @staticmethod
    def _access_help(action: str, original: str) -> str:
        action = action.upper()
        return (
            f"QRZ recusou a operação {action}. "
            "A chave pode ser válida, mas o QRZ não aceitou esta operação. "
            "Confirme a Logbook API Access Key do logbook e tente novamente. "
            f"Resposta do QRZ: {original}."
        )

    def _post(self, action: str, **fields: Any) -> Dict[str, str]:
        raw_key = str(self.credentials.get("api_key") or "")
        cleaned_key = "".join(raw_key.split())
        if cleaned_key != raw_key:
            self.credentials = {**self.credentials, "api_key": cleaned_key}
        try:
            return super()._post(action, **fields)
        except CloudProviderError as exc:
            message = str(exc).strip()
            if message in {"QRZ returned FAIL", "QRZ returned AUTH"}:
                raise CloudProviderError(self._access_help(action, message)) from exc
            lowered = message.lower()
            if any(token in lowered for token in ("invalid key", "access key", "unauthorized", "subscription", "privilege")):
                raise CloudProviderError(self._access_help(action, message)) from exc
            raise

    @staticmethod
    def _status_count(data: Dict[str, str]) -> int:
        candidates = [data.get("COUNT", ""), data.get("DATA", "")]
        for text in candidates:
            match = re.search(r"(?:TOTAL(?:_QSO)?S?|QSOS?|COUNT)\s*[=:]\s*(\d+)", str(text), flags=re.I)
            if match:
                return int(match.group(1))
            if str(text).strip().isdigit():
                return int(str(text).strip())
        return 0

    def test_connection(self) -> Dict[str, Any]:
        # STATUS is the canonical key/logbook validation operation and mirrors
        # what the QRZ API checker proves: the key maps to a live logbook.
        data = self._post("STATUS")
        return {
            "ok": data.get("RESULT", "").upper() == "OK",
            "records": self._status_count(data),
            "status": "Chave e acesso ao logbook QRZ validados.",
        }

    def _parse_page(self, data: Dict[str, str]):
        page, errors = ADIFParser().parse(data.get("ADIF", ""))
        if errors and not page:
            raise CloudProviderError("QRZ returned invalid ADIF: " + "; ".join(errors[:3]))
        return page

    def _single_full_fetch(self) -> Dict[str, Any]:
        data = self._post("FETCH", OPTION="ALL,TYPE:ADIF,STATUS:ALL")
        records = self._parse_page(data)
        return {
            "records": records,
            "metadata": {"pages": 1, "coverage": "API_FULL_SYNC", "strategy": "ALL_FALLBACK"},
        }

    def fetch_all(self) -> Dict[str, Any]:
        # Validate the key independently of FETCH. This lets us distinguish a
        # valid account/key from a FETCH syntax/provider quirk.
        self._post("STATUS")
        records: List[Dict[str, Any]] = []
        after_logid = 0
        pages = 0
        while True:
            # Use QRZ's documented paging example with defaults for TYPE=ADIF
            # and STATUS=ALL, avoiding unnecessary options on the wire.
            option = f"MAX:250,AFTERLOGID:{after_logid}"
            try:
                data = self._post("FETCH", OPTION=option)
            except CloudProviderError:
                if pages == 0:
                    # Some QRZ deployments/accounts have shown inconsistent
                    # behavior with paged selection while accepting ALL. Fall
                    # back once to the canonical full-log request.
                    return self._single_full_fetch()
                raise
            page = self._parse_page(data)
            records.extend(page)
            pages += 1
            if len(page) < 250:
                break
            logids: List[int] = []
            for row in page:
                raw = row.get("APP_QRZLOG_LOGID") or row.get("QSO_ID")
                try:
                    logids.append(int(str(raw)))
                except (TypeError, ValueError):
                    pass
            if not logids:
                for token in (data.get("LOGIDS") or "").split(","):
                    try:
                        logids.append(int(token.strip()))
                    except ValueError:
                        pass
            if not logids:
                raise CloudProviderError("QRZ paging could not identify the last LOGID")
            next_after = max(logids) + 1
            if next_after <= after_logid:
                raise CloudProviderError("QRZ paging did not advance")
            after_logid = next_after
            if pages > 10000:
                raise CloudProviderError("QRZ paging safety limit reached")
        return {
            "records": records,
            "metadata": {"pages": pages, "coverage": "API_FULL_SYNC", "strategy": "PAGED"},
        }
