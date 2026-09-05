"""Production QRZ Logbook adapter.

Release 5.0.3 hardens the real download path observed with PU2BRU's live QRZ
logbook. A connection may validate through STATUS while FETCH returns a
successful envelope whose ADIF payload is empty, encoded differently, or only
contains LOGIDS. The adapter now requests ADIF explicitly, decodes the payload
robustly, falls back through documented FETCH forms, and refuses to report a
successful full sync when QRZ says the book contains QSOs but no records were
actually downloaded.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, unquote_plus

from .cloud_logs import ADIFParser, CloudProviderError, QRZCloudAdapter


class QRZCloudAdapterV501(QRZCloudAdapter):
    """QRZ adapter with STATUS validation and verified full-log FETCH."""

    PAGE_SIZE = 250

    @staticmethod
    def _access_help(action: str, original: str) -> str:
        return (
            f"QRZ recusou a operação {action.upper()}. "
            "A chave está configurada, mas o QRZ não aceitou esta operação. "
            "Confirme a Logbook API Access Key do logbook e tente novamente. "
            f"Resposta do QRZ: {original}."
        )

    @staticmethod
    def _decode_adif(value: str) -> str:
        """Decode QRZ ADIF whether returned normally or an extra URL-encoded time."""
        text = html.unescape(str(value or ""))
        for _ in range(3):
            if "<" in text:
                break
            if "%" not in text and "&lt;" not in text.lower():
                break
            decoded = html.unescape(unquote_plus(text))
            if decoded == text:
                break
            text = decoded
        return text

    @classmethod
    def _parse_response(cls, raw: str) -> Dict[str, str]:
        parsed = {
            key.upper(): values[-1]
            for key, values in parse_qs(raw, keep_blank_values=True).items()
        }

        # Be defensive with older/quirky QRZ responses where ADIF may not be
        # escaped exactly like the surrounding name=value envelope.
        if (not parsed.get("ADIF")) and re.search(r"(?:^|&)ADIF=", raw, flags=re.I):
            match = re.search(
                r"(?:^|&)ADIF=(.*?)(?=&(?:RESULT|REASON|LOGIDS?|COUNT|DATA)=|$)",
                raw,
                flags=re.I | re.S,
            )
            if match:
                parsed["ADIF"] = match.group(1)

        if "ADIF" in parsed:
            parsed["ADIF"] = cls._decode_adif(parsed["ADIF"])
        return parsed

    def _post(self, action: str, **fields: Any) -> Dict[str, str]:
        raw_key = str(self.credentials.get("api_key") or "")
        key = "".join(raw_key.split())
        if not key:
            raise CloudProviderError("QRZ API Key is required")
        if key != raw_key:
            self.credentials = {**self.credentials, "api_key": key}

        form = {"KEY": key, "ACTION": action.upper()}
        form.update({k: str(v) for k, v in fields.items() if v is not None})
        response = self.client.post(
            self.endpoint,
            data=form,
            headers={"User-Agent": "PU2BRU-QSO-Manager/5.0.3 (PU2BRU)"},
        )
        response.raise_for_status()
        parsed = self._parse_response(response.text)
        result = parsed.get("RESULT", "").upper()
        if result in {"FAIL", "AUTH"}:
            reason = parsed.get("REASON") or f"QRZ returned {result}"
            lowered = reason.lower()
            if reason in {"QRZ returned FAIL", "QRZ returned AUTH"} or any(
                token in lowered
                for token in ("invalid key", "access key", "unauthorized", "subscription", "privilege")
            ):
                raise CloudProviderError(self._access_help(action, reason))
            raise CloudProviderError(reason)
        return parsed

    @staticmethod
    def _status_count(data: Dict[str, str]) -> int:
        # STATUS normally places the values inside DATA, but tolerate flattened
        # variants as well.
        candidates = [data.get("COUNT", ""), data.get("QSOS", ""), data.get("DATA", "")]
        for text in candidates:
            match = re.search(r"(?:TOTAL(?:_QSO)?S?|QSOS?|COUNT)\s*[=:]\s*(\d+)", str(text), flags=re.I)
            if match:
                return int(match.group(1))
            if str(text).strip().isdigit():
                return int(str(text).strip())
        return 0

    @staticmethod
    def _response_count(data: Dict[str, str]) -> int:
        try:
            return int(str(data.get("COUNT") or "0").strip())
        except ValueError:
            return 0

    @staticmethod
    def _logids(data: Dict[str, str], page: Iterable[Dict[str, Any]] = ()) -> List[int]:
        ids: List[int] = []
        for row in page:
            raw = row.get("APP_QRZLOG_LOGID") or row.get("QSO_ID")
            try:
                ids.append(int(str(raw)))
            except (TypeError, ValueError):
                pass
        for token in str(data.get("LOGIDS") or "").split(","):
            try:
                value = int(token.strip())
            except ValueError:
                continue
            if value not in ids:
                ids.append(value)
        return ids

    def test_connection(self) -> Dict[str, Any]:
        data = self._post("STATUS")
        return {
            "ok": data.get("RESULT", "").upper() == "OK",
            "records": self._status_count(data),
            "status": "Chave e acesso ao logbook QRZ validados.",
        }

    def _parse_page(self, data: Dict[str, str]) -> Tuple[List[Dict[str, Any]], List[str]]:
        adif = self._decode_adif(data.get("ADIF", ""))
        page, errors = ADIFParser().parse(adif)
        return page, errors

    def _fetch_exact_logids(self, ids: List[int]) -> Tuple[List[Dict[str, Any]], Dict[str, str], str]:
        option = "LOGIDS:" + "+".join(str(value) for value in ids) + ",TYPE:ADIF,STATUS:ALL"
        data = self._post("FETCH", OPTION=option)
        page, errors = self._parse_page(data)
        if errors and not page:
            raise CloudProviderError("QRZ returned invalid ADIF: " + "; ".join(errors[:3]))
        return page, data, option

    def _fetch_page(self, after_logid: int) -> Tuple[List[Dict[str, Any]], Dict[str, str], str]:
        """Fetch one page, trying only documented QRZ forms."""
        options = [
            f"MAX:{self.PAGE_SIZE},AFTERLOGID:{after_logid},TYPE:ADIF,STATUS:ALL",
            f"MAX:{self.PAGE_SIZE};AFTERLOGID:{after_logid};TYPE:ADIF;STATUS:ALL",
            f"MAX:{self.PAGE_SIZE},AFTERLOGID:{after_logid}",
        ]
        diagnostics: List[str] = []

        for option in options:
            try:
                data = self._post("FETCH", OPTION=option)
            except CloudProviderError as exc:
                diagnostics.append(f"{option}: {exc}")
                continue
            page, errors = self._parse_page(data)
            if page:
                return page, data, option
            count = self._response_count(data)
            ids = self._logids(data)
            if count == 0 and not ids:
                return [], data, option
            diagnostics.append(
                f"{option}: COUNT={count}, LOGIDS={len(ids)}, ADIF={len(data.get('ADIF', ''))} bytes"
            )

        # If the server is willing to identify the records but not emit ADIF in
        # the paged request, ask for LOGIDS first and then fetch those exact IDs.
        id_option = f"MAX:{self.PAGE_SIZE},AFTERLOGID:{after_logid},TYPE:LOGIDS,STATUS:ALL"
        try:
            id_data = self._post("FETCH", OPTION=id_option)
            ids = self._logids(id_data)
            if ids:
                page, data, option = self._fetch_exact_logids(ids)
                if page:
                    return page, data, f"LOGIDS_TWO_STEP({id_option} -> {option})"
                diagnostics.append(f"{id_option}: {len(ids)} ids, exact ADIF fetch returned 0 records")
        except CloudProviderError as exc:
            diagnostics.append(f"{id_option}: {exc}")

        raise CloudProviderError(
            "QRZ informou QSOs para esta página, mas nenhum registro ADIF pôde ser lido. "
            "O snapshot NÃO foi substituído. Diagnóstico: " + " | ".join(diagnostics[:5])
        )

    def _download_paged(self, expected: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        after_logid = 0
        pages = 0
        strategies: List[str] = []

        while True:
            page, data, strategy = self._fetch_page(after_logid)
            if strategy not in strategies:
                strategies.append(strategy)
            if not page:
                break

            records.extend(page)
            pages += 1
            ids = self._logids(data, page)
            if not ids:
                raise CloudProviderError(
                    "QRZ retornou ADIF, mas não forneceu APP_QRZLOG_LOGID/LOGIDS para continuar a paginação."
                )
            next_after = max(ids) + 1
            if next_after <= after_logid:
                raise CloudProviderError("QRZ paging did not advance")
            after_logid = next_after

            if expected and len(records) >= expected:
                break
            if len(page) < self.PAGE_SIZE:
                break
            if pages > 10000:
                raise CloudProviderError("QRZ paging safety limit reached")

        return records, {
            "pages": pages,
            "coverage": "API_FULL_SYNC",
            "strategy": "PAGED_VERIFIED",
            "fetch_strategies": strategies,
            "remote_status_count": expected,
        }

    def fetch_all(self) -> Dict[str, Any]:
        status_before = self._post("STATUS")
        expected_before = self._status_count(status_before)
        records, metadata = self._download_paged(expected_before)

        status_after = self._post("STATUS")
        expected_after = self._status_count(status_after) or expected_before

        # The live log can change during a long sync. Retry once against the new
        # STATUS count. Never convert a protocol/parsing problem into a valid
        # zero-record snapshot.
        if len(records) != expected_after and expected_after != expected_before:
            records, metadata = self._download_paged(expected_after)
            status_after = self._post("STATUS")
            expected_after = self._status_count(status_after) or expected_after
            metadata["retried_after_remote_change"] = True

        if expected_after > 0 and not records:
            raise CloudProviderError(
                f"QRZ informa {expected_after} QSOs no logbook, mas o download retornou 0. "
                "O snapshot anterior foi preservado."
            )
        if expected_after and len(records) != expected_after:
            raise CloudProviderError(
                f"Download QRZ incompleto: o QRZ informa {expected_after} QSOs, "
                f"mas foram baixados {len(records)}. O snapshot anterior foi preservado."
            )

        metadata["remote_status_count"] = expected_after
        metadata["verified_record_count"] = len(records)
        return {"records": records, "metadata": metadata}
