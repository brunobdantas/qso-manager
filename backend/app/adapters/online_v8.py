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
    """Read the eQSL Inbox/Archive as confirmation evidence."""

    provider = "EQSL_INBOX"
    base_url = "https://www.eqsl.cc/qslcard/"
    capabilities = {"read": True, "add": False, "update": False, "delete": False}

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
    def _hrefs(body: str) -> List[str]:
        return re.findall(
            r'href=["\']([^"\']+\.(?:adi|adif|txt)(?:\?[^"\']*)?)["\']',
            html.unescape(body),
            flags=re.I,
        )

    def _fetch(self) -> Dict[str, Any]:
        response = self.client.get(urljoin(self.base_url, "DownloadInbox.cfm"), params=self._params())
        response.raise_for_status()
        body = response.text or ""
        records, errors = ADIFParser().parse(body)
        if records:
            return {"records": records, "errors": errors}
        for href in self._hrefs(body):
            downloaded = self.client.get(urljoin(str(response.url), href))
            if not downloaded.is_success:
                continue
            records, errors = ADIFParser().parse(downloaded.text)
            if records:
                return {"records": records, "errors": errors}
        clean = re.sub(r"<[^>]+>", " ", html.unescape(body))
        clean = re.sub(r"\s+", " ", clean).strip()
        raise CloudProviderError("eQSL Inbox did not return ADIF" + (f": {clean[:300]}" if clean else ""))

    def test_connection(self) -> Dict[str, Any]:
        result = self._fetch()
        return {"ok": True, "records": len(result["records"]), "parse_errors": result["errors"][:3]}

    def fetch_all(self) -> Dict[str, Any]:
        result = self._fetch()
        records = result["records"]
        for row in records:
            row.setdefault("EQSL_QSL_RCVD", "Y")
            # eQSL's incoming file may carry QSL_SENT/QSLSDATE because the record
            # is from the sender's perspective. Preserve it as evidence; never
            # fabricate an eQSL receive date from QSO_DATE.
            if row.get("QSLRDATE"):
                row.setdefault("EQSL_QSLRDATE", row.get("QSLRDATE"))
        return {
            "records": records,
            "metadata": {
                "coverage": "API_FULL_SYNC",
                "source": "eqsl_inbox_api",
                "confirmations_only": True,
                "parse_errors": result["errors"][:20],
            },
        }
