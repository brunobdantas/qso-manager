"""Production QRZ Logbook adapter.

Release 5.0.4 uses a deterministic LOGID-manifest download strategy for QRZ.
The QRZ API supports fetching the complete list of LOGIDs with TYPE:LOGIDS and
then fetching exact records by LOGIDS.  This avoids depending on AFTERLOGID
paging behaviour while still using only documented API operations.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, unquote_plus

from .cloud_logs import ADIFParser, CloudProviderError, QRZCloudAdapter


class QRZCloudAdapterV501(QRZCloudAdapter):
    """QRZ adapter with STATUS validation and verified full-log download."""

    BATCH_SIZE = 200

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
            headers={"User-Agent": "PU2BRU-QSO-Manager/5.0.4 (PU2BRU)"},
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
        return ADIFParser().parse(adif)

    def _fetch_manifest(self) -> Tuple[List[int], Dict[str, str]]:
        # QRZ documents ALL together with TYPE and STATUS. Without MAX the
        # selection is unlimited, so this yields a stable manifest of the book.
        option = "ALL,TYPE:LOGIDS,STATUS:ALL"
        data = self._post("FETCH", OPTION=option)
        ids = sorted(set(self._logids(data)))
        count = self._response_count(data)

        if count > 0 and len(ids) != count:
            raise CloudProviderError(
                f"QRZ informou {count} LOGIDs, mas entregou {len(ids)} identificadores. "
                "O snapshot anterior foi preservado."
            )
        return ids, data

    def _fetch_exact_batch(self, ids: List[int]) -> List[Dict[str, Any]]:
        option = "LOGIDS:" + "+".join(str(value) for value in ids) + ",TYPE:ADIF,STATUS:ALL"
        data = self._post("FETCH", OPTION=option)
        page, errors = self._parse_page(data)
        if errors and not page:
            raise CloudProviderError("QRZ retornou ADIF inválido: " + "; ".join(errors[:3]))
        if len(page) != len(ids):
            raise CloudProviderError(
                f"QRZ deveria retornar {len(ids)} QSOs para um lote de LOGIDs, mas retornou {len(page)}. "
                "O snapshot anterior foi preservado."
            )
        return page

    def _download_from_manifest(self, expected: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        ids, manifest_data = self._fetch_manifest()
        manifest_count = self._response_count(manifest_data) or len(ids)

        if expected > 0 and not ids:
            raise CloudProviderError(
                f"QRZ informa {expected} QSOs no logbook, mas o manifesto retornou 0 LOGIDs. "
                "O snapshot anterior foi preservado."
            )
        if expected and manifest_count != expected:
            raise CloudProviderError(
                f"QRZ STATUS informa {expected} QSOs, mas o manifesto contém {manifest_count}. "
                "A base pode ter mudado durante a sincronização; o snapshot anterior foi preservado."
            )

        records: List[Dict[str, Any]] = []
        batches = 0
        for offset in range(0, len(ids), self.BATCH_SIZE):
            batch = ids[offset:offset + self.BATCH_SIZE]
            records.extend(self._fetch_exact_batch(batch))
            batches += 1

        if len(records) != len(ids):
            raise CloudProviderError(
                f"Download QRZ incompleto: manifesto com {len(ids)} QSOs e {len(records)} registros baixados. "
                "O snapshot anterior foi preservado."
            )

        return records, {
            "coverage": "API_FULL_SYNC",
            "strategy": "LOGID_MANIFEST_BATCHED",
            "manifest_count": len(ids),
            "batches": batches,
            "batch_size": self.BATCH_SIZE,
            "remote_status_count": expected,
        }

    def fetch_all(self) -> Dict[str, Any]:
        status_before = self._post("STATUS")
        expected_before = self._status_count(status_before)

        try:
            records, metadata = self._download_from_manifest(expected_before)
        except CloudProviderError as first_error:
            # A QSO can be added/deleted while a long synchronization is in
            # progress. If STATUS changed, retry once against the new book state.
            status_retry = self._post("STATUS")
            expected_retry = self._status_count(status_retry)
            if expected_retry == expected_before:
                raise first_error
            records, metadata = self._download_from_manifest(expected_retry)
            metadata["retried_after_remote_change"] = True
            expected_before = expected_retry

        status_after = self._post("STATUS")
        expected_after = self._status_count(status_after) or expected_before
        if expected_after != expected_before:
            # Do one clean retry if the book changed during the batch download.
            records, metadata = self._download_from_manifest(expected_after)
            metadata["retried_after_remote_change"] = True
            status_after = self._post("STATUS")
            expected_after = self._status_count(status_after) or expected_after

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
