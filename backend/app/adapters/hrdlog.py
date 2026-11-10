"""Official HRDLog.net realtime write protocol.

The implementation follows ``iw1qlh/HRDLOG-net-library``, maintained by the
HRDLog operator.  HRDLog exposes insert/update/delete writes but no supported
full-log read API, so QSO Manager keeps a user-provided complete ADIF snapshot
and mutates that snapshot only after a confirmed server response.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Optional

import httpx

from .cloud_logs import CloudLogAdapter, CloudProviderError, record_to_adif
from ..core.version import __version__


class HRDLogCloudAdapter(CloudLogAdapter):
    provider = "HRDLOG"
    endpoint = "https://robot.hrdlog.net/NewEntry.aspx"
    capabilities = {
        "read": False, "add": True, "update": True, "delete": True,
        "update_fields": [
            "CALL", "QSO_DATE", "TIME_ON", "TIME_OFF", "BAND", "FREQ",
            "MODE", "SUBMODE", "RST_SENT", "RST_RCVD", "GRIDSQUARE", "STATE",
            "CNTY", "COUNTRY", "COMMENT", "NAME", "QTH", "STATION_CALLSIGN",
            "MY_GRIDSQUARE",
        ],
        "requires_external_id": False,
        "requires_snapshot_record": True,
        "write_mode": "official_adif_key_crud",
        "max_batch": 500,
        "read_note": "Sem API de leitura completa; a cópia local é reconciliada por ADIF.",
    }

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
            "message": (
                "Credenciais completas. O HRDLog valida o Upload Code no primeiro envio; "
                "o teste não cria, edita ou exclui QSO."
            ),
        }

    def fetch_all(self) -> Dict[str, Any]:
        raise CloudProviderError(
            "HRDLog não oferece leitura completa suportada; reconcilie a cópia local com um ADIF completo."
        )

    @staticmethod
    def _qso_key(record: Dict[str, Any]) -> str:
        key = {name: record.get(name) for name in ("CALL", "QSO_DATE", "TIME_ON")}
        if not all(key.values()):
            raise CloudProviderError("HRDLog update/delete requires CALL, QSO_DATE and TIME_ON")
        return record_to_adif(key)

    @staticmethod
    def _clean_error(body: str) -> str:
        clean = re.sub(r"<[^>]+>", " ", html.unescape(body or ""))
        return re.sub(r"\s+", " ", clean).strip()

    @staticmethod
    def _reply_count(body: str, tag: str) -> Optional[int]:
        # The official response is XML with namespace-qualified elements.  A
        # namespace-tolerant pattern also supports the legacy unqualified form.
        match = re.search(
            rf"<(?:[A-Za-z0-9_]+:)?{re.escape(tag)}(?:\s[^>]*)?>\s*(\d+)\s*</(?:[A-Za-z0-9_]+:)?{re.escape(tag)}\s*>",
            body or "",
            flags=re.I,
        )
        return int(match.group(1)) if match else None

    def _send(
        self,
        command: str,
        *,
        adif: Optional[str] = None,
        qso_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        auth = self._required()
        cmd = str(command or "").strip().upper()
        if cmd not in {"INSERT", "UPDATE", "DELETE"}:
            raise CloudProviderError(f"Unsupported HRDLog command: {command}")
        data: Dict[str, str] = {
            "Callsign": auth["callsign"],
            "Code": auth["code"],
            "App": f"PU2BRU-QSO-Manager/{__version__}",
        }
        if cmd == "INSERT":
            if not adif:
                raise CloudProviderError("HRDLog insert requires ADIFData")
            data["ADIFData"] = adif
        elif cmd == "UPDATE":
            if not adif or not qso_key:
                raise CloudProviderError("HRDLog update requires ADIFKey and ADIFData")
            data.update({"Cmd": "UPDATE", "ADIFKey": qso_key, "ADIFData": adif})
        else:
            if not qso_key:
                raise CloudProviderError("HRDLog delete requires ADIFKey")
            data.update({"Cmd": "DELETE", "ADIFKey": qso_key})

        response = self.client.post(
            self.endpoint,
            data=data,
            headers={"User-Agent": f"PU2BRU-QSO-Manager/{__version__}"},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CloudProviderError(f"HRDLog HTTP {response.status_code}") from exc

        body = response.text or ""
        error = re.search(
            r"<(?:[A-Za-z0-9_]+:)?error(?:\s[^>]*)?>(.*?)</(?:[A-Za-z0-9_]+:)?error\s*>",
            body,
            flags=re.I | re.S,
        )
        if error:
            message = self._clean_error(error.group(1))
            if message.lower() in {"unknown user", "invalid token"}:
                raise CloudProviderError("HRDLog rejected Callsign/Upload Code")
            raise CloudProviderError(message[:500] or f"HRDLog rejected {cmd.lower()}")

        tag = cmd.lower()
        count = self._reply_count(body, tag)
        if count is None:
            raise CloudProviderError(self._clean_error(body)[:500] or f"HRDLog did not confirm {tag}")
        if count == 0:
            status = "duplicate" if cmd == "INSERT" else "not_changed"
            # Insert=0 is the documented duplicate state. UPDATE/DELETE=0 means
            # the key matched nothing and must never be reported as success.
            if cmd != "INSERT":
                raise CloudProviderError(f"HRDLog {tag} matched no QSO")
            return {"ok": True, "status": status, "count": count, "message": body[:500]}
        status = {"INSERT": "inserted", "UPDATE": "updated", "DELETE": "deleted"}[cmd]
        return {"ok": True, "status": status, "count": count, "message": body[:500]}

    def add_qso(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return self._send("INSERT", adif=record_to_adif(record))

    def update_qso(
        self,
        external_id: str,
        changes: Dict[str, Any],
        record: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not record:
            raise CloudProviderError("HRDLog update requires the original snapshot record")
        allowed = set(self.capabilities["update_fields"])
        normalized = {str(k).upper(): v for k, v in dict(changes or {}).items()}
        unsupported = sorted(set(normalized) - allowed)
        if not normalized:
            raise CloudProviderError("No HRDLog fields supplied for update")
        if unsupported:
            raise CloudProviderError("Unsupported HRDLog update fields: " + ", ".join(unsupported))
        updated = {**record, **normalized}
        return self._send(
            "UPDATE",
            qso_key=self._qso_key(record),
            adif=record_to_adif(updated),
        )

    def delete_qso(self, external_id: str, record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not record:
            raise CloudProviderError("HRDLog delete requires the original snapshot record")
        return self._send("DELETE", qso_key=self._qso_key(record))
