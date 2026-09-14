"""Online-only provider adapters introduced by QSO Manager v8."""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from .cloud_logs import CloudLogAdapter, CloudProviderError, record_to_adif
from ..adif.parser import ADIFParser


class HRDLogCloudAdapter(CloudLogAdapter):
    """HRDLog realtime writer.

    HRDLog documents a realtime upload endpoint but no supported full-log read
    endpoint.  QSO Manager therefore bootstraps the comparison snapshot from a
    user ADIF export and only appends records after a confirmed online insert.
    """

    provider = "HRDLOG"
    endpoint = "https://robot.hrdlog.net/NewEntry.aspx"
    capabilities = {"read": False, "add": True, "update": False, "delete": False}

    def _required(self) -> Dict[str, str]:
        callsign = str(self.credentials.get("callsign") or "").strip().upper()
        code = str(self.credentials.get("upload_code") or self.credentials.get("code") or "").strip()
        if not callsign or not code:
            raise CloudProviderError("HRDLog requires Callsign and Upload Code")
        return {"callsign": callsign, "code": code}

    def test_connection(self) -> Dict[str, Any]:
        self._required()
        return {
            "ok": True,
            "write_only": True,
            "message": "Credenciais completas. O HRDLog valida o Upload Code no primeiro envio; o teste não cria QSO.",
        }

    def fetch_all(self) -> Dict[str, Any]:
        raise CloudProviderError(
            "HRDLog não oferece leitura completa suportada; use o ADIF de bootstrap e atualização online."
        )

    def add_qso(self, record: Dict[str, Any]) -> Dict[str, Any]:
        auth = self._required()
        adif = record_to_adif(record)
        response = self.client.post(
            self.endpoint,
            data={
                "Code": auth["code"],
                "ADIFData": adif,
                "Callsign": auth["callsign"],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "PU2BRU-QSO-Manager/8.0",
            },
        )
        response.raise_for_status()
        body = response.text or ""
        lower = body.lower()
        if "<insert>1" in lower:
            return {"ok": True, "status": "inserted", "message": body[:500]}
        if "<insert>0" in lower:
            # Duplicate is a valid remote state for reconciliation purposes.
            return {"ok": True, "status": "duplicate", "message": body[:500]}
        if "unknown user</error>" in lower or "invalid token</error>" in lower:
            raise CloudProviderError("HRDLog rejected Callsign/Upload Code")
        error = re.sub(r"<[^>]+>", " ", html.unescape(body))
        error = re.sub(r"\s+", " ", error).strip()
        raise CloudProviderError(error[:500] or "HRDLog did not confirm the insert")


class LoTWConfirmationAdapter(CloudLogAdapter):
    """Read received LoTW confirmations through the official report service."""

    provider = "LOTW"
    endpoint = "https://lotw.arrl.org/lotwuser/lotwreport.adi"
    capabilities = {"read": True, "add": False, "update": False, "delete": False}

    def _required(self) -> Dict[str, str]:
        login = str(self.credentials.get("login") or self.credentials.get("username") or "").strip()
        password = str(self.credentials.get("password") or "").strip()
        if not login or not password:
            raise CloudProviderError("LoTW requires login and password")
        return {"login": login, "password": password}

    def _download(self, since: str = "1945-11-15") -> str:
        auth = self._required()
        params = {
            **auth,
            "qso_query": "1",
            "qso_qsl": "yes",
            "qso_qsldetail": "yes",
            "qso_withown": "yes",
            "qso_qslsince": since,
        }
        response = self.client.get(self.endpoint, params=params)
        response.raise_for_status()
        body = response.text or ""
        if "<EOH>" not in body.upper():
            clean = re.sub(r"<[^>]+>", " ", html.unescape(body))
            clean = re.sub(r"\s+", " ", clean).strip()
            raise CloudProviderError("LoTW did not return ADIF" + (f": {clean[:300]}" if clean else ""))
        return body

    def test_connection(self) -> Dict[str, Any]:
        body = self._download("2026-01-01")
        records, errors = ADIFParser().parse(body)
        return {"ok": True, "records": len(records), "parse_errors": errors[:3]}

    def fetch_all(self) -> Dict[str, Any]:
        body = self._download("1945-11-15")
        records, errors = ADIFParser().parse(body)
        for row in records:
            if str(row.get("QSL_RCVD") or "").upper() == "Y":
                row.setdefault("LOTW_QSL_RCVD", "Y")
                if row.get("QSLRDATE"):
                    row.setdefault("LOTW_QSLRDATE", row.get("QSLRDATE"))
        return {
            "records": records,
            "metadata": {
                "coverage": "API_FULL_SYNC",
                "source": "lotw_confirmation_api",
                "confirmations_only": True,
                "parse_errors": errors[:20],
            },
        }


