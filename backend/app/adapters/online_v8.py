"""Online-only provider adapters introduced by QSO Manager v8."""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from .cloud_logs import CloudLogAdapter, CloudProviderError, record_to_adif
from ..adif.parser import ADIFParser
from ..core.version import __version__


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
                "User-Agent": f"PU2BRU-QSO-Manager/{__version__}",
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
    """Read the complete LoTW log and keep confirmations incrementally updated.

    Initial synchronization downloads accepted QSOs (qso_qsl=no), including
    current QSL status/detail. Later synchronizations use both LoTW cursors:
    new/updated accepted QSOs since APP_LoTW_LASTQSORX and new/updated QSLs
    since APP_LoTW_LASTQSL. The resulting snapshot remains a complete local
    LoTW log rather than a confirmation-only feed.
    """

    provider = "LOTW"
    endpoint = "https://lotw.arrl.org/lotwuser/lotwreport.adi"
    capabilities = {"read": True, "add": False, "update": False, "delete": False}
    USER_AGENT = f"PU2BRU-QSO-Manager/{__version__} (LoTW read-only)"
    TEST_TIMEOUT = httpx.Timeout(15.0, connect=8.0)
    SYNC_TIMEOUT = httpx.Timeout(240.0, connect=12.0)
    FULL_SYNC_SINCE = "1945-11-15"
    CURSOR_OVERLAP_SECONDS = 600

    def _required(self) -> Dict[str, str]:
        login = str(self.credentials.get("login") or self.credentials.get("username") or "").strip()
        password = str(self.credentials.get("password") or "").strip()
        if not login or not password:
            raise CloudProviderError("LoTW exige o username da conta e a senha")
        return {"login": login, "password": password}

    @staticmethod
    def _clean_error(body: str) -> str:
        clean = re.sub(r"<[^>]+>", " ", html.unescape(body or ""))
        return re.sub(r"\s+", " ", clean).strip()

    @staticmethod
    def _looks_like_auth_error(clean: str) -> bool:
        lower = clean.lower()
        markers = (
            "username/password incorrect",
            "username / password incorrect",
            "incorrect password",
            "invalid password",
            "login failed",
            "logon failed",
            "authentication failed",
        )
        return any(marker in lower for marker in markers)

    @staticmethod
    def _header_fields(body: str) -> Dict[str, str]:
        upper = body.upper()
        eoh = upper.find("<EOH>")
        header = body[:eoh] if eoh >= 0 else body[:4000]
        fields: Dict[str, str] = {}
        pos = 0
        while pos < len(header):
            open_pos = header.find("<", pos)
            if open_pos < 0:
                break
            close_pos = header.find(">", open_pos + 1)
            if close_pos < 0:
                break
            tag = header[open_pos + 1:close_pos]
            match = re.match(r"^([A-Z0-9_]+):(\d+)(?::[A-Z])?$", tag, re.I)
            if not match:
                pos = close_pos + 1
                continue
            name = match.group(1).upper()
            length = int(match.group(2))
            value_start = close_pos + 1
            value = header[value_start:value_start + length]
            fields[name] = value.strip()
            pos = value_start + length
        return fields

    @staticmethod
    def _compact_date(value: Any) -> str:
        return str(value or "").replace("-", "").strip()

    @staticmethod
    def _compact_time(value: Any) -> str:
        return str(value or "").replace(":", "").strip()[:6]

    @staticmethod
    def _canonical_mode(record: Dict[str, Any]) -> str:
        return str(record.get("SUBMODE") or record.get("APP_LOTW_MODE") or record.get("MODE") or "").upper().strip()

    @classmethod
    def _base_key(cls, record: Dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            str(record.get("CALL") or "").upper().strip(),
            cls._compact_date(record.get("QSO_DATE")),
            cls._compact_time(record.get("TIME_ON")),
            str(record.get("BAND") or "").upper().strip(),
            str(record.get("STATION_CALLSIGN") or record.get("APP_LOTW_OWNCALL") or "").upper().strip(),
        )

    @classmethod
    def _records_match(cls, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        if cls._base_key(left) != cls._base_key(right):
            return False
        left_mode, right_mode = cls._canonical_mode(left), cls._canonical_mode(right)
        if left_mode and right_mode and left_mode != right_mode:
            return False
        lf, rf = left.get("FREQ"), right.get("FREQ")
        if lf not in (None, "") and rf not in (None, ""):
            try:
                if abs(float(lf) - float(rf)) > 0.020:
                    return False
            except (TypeError, ValueError):
                pass
        return True

    @staticmethod
    def _mark_confirmation(record: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(record)
        row["APP_QSOMGR_LOTW_ACCEPTED"] = "Y"
        if str(row.get("QSL_RCVD") or "").upper() == "Y":
            row["LOTW_QSL_RCVD"] = "Y"
            if row.get("QSLRDATE"):
                row["LOTW_QSLRDATE"] = row.get("QSLRDATE")
        return row

    @staticmethod
    def _merge_qsl_into_qso(qso: Dict[str, Any], qsl: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(qso)
        identity = {
            "CALL", "QSO_DATE", "TIME_ON", "TIME_OFF", "BAND", "BAND_RX",
            "FREQ", "FREQ_RX", "MODE", "SUBMODE", "APP_LOTW_MODE",
            "STATION_CALLSIGN", "APP_LOTW_OWNCALL",
        }
        for key, value in qsl.items():
            if value in (None, ""):
                continue
            if key in identity and result.get(key) not in (None, ""):
                continue
            result[key] = value
        if str(qsl.get("QSL_RCVD") or "").upper() == "Y":
            result["QSL_RCVD"] = "Y"
            result["LOTW_QSL_RCVD"] = "Y"
            if qsl.get("QSLRDATE"):
                result["QSLRDATE"] = qsl["QSLRDATE"]
                result["LOTW_QSLRDATE"] = qsl["QSLRDATE"]
        result["APP_QSOMGR_LOTW_ACCEPTED"] = "Y"
        return result

    @classmethod
    def _merge_records(
        cls,
        base_records: List[Dict[str, Any]],
        incoming_records: List[Dict[str, Any]],
        *,
        qsl_overlay: bool,
    ) -> tuple[List[Dict[str, Any]], int, int]:
        rows = [dict(r) for r in base_records]
        index: Dict[tuple[str, str, str, str, str], List[int]] = {}
        for i, row in enumerate(rows):
            index.setdefault(cls._base_key(row), []).append(i)

        merged = 0
        appended = 0
        for incoming in incoming_records:
            row = cls._mark_confirmation(incoming)
            candidates = index.get(cls._base_key(row), [])
            exact = [i for i in candidates if cls._records_match(rows[i], row)]
            target: Optional[int] = exact[0] if len(exact) == 1 else None
            if target is None and len(candidates) == 1:
                # LoTW may map a submitted mode before returning it. If the
                # call/date/time/band/station tuple is unique, preserve the
                # QSO identity from the accepted-QSO record and overlay status.
                target = candidates[0]

            if target is not None:
                rows[target] = (
                    cls._merge_qsl_into_qso(rows[target], row)
                    if qsl_overlay
                    else cls._merge_qsl_into_qso(row, rows[target])
                )
                merged += 1
                continue

            if qsl_overlay:
                row["APP_QSOMGR_LOTW_QSL_ONLY"] = "Y"
            rows.append(row)
            index.setdefault(cls._base_key(row), []).append(len(rows) - 1)
            appended += 1
        return rows, merged, appended

    def _download(
        self,
        *,
        qsl: bool,
        since: Optional[str] = None,
        timeout: Optional[httpx.Timeout] = None,
    ) -> str:
        auth = self._required()
        params = {
            **auth,
            "qso_query": "1",
            "qso_qsl": "yes" if qsl else "no",
            "qso_qsldetail": "yes",
            "qso_mydetail": "yes",
            "qso_withown": "yes",
        }
        if since:
            params["qso_qslsince" if qsl else "qso_qsorxsince"] = since
        try:
            response = self.client.get(
                self.endpoint,
                params=params,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "text/plain,text/html;q=0.8,*/*;q=0.5",
                },
                timeout=timeout or self.SYNC_TIMEOUT,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise CloudProviderError(
                "LoTW não respondeu dentro do tempo esperado. "
                "Tente novamente; se persistir, verifique se o site do LoTW está acessível no navegador."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise CloudProviderError(f"LoTW retornou HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise CloudProviderError(
                "Não foi possível alcançar o serviço do LoTW. Verifique a conexão e tente novamente."
            ) from exc

        body = response.text or ""
        if "<EOH>" not in body.upper():
            clean = self._clean_error(body)
            if self._looks_like_auth_error(clean):
                raise CloudProviderError(
                    "LoTW recusou o username/senha. Use o username da conta LoTW "
                    "(nem sempre ele é igual ao indicativo)."
                )
            raise CloudProviderError(
                "LoTW respondeu, mas não devolveu ADIF"
                + (f": {clean[:300]}" if clean else "")
            )
        return body

    @classmethod
    def _parse_report(cls, body: str) -> tuple[List[Dict[str, Any]], List[str], Dict[str, str]]:
        records, errors = ADIFParser().parse(body)
        return [cls._mark_confirmation(r) for r in records], errors, cls._header_fields(body)

    @staticmethod
    def _max_timestamp(records: List[Dict[str, Any]], field: str) -> Optional[str]:
        values = [str(r.get(field) or "").strip() for r in records if r.get(field)]
        return max(values) if values else None

    def test_connection(self) -> Dict[str, Any]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        body = self._download(qsl=True, since=today, timeout=self.TEST_TIMEOUT)
        records, errors, _header = self._parse_report(body)
        return {
            "ok": True,
            "records": len(records),
            "parse_errors": errors[:3],
            "message": "Credenciais LoTW validadas. A sincronização completa é feita separadamente.",
        }

    def fetch_all(self) -> Dict[str, Any]:
        """Initial full snapshot: every accepted QSO, with current QSL detail."""
        started = datetime.now(timezone.utc)
        body = self._download(qsl=False, since=self.FULL_SYNC_SINCE, timeout=self.SYNC_TIMEOUT)
        records, errors, header = self._parse_report(body)

        last_qso = (
            header.get("APP_LOTW_LASTQSORX")
            or self._max_timestamp(records, "APP_LOTW_RXQSO")
        )
        last_qsl = self._max_timestamp(records, "APP_LOTW_RXQSL")
        if not last_qsl:
            # Keep a safe overlap so a QSL arriving while the full query was in
            # flight is picked up by the next incremental refresh.
            from datetime import timedelta
            last_qsl = (started - timedelta(seconds=self.CURSOR_OVERLAP_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")

        confirmed = sum(1 for r in records if str(r.get("QSL_RCVD") or "").upper() == "Y")
        return {
            "records": records,
            "metadata": {
                "coverage": "API_FULL_SYNC",
                "source": "lotw_qso_qsl_api",
                "confirmations_only": False,
                "incremental": False,
                "parse_errors": errors[:20],
                "lotw_last_qso_rx": last_qso,
                "lotw_last_qsl": last_qsl,
                "accepted_qsos": len(records),
                "confirmed_qsos": confirmed,
                "delta_qso_records": len(records),
                "delta_qsl_records": 0,
                "lotw_numrec": header.get("APP_LOTW_NUMREC"),
            },
        }

    def fetch_incremental(self, previous_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh a complete snapshot using LoTW's QSO and QSL cursors."""
        previous_records = list(previous_snapshot.get("records") or [])
        metadata = dict(previous_snapshot.get("metadata") or {})
        # Older QSO Manager releases stored only QSL records. Force one
        # complete migration before incremental updates are enabled.
        if (
            not previous_records
            or metadata.get("confirmations_only") is True
            or not metadata.get("lotw_last_qso_rx")
            or not metadata.get("lotw_last_qsl")
        ):
            result = self.fetch_all()
            result["metadata"]["migration_from_confirmation_only"] = bool(previous_records)
            return result

        # QSO acceptance and QSL confirmation deltas are independent.
        # Fetch both concurrently so the refresh duration is bounded by the
        # slower LoTW query rather than the sum of the two.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="lotw-delta") as executor:
            qso_future = executor.submit(
                self._download,
                qsl=False,
                since=str(metadata["lotw_last_qso_rx"]),
                timeout=self.SYNC_TIMEOUT,
            )
            qsl_future = executor.submit(
                self._download,
                qsl=True,
                since=str(metadata["lotw_last_qsl"]),
                timeout=self.SYNC_TIMEOUT,
            )
            qso_body = qso_future.result()
            qsl_body = qsl_future.result()
        qso_delta, qso_errors, qso_header = self._parse_report(qso_body)
        qsl_delta, qsl_errors, qsl_header = self._parse_report(qsl_body)

        rows, qso_merged, qso_appended = self._merge_records(
            previous_records, qso_delta, qsl_overlay=False
        )
        rows, qsl_merged, qsl_appended = self._merge_records(
            rows, qsl_delta, qsl_overlay=True
        )

        last_qso = (
            qso_header.get("APP_LOTW_LASTQSORX")
            or self._max_timestamp(qso_delta, "APP_LOTW_RXQSO")
            or metadata.get("lotw_last_qso_rx")
        )
        last_qsl = (
            qsl_header.get("APP_LOTW_LASTQSL")
            or self._max_timestamp(qsl_delta, "APP_LOTW_RXQSL")
            or metadata.get("lotw_last_qsl")
        )
        confirmed = sum(1 for r in rows if str(r.get("QSL_RCVD") or "").upper() == "Y")
        return {
            "records": rows,
            "metadata": {
                **metadata,
                "coverage": "API_FULL_SYNC",
                "source": "lotw_qso_qsl_api",
                "confirmations_only": False,
                "incremental": True,
                "parse_errors": (qso_errors + qsl_errors)[:20],
                "lotw_last_qso_rx": last_qso,
                "lotw_last_qsl": last_qsl,
                "accepted_qsos": len(rows),
                "confirmed_qsos": confirmed,
                "delta_qso_records": len(qso_delta),
                "delta_qsl_records": len(qsl_delta),
                "delta_qso_merged": qso_merged,
                "delta_qso_appended": qso_appended,
                "delta_qsl_merged": qsl_merged,
                "delta_qsl_appended": qsl_appended,
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
    USER_AGENT = f"PU2BRU-QSO-Manager/{__version__} (PU2BRU)"

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
