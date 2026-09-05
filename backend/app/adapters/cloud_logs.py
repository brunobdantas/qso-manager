"""Cloud logbook adapters for QRZ, WRL, Club Log and eQSL.

All credentials stay in the Python backend. Downloads are read-only; mutating
operations are deliberately small, explicit and provider-capability aware.
"""
from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urljoin

import httpx

from ..adif.parser import ADIFParser


class CloudProviderError(RuntimeError):
    pass


def _adif_field(name: str, value: Any) -> str:
    if value is None or value == "":
        return ""
    text = str(value)
    upper = name.upper()
    if upper in {"QSO_DATE", "QSLRDATE", "QSLSDATE"}:
        text = text.replace("-", "")
    if upper in {"TIME_ON", "TIME_OFF"}:
        text = text.replace(":", "")
    return f"<{name}:{len(text)}>{text}"


def record_to_adif(record: Dict[str, Any]) -> str:
    preferred = [
        "CALL", "QSO_DATE", "TIME_ON", "TIME_OFF", "BAND", "FREQ", "MODE", "SUBMODE",
        "RST_SENT", "RST_RCVD", "GRIDSQUARE", "STATE", "CNTY", "COUNTRY", "DXCC", "CQZ",
        "ITUZ", "CONT", "IOTA", "COMMENT", "NAME", "QTH", "STATION_CALLSIGN", "MY_GRIDSQUARE",
    ]
    fields: List[str] = []
    emitted = set()
    for key in preferred:
        if key in record:
            fields.append(_adif_field(key, record.get(key)))
            emitted.add(key)
    for key, value in record.items():
        key = str(key).upper()
        if key in emitted or key.startswith("_"):
            continue
        if value is None or isinstance(value, (dict, list, tuple)):
            continue
        fields.append(_adif_field(key, value))
    return "".join(fields) + "<EOR>"


def records_to_adif(records: Iterable[Dict[str, Any]], program_id: str = "PU2BRU-QSO-Manager") -> str:
    header = _adif_field("ADIF_VER", "3.1.4") + _adif_field("PROGRAMID", program_id) + "<EOH>\n"
    return header + "\n".join(record_to_adif(row) for row in records)