class EQSLInboxAdapter(CloudLogAdapter):
    """Read the complete eQSL Inbox/Archive as confirmation evidence.

    DownloadInbox.cfm returns an HTML control page that contains links to a
    generated .ADI/.TXT file.  Parsing that HTML as ADIF can create a bogus
    one-record snapshot because HTML markup may accidentally resemble ADIF
    tags.  Treat HTML strictly as a control page and parse only the generated
    download file.
    """

    provider = "EQSL_INBOX"
    base_url = "https://www.eqsl.cc/qslcard/"
    capabilities = {"read": True, "add": False, "update": False, "delete": False}
    USER_AGENT = "PU2BRU-QSO-Manager/9.0 (PU2BRU)"

    def _params(self) -> Dict[str, str]:
        username = str(self.credentials.get("username") or "").strip().upper()
        password = str(self.credentials.get("password") or "").strip()
        if not username or not password:
            raise CloudProviderError("eQSL requires Username/Indicativo and password")
        params = {
            "Username": username,
            "Password": password,
            "RcvdSince": "19000101",
        }
        nickname = str(self.credentials.get("qth_nickname") or "").strip()
        if nickname:
            params["QTHNickname"] = nickname
        return params

    @staticmethod
    def _looks_html(response, body: str) -> bool:
        content_type = str(response.headers.get("content-type") or "").lower()
        sample = body[:2000].lower()
        return (
            "text/html" in content_type
            or "<html" in sample
            or "<body" in sample
            or "<!doctype" in sample
        )

    @staticmethod
    def _reported_count(body: str) -> Optional[int]:
        clean = re.sub(r"<[^>]+>", " ", html.unescape(body))
        clean = re.sub(r"\s+", " ", clean)
        for pattern in (
            r"there\s+were\s+([0-9][0-9.,]*)\s+records?",
            r"([0-9][0-9.,]*)\s+records?\s+(?:were\s+)?(?:built|generated|found)",
        ):
            match = re.search(pattern, clean, flags=re.I)
            if match:
                digits = re.sub(r"\D", "", match.group(1))
                if digits:
                    return int(digits)
        return None

    @staticmethod
    def _hrefs(body: str) -> List[str]:
        hrefs = re.findall(
            r'href\s*=\s*["\']([^"\']+)["\']',
            html.unescape(body),
            flags=re.I,
        )
        ranked = []
        seen = set()
        for href in hrefs:
            href = str(href or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            lower = href.split("?", 1)[0].lower()
            if lower.endswith((".adi", ".adif")):
                ranked.append((0, href))
            elif lower.endswith(".txt"):
                ranked.append((1, href))
        ranked.sort(key=lambda item: item[0])
        return [href for _rank, href in ranked]

    @staticmethod
    def _validate_count(records: List[Dict[str, Any]], expected: Optional[int]) -> None:
        if expected is not None and len(records) != expected:
            raise CloudProviderError(
                f"Download eQSL Inbox incompleto: a página informa {expected} registros, "
                f"mas o arquivo ADIF contém {len(records)}. O snapshot anterior foi preservado."
            )

    def _fetch(self) -> Dict[str, Any]:
        response = self.client.get(
            urljoin(self.base_url, "DownloadInbox.cfm"),
            params=self._params(),
            headers={"User-Agent": self.USER_AGENT},
        )
        response.raise_for_status()
        body = response.text or ""
        expected = self._reported_count(body)

        if self._looks_html(response, body):
            clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(body))).strip()
            lowered = clean.lower()
            if "not yet logged in" in lowered or ("invalid" in lowered and "password" in lowered):
                raise CloudProviderError("eQSL recusou as credenciais para download do Inbox")

            diagnostics = []
            for href in self._hrefs(body):
                link = urljoin(str(response.url), href)
                downloaded = self.client.get(
                    link,
                    headers={"User-Agent": self.USER_AGENT},
                )
                if not downloaded.is_success:
                    diagnostics.append(f"{href}: HTTP {downloaded.status_code}")
                    continue
                records, errors = ADIFParser().parse(html.unescape(downloaded.text or ""))
                if not records:
                    diagnostics.append(f"{href}: 0 registros")
                    continue
                self._validate_count(records, expected)
                return {
                    "records": records,
                    "errors": errors,
                    "strategy": "INBOX_ADIF_FILE",
                    "reported_count": expected,
                    "download_file": link.rsplit("/", 1)[-1].split("?", 1)[0],
                }

            if expected == 0:
                return {
                    "records": [],
                    "errors": [],
                    "strategy": "INBOX_ADIF_FILE",
                    "reported_count": 0,
                    "download_file": None,
                }

            detail = " | ".join(diagnostics[:4])
            raise CloudProviderError(
                "eQSL criou a página de download do Inbox, mas o QSO Manager não conseguiu obter o arquivo ADIF"
                + (f". Diagnóstico: {detail}" if detail else ".")
            )

        records, errors = ADIFParser().parse(html.unescape(body))
        if not records and expected != 0:
            raise CloudProviderError("eQSL Inbox não retornou um arquivo ADIF válido")
        self._validate_count(records, expected)
        return {
            "records": records,
            "errors": errors,
            "strategy": "DIRECT_ADIF",
            "reported_count": expected,
            "download_file": None,
        }

    def test_connection(self) -> Dict[str, Any]:
        result = self._fetch()
        return {
            "ok": True,
            "records": len(result["records"]),
            "parse_errors": result["errors"][:3],
            "download_strategy": result.get("strategy"),
            "remote_reported_count": result.get("reported_count"),
        }

    def fetch_all(self) -> Dict[str, Any]:
        result = self._fetch()
        records = result["records"]
        for row in records:
            row.setdefault("EQSL_QSL_RCVD", "Y")
            # The eQSL Inbox file is from the sender's perspective. Preserve
            # those fields as evidence. Only copy an explicit received date
            # when the downloaded ADIF actually supplies one.
            if row.get("QSLRDATE"):
                row.setdefault("EQSL_QSLRDATE", row.get("QSLRDATE"))
        return {
            "records": records,
            "metadata": {
                "coverage": "API_FULL_SYNC",
                "source": "eqsl_inbox_api",
                "confirmations_only": True,
                "parse_errors": result["errors"][:20],
                "download_strategy": result.get("strategy"),
                "remote_reported_count": result.get("reported_count"),
                "download_file": result.get("download_file"),
            },
        }
