"""Production QRZ Logbook adapter.

Release 5.0.5 deliberately goes back to the simplest forms documented by QRZ.
The primary full-sync request is ACTION=FETCH with OPTION=ALL only; ADIF and
ALL statuses are already the documented defaults. If that transaction cannot
be completed, the adapter falls back to QRZ's exact paging example:
MAX:250,AFTERLOGID:n. No TYPE:LOGIDS manifest or compound selector is required.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, unquote_plus

import httpx

from .cloud_logs import ADIFParser, CloudProviderError, QRZCloudAdapter


class QRZCloudAdapterV501(QRZCloudAdapter):
    """QRZ adapter with STATUS validation and verified full-log download."""

    PAGE_SIZE = 250

    @staticmethod
    def _access_help(action: str, original: str) -> str:
        return (
            f"QRZ recusou a operação {action.upper()} por autenticação/permissão. "
            "A Logbook API Key deve ser a chave do logbook correto. "
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

        # Some QRZ responses have historically been inconsistent around the
        # ADIF value encoding. Recover the raw ADIF value if parse_qs did not.
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

    @staticmethod
    def _safe_option_label(option: str) -> str:
        option = str(option or "")
        if option.startswith("LOGIDS:"):
            return "LOGIDS:<lista>"
        return option[:180]

    def _post(self, action: str, **fields: Any) -> Dict[str, str]:
        raw_key = str(self.credentials.get("api_key") or "")
        key = "".join(raw_key.split())
        if not key:
            raise CloudProviderError("QRZ API Key is required")
        if key != raw_key:
            self.credentials = {**self.credentials, "api_key": key}

        action = action.upper()
        form = {"KEY": key, "ACTION": action}
        form.update({k: str(v) for k, v in fields.items() if v is not None})
        try:
            response = self.client.post(
                self.endpoint,
                data=form,
                headers={"User-Agent": "PU2BRU-QSO-Manager/5.0.5 (PU2BRU)"},
                timeout=180.0 if action == "FETCH" else 60.0,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            option = self._safe_option_label(form.get("OPTION", ""))
            raise CloudProviderError(
                f"QRZ {action} excedeu o tempo de resposta"
                + (f" (OPTION={option})" if option else "")
            ) from exc
        except httpx.HTTPError as exc:
            raise CloudProviderError(f"Falha HTTP ao acessar QRZ {action}: {exc}") from exc

        parsed = self._parse_response(response.text)
        result = parsed.get("RESULT", "").upper()
        if result in {"FAIL", "AUTH"}:
            reason = parsed.get("REASON") or f"QRZ returned {result}"
            lowered = reason.lower()
            if result == "AUTH" or any(
                token in lowered
                for token in ("invalid key", "access key", "unauthorized", "subscription", "privilege")
            ):
                raise CloudProviderError(self._access_help(action, reason))
            option = self._safe_option_label(form.get("OPTION", ""))
            raise CloudProviderError(
                f"QRZ {action} falhou"
                + (f" (OPTION={option})" if option else "")
                + f": {reason}"
            )
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
                value = int(str(raw))
            except (TypeError, ValueError):
                continue
            if value not in ids:
                ids.append(value)
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

    def _download_direct(self, expected: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        # This is the canonical full-book request in the QRZ documentation.
        # TYPE defaults to ADIF and STATUS defaults to ALL, so do not add any
        # extra selector that a particular QRZ deployment might reject.
        data = self._post("FETCH", OPTION="ALL")
        records, errors = self._parse_page(data)
        if errors and not records:
            raise CloudProviderError("QRZ retornou ADIF inválido no FETCH ALL: " + "; ".join(errors[:3]))

        response_count = self._response_count(data)
        if response_count and len(records) != response_count:
            raise CloudProviderError(
                f"FETCH ALL incompleto: QRZ informou COUNT={response_count}, mas foram lidos {len(records)} QSOs."
            )
        if expected and len(records) != expected:
            raise CloudProviderError(
                f"FETCH ALL retornou {len(records)} QSOs, mas STATUS informa {expected}."
            )
        return records, {
            "coverage": "API_FULL_SYNC",
            "strategy": "DIRECT_ALL",
            "remote_status_count": expected,
            "response_count": response_count,
        }

    def _download_paged(self, expected: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        after_logid = 0
        pages = 0
        seen_pages = set()

        while True:
            option = f"MAX:{self.PAGE_SIZE},AFTERLOGID:{after_logid}"
            data = self._post("FETCH", OPTION=option)
            page, errors = self._parse_page(data)
            if errors and not page:
                raise CloudProviderError(
                    f"QRZ retornou ADIF inválido na página {pages + 1}: " + "; ".join(errors[:3])
                )

            ids = self._logids(data, page)
            signature = (tuple(ids[:3]), tuple(ids[-3:]), len(page))
            if signature in seen_pages and page:
                raise CloudProviderError(
                    f"QRZ repetiu a mesma página na paginação (AFTERLOGID={after_logid})."
                )
            seen_pages.add(signature)

            if not page:
                break

            records.extend(page)
            pages += 1

            if len(page) < self.PAGE_SIZE:
                break
            if not ids:
                raise CloudProviderError(
                    f"QRZ retornou {len(page)} QSOs na página {pages}, mas não forneceu LOGIDS para continuar."
                )

            next_after = max(ids) + 1
            if next_after <= after_logid:
                raise CloudProviderError(
                    f"QRZ não avançou a paginação: AFTERLOGID={after_logid}, maior LOGID recebido={max(ids)}."
                )
            after_logid = next_after

            if expected and len(records) >= expected:
                break
            if pages > 10000:
                raise CloudProviderError("QRZ paging safety limit reached")

        if expected and len(records) != expected:
            raise CloudProviderError(
                f"Paginação QRZ retornou {len(records)} QSOs, mas STATUS informa {expected}."
            )
        return records, {
            "coverage": "API_FULL_SYNC",
            "strategy": "PAGED_MINIMAL",
            "pages": pages,
            "page_size": self.PAGE_SIZE,
            "remote_status_count": expected,
        }

    def _download_verified(self, expected: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        direct_error = None
        try:
            return self._download_direct(expected)
        except CloudProviderError as exc:
            direct_error = str(exc)

        try:
            records, metadata = self._download_paged(expected)
            metadata["direct_all_error"] = direct_error
            return records, metadata
        except CloudProviderError as paged_error:
            raise CloudProviderError(
                f"QRZ está conectado e STATUS informa {expected} QSOs, mas as duas formas oficiais de leitura falharam. "
                f"FETCH ALL: {direct_error} | PAGINAÇÃO: {paged_error}. "
                "O snapshot anterior foi preservado; não é necessário recadastrar a chave."
            ) from paged_error

    def fetch_all(self) -> Dict[str, Any]:
        status_before = self._post("STATUS")
        expected_before = self._status_count(status_before)
        records, metadata = self._download_verified(expected_before)

        status_after = self._post("STATUS")
        expected_after = self._status_count(status_after) or expected_before
        if expected_after != expected_before:
            # The book changed while downloading. Retry once against the new
            # authoritative count instead of saving an ambiguous snapshot.
            records, metadata = self._download_verified(expected_after)
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