class CloudLogAdapter(ABC):
    provider: str
    capabilities: Dict[str, bool]

    def __init__(self, credentials: Dict[str, Any], client: Optional[httpx.Client] = None) -> None:
        self.credentials = credentials
        self.client = client or self._build_client()
        self._owns_client = client is None

    @staticmethod
    def _build_client() -> httpx.Client:
        """Create the shared HTTP client without failing on an unsupported host proxy.

        HTTPX 0.26 accepts ``socks5`` but some launchers expose ``socks5h`` in
        the process environment.  Prefer the configured environment in normal
        installations and fail over to a direct client only for this specific
        incompatibility.  Credentials and proxy URLs are never included in the
        resulting error path.
        """
        try:
            return httpx.Client(timeout=60.0, follow_redirects=True)
        except ValueError as exc:
            if "Unknown scheme for proxy URL" not in str(exc):
                raise
            return httpx.Client(timeout=60.0, follow_redirects=True, trust_env=False)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]: ...

    @abstractmethod
    def fetch_all(self) -> Dict[str, Any]: ...

    def add_qso(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise CloudProviderError(f"{self.provider} does not support add through this adapter")

    def update_qso(self, external_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        raise CloudProviderError(f"{self.provider} does not support update through this adapter")

    def delete_qso(self, external_id: str, record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise CloudProviderError(f"{self.provider} does not support delete through this adapter")


class QRZCloudAdapter(CloudLogAdapter):
    provider = "QRZ"
    endpoint = "https://logbook.qrz.com/api"
    capabilities = {"read": True, "add": True, "update": False, "delete": False}

    def _post(self, action: str, **fields: Any) -> Dict[str, str]:
        key = str(self.credentials.get("api_key") or "").strip()
        if not key:
            raise CloudProviderError("QRZ API Key is required")
        data = {"KEY": key, "ACTION": action.upper()}
        data.update({k: str(v) for k, v in fields.items() if v is not None})
        response = self.client.post(
            self.endpoint,
            data=data,
            headers={"User-Agent": "PU2BRU-QSO-Manager/5.0 (PU2BRU)"},
        )
        response.raise_for_status()
        parsed = {k.upper(): values[-1] for k, values in parse_qs(response.text, keep_blank_values=True).items()}
        result = parsed.get("RESULT", "").upper()
        if result in {"FAIL", "AUTH"}:
            raise CloudProviderError(parsed.get("REASON") or f"QRZ returned {result}")
        return parsed

    def test_connection(self) -> Dict[str, Any]:
        data = self._post("STATUS")
        return {"ok": data.get("RESULT", "").upper() == "OK", "status": data.get("DATA", "")}

    def fetch_all(self) -> Dict[str, Any]:
        parser = ADIFParser()
        records: List[Dict[str, Any]] = []
        after_logid = 0
        pages = 0
        while True:
            option = f"MAX:250,AFTERLOGID:{after_logid},TYPE:ADIF,STATUS:ALL"
            data = self._post("FETCH", OPTION=option)
            adif = data.get("ADIF", "")
            page, errors = parser.parse(adif)
            if errors and not page:
                raise CloudProviderError("QRZ returned invalid ADIF: " + "; ".join(errors[:3]))
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
        return {"records": records, "metadata": {"pages": pages, "coverage": "API_FULL_SYNC"}}

    def fetch_logids(self, logids: Iterable[str]) -> Dict[str, Any]:
        ids = [str(x).strip() for x in logids if str(x).strip()]
        if not ids:
            return {"records": [], "verified": False}
        option = "LOGIDS:" + "+".join(ids) + ",TYPE:ADIF,STATUS:ALL"
        data = self._post("FETCH", OPTION=option)
        records, errors = ADIFParser().parse(data.get("ADIF", ""))
        returned = {str(r.get("APP_QRZLOG_LOGID") or r.get("QSO_ID") or "") for r in records}
        return {"records": records, "verified": all(i in returned for i in ids), "errors": errors[:10]}

    def add_qso(self, record: Dict[str, Any]) -> Dict[str, Any]:
        # Deliberately no OPTION=REPLACE: QRZ warns REPLACE can overwrite confirmations.
        data = self._post("INSERT", ADIF=record_to_adif(record))
        if data.get("RESULT", "").upper() != "OK":
            raise CloudProviderError(data.get("REASON") or "QRZ did not insert the QSO")
        return {"ok": True, "external_id": data.get("LOGID"), "result": data.get("RESULT")}


class WRLCloudAdapter(CloudLogAdapter):
    provider = "WRL"
    base_url = "https://api.worldradioleague.com"
    capabilities = {"read": True, "add": True, "update": True, "delete": True}

    def _headers(self) -> Dict[str, str]:
        key = str(self.credentials.get("api_key") or "").strip()
        if not key:
            raise CloudProviderError("WRL Developer API Key is required")
        return {"Authorization": f"Bearer {key}", "User-Agent": "PU2BRU-QSO-Manager/5.0"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        response = self.client.request(method, self.base_url + path, headers=self._headers(), **kwargs)
        if response.status_code == 429:
            raise CloudProviderError(f"WRL rate limit reached; retry after {response.headers.get('Retry-After', '?')} seconds")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CloudProviderError(f"WRL returned non-JSON response ({response.status_code})") from exc
        if not response.is_success or payload.get("error"):
            err = payload.get("error") or {}
            raise CloudProviderError(err.get("message") or f"WRL HTTP {response.status_code}")
        return payload

    def test_connection(self) -> Dict[str, Any]:
        payload = self._request("GET", "/v1/me")
        return {"ok": True, "account": payload.get("data") or {}}

    @staticmethod
    def _band(value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        text = str(value).strip().lower()
        if text.endswith("m") or text.endswith("cm"):
            return text
        try:
            n = float(value)
        except (TypeError, ValueError):
            return text
        if n >= 1:
            return f"{n:g}m"
        return f"{n * 100:g}cm"

    @staticmethod
    def _to_record(contact: Dict[str, Any]) -> Dict[str, Any]:
        stamp = str(contact.get("timestamp") or "")
        qso_date = time_on = None
        if stamp:
            try:
                dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
                qso_date = dt.strftime("%Y-%m-%d")
                time_on = dt.strftime("%H:%M:%S")
            except ValueError:
                pass
        record: Dict[str, Any] = {
            "CALL": contact.get("call"), "QSO_DATE": qso_date, "TIME_ON": time_on,
            "FREQ": contact.get("freq"), "BAND": WRLCloudAdapter._band(contact.get("band")),
            "MODE": contact.get("mode"), "RST_SENT": contact.get("rstSent"), "RST_RCVD": contact.get("rstRcvd"),
            "GRIDSQUARE": contact.get("gridsquare"), "STATE": contact.get("state"),
            "COMMENT": contact.get("notes"), "NAME": contact.get("name"), "QTH": contact.get("qth"),
            "STATION_CALLSIGN": contact.get("stationCallsign"), "MY_GRIDSQUARE": contact.get("myGridsquare"),
            "APP_WRL_ID": contact.get("id"), "APP_WRL_LOGBOOK_ID": contact.get("logbookId"),
        }
        return {k: v for k, v in record.items() if v is not None and v != ""}

    def fetch_all(self) -> Dict[str, Any]:
        records: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        pages = 0
        requested_logbook = self.credentials.get("logbook_id")
        while True:
            params: Dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            if requested_logbook:
                params["logbookId"] = requested_logbook
            payload = self._request("GET", "/v1/contacts", params=params)
            contacts = payload.get("data") or []
            records.extend(self._to_record(c) for c in contacts)
            pages += 1
            cursor = (payload.get("meta") or {}).get("nextCursor")
            if not cursor:
                break
            if pages > 10000:
                raise CloudProviderError("WRL paging safety limit reached")
        return {"records": records, "metadata": {"pages": pages, "coverage": "API_FULL_SYNC", "logbook_id": requested_logbook}}

    @staticmethod
    def _create_payload(record: Dict[str, Any], logbook_id: Optional[str] = None) -> Dict[str, Any]:
        qso_date = str(record.get("QSO_DATE") or "").replace("-", "")
        time_on = str(record.get("TIME_ON") or "").replace(":", "")
        freq = record.get("FREQ")
        band = record.get("BAND")
        mode = record.get("SUBMODE") or record.get("MODE")
        if not all([record.get("CALL"), qso_date, time_on, freq, band, mode]):
            raise CloudProviderError("WRL add requires CALL, QSO_DATE, TIME_ON, FREQ, BAND and MODE/SUBMODE")
        payload: Dict[str, Any] = {
            "programId": "PU2BRU-QSO-Manager", "call": record["CALL"],
            "timestamp": {"qsoDate": qso_date, "timeOn": time_on[:6]},
            "freq": float(freq), "band": band, "mode": mode,
        }
        mapping = {
            "RST_SENT": "rstSent", "RST_RCVD": "rstRcvd", "COMMENT": "notes",
            "STATION_CALLSIGN": "stationCallsign", "MY_GRIDSQUARE": "myGridsquare",
            "NAME": "name", "GRIDSQUARE": "gridsquare", "QTH": "qth", "STATE": "state", "OPERATOR": "operator",
        }
        for source, target in mapping.items():
            if record.get(source) not in (None, ""):
                payload[target] = str(record[source])
        if logbook_id:
            payload["logbookId"] = logbook_id
        return payload

    def add_qso(self, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._create_payload(record, self.credentials.get("logbook_id"))
        result = self._request("POST", "/v1/contacts", json=payload)
        data = result.get("data") or {}
        return {"ok": True, "external_id": data.get("id"), "data": data, "meta": result.get("meta")}

    def update_qso(self, external_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        if not external_id:
            raise CloudProviderError("WRL contact id is required for update")
        mapping = {
            "CALL": "call", "FREQ": "freq", "BAND": "band", "MODE": "mode", "SUBMODE": "mode",
            "RST_SENT": "rstSent", "RST_RCVD": "rstRcvd", "COMMENT": "notes", "STATION_CALLSIGN": "stationCallsign",
            "MY_GRIDSQUARE": "myGridsquare", "NAME": "name", "GRIDSQUARE": "gridsquare", "QTH": "qth",
            "STATE": "state", "OPERATOR": "operator",
        }
        payload: Dict[str, Any] = {}
        for key, value in changes.items():
            if key in mapping:
                payload[mapping[key]] = value
        if "QSO_DATE" in changes or "TIME_ON" in changes:
            raise CloudProviderError("WRL time update needs the complete original date/time context; use the managed QSO action instead")
        if not payload:
            raise CloudProviderError("No supported WRL fields supplied for update")
        result = self._request("PATCH", f"/v1/contacts/{external_id}", json=payload)
        return {"ok": True, "data": result.get("data")}

    def delete_qso(self, external_id: str, record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not external_id:
            raise CloudProviderError("WRL contact id is required for delete")
        result = self._request("DELETE", f"/v1/contacts/{external_id}")
        return {"ok": True, "data": result.get("data")}


class ClubLogCloudAdapter(CloudLogAdapter):
    provider = "CLUBLOG"
    capabilities = {"read": True, "add": True, "update": False, "delete": True}
    base_url = "https://clublog.org"

    def _required(self) -> Dict[str, str]:
        values = {
            "email": str(self.credentials.get("email") or "").strip(),
            "password": str(self.credentials.get("app_password") or self.credentials.get("password") or "").strip(),
            "callsign": str(self.credentials.get("callsign") or "").strip().upper(),
        }
        if not all(values.values()):
            raise CloudProviderError("Club Log requires email, Application Password and callsign")
        return values

    def fetch_all(self) -> Dict[str, Any]:
        fields = self._required()
        response = self.client.post(self.base_url + "/getadif.php", data={"email": fields["email"], "password": fields["password"], "call": fields["callsign"]})
        response.raise_for_status()
        text = response.text
        records, errors = ADIFParser().parse(text)
        if not records:
            msg = re.sub(r"<[^>]+>", " ", text)[:500].strip()
            raise CloudProviderError("Club Log did not return an ADIF log" + (f": {msg}" if msg else ""))
        return {"records": records, "metadata": {"coverage": "API_FULL_SYNC", "parse_errors": errors[:10], "minimalist_export": True}}

    def test_connection(self) -> Dict[str, Any]:
        result = self.fetch_all()
        return {"ok": True, "records": len(result["records"]), "note": "Club Log validates credentials by downloading the log."}

    def add_qso(self, record: Dict[str, Any]) -> Dict[str, Any]:
        fields = self._required()
        api_key = str(self.credentials.get("api_key") or "").strip()
        if not api_key:
            raise CloudProviderError("Club Log API key is required for uploads")
        response = self.client.post(self.base_url + "/realtime.php", data={
            "email": fields["email"], "password": fields["password"], "callsign": fields["callsign"],
            "adif": record_to_adif(record), "api": api_key,
        })
        if not response.is_success:
            raise CloudProviderError(response.text.strip() or f"Club Log HTTP {response.status_code}")
        return {"ok": True, "message": response.text.strip()}

    @staticmethod
    def _band_id(band: Any) -> str:
        text = str(band or "").strip().lower()
        mapping = {"70cm": "70", "23cm": "23", "13cm": "13"}
        if text in mapping:
            return mapping[text]
        if text.endswith("m"):
            return text[:-1]
        raise CloudProviderError(f"Club Log delete cannot map band {band!r}")

    def delete_qso(self, external_id: str, record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not record:
            raise CloudProviderError("Club Log delete requires the exact QSO record")
        fields = self._required()
        api_key = str(self.credentials.get("api_key") or "").strip()
        if not api_key:
            raise CloudProviderError("Club Log API key is required for delete")
        date = str(record.get("QSO_DATE") or "").replace("/", "-")
        if len(date) == 8 and "-" not in date:
            date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        time = str(record.get("TIME_ON") or "").replace(":", "")
        if len(time) < 4:
            raise CloudProviderError("Club Log delete requires exact QSO time")
        time = (time + "000000")[:6]
        stamp = f"{date} {time[:2]}:{time[2:4]}:{time[4:6]}"
        response = self.client.post(self.base_url + "/delete.php", data={
            "email": fields["email"], "password": fields["password"], "callsign": fields["callsign"],
            "dxcall": record.get("CALL"), "datetime": stamp, "bandid": self._band_id(record.get("BAND")), "api": api_key,
        })
        if not response.is_success:
            raise CloudProviderError(response.text.strip() or f"Club Log HTTP {response.status_code}")
        body = response.text.strip()
        if "not deleted" in body.lower():
            raise CloudProviderError(body)
        return {"ok": True, "message": body}


class EQSLCloudAdapter(CloudLogAdapter):
    provider = "EQSL"
    capabilities = {"read": True, "add": True, "update": False, "delete": False}
    base_url = "https://www.eqsl.cc/qslcard/"

    def _required(self) -> Dict[str, str]:
        username = str(self.credentials.get("username") or "").strip().upper()
        password = str(self.credentials.get("password") or "").strip()
        if not username or not password:
            raise CloudProviderError("eQSL requires callsign/Username and password")
        return {"Username": username, "Password": password}

    def _params(self) -> Dict[str, str]:
        params = self._required()
        nickname = str(self.credentials.get("qth_nickname") or "").strip()
        if nickname:
            params["QTHNickname"] = nickname
        return params

    def fetch_all(self) -> Dict[str, Any]:
        response = self.client.get(urljoin(self.base_url, "DownloadADIF.cfm"), params=self._params())
        response.raise_for_status()
        body = html.unescape(response.text)
        records, errors = ADIFParser().parse(body)
        if records:
            return {"records": records, "metadata": {"coverage": "API_FULL_SYNC", "normalized_export": True, "parse_errors": errors[:10]}}
        hrefs = re.findall(r'href=["\']([^"\']+\.(?:adi|adif)(?:\?[^"\']*)?)["\']', body, flags=re.I)
        for href in hrefs:
            downloaded = self.client.get(urljoin(str(response.url), href))
            if not downloaded.is_success:
                continue
            page, page_errors = ADIFParser().parse(downloaded.text)
            if page:
                return {"records": page, "metadata": {"coverage": "API_FULL_SYNC", "normalized_export": True, "parse_errors": page_errors[:10]}}
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        raise CloudProviderError("eQSL OutBox download did not return ADIF" + (f": {text[:300]}" if text else ""))

    def test_connection(self) -> Dict[str, Any]:
        response = self.client.get(urljoin(self.base_url, "DisplayLastUploadDate.cfm"), params=self._params())
        response.raise_for_status()
        body = re.sub(r"<[^>]+>", " ", html.unescape(response.text))
        if "invalid" in body.lower() and "password" in body.lower():
            raise CloudProviderError("eQSL rejected the credentials")
        return {"ok": True, "message": re.sub(r"\s+", " ", body).strip()[:250]}

    def add_qso(self, record: Dict[str, Any]) -> Dict[str, Any]:
        auth = self._required()
        qth = str(self.credentials.get("qth_nickname") or "").strip()
        payload_record = dict(record)
        payload_record["EQSL_USER"] = auth["Username"]
        payload_record["EQSL_PSWD"] = auth["Password"]
        if qth:
            payload_record["APP_EQSL_QTH_NICKNAME"] = qth
        response = self.client.post(urljoin(self.base_url, "ImportADIF.cfm"), data={"ADIFData": record_to_adif(payload_record)})
        response.raise_for_status()
        body = re.sub(r"<[^>]+>", " ", html.unescape(response.text))
        clean = re.sub(r"\s+", " ", body).strip()
        if "0 out of" in clean.lower() or "error" in clean.lower():
            raise CloudProviderError(clean[:500])
        return {"ok": True, "message": clean[:500]}


PROVIDERS = {
    "QRZ": QRZCloudAdapter,
    "WRL": WRLCloudAdapter,
    "CLUBLOG": ClubLogCloudAdapter,
    "EQSL": EQSLCloudAdapter,
}


def adapter_for(provider: str, credentials: Dict[str, Any], client: Optional[httpx.Client] = None) -> CloudLogAdapter:
    name = provider.strip().upper()
    cls = PROVIDERS.get(name)
    if not cls:
        raise CloudProviderError(f"Unsupported provider: {provider}")
    return cls(credentials, client=client)
