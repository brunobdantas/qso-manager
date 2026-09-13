from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

from app.adapters.cloud_logs import CloudProviderError
from app.adapters.qrz_cloud_v501 import QRZCloudAdapterV501
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.eqsl_qrz_sync_service import EqslQrzSyncService


def qrz(
    call: str,
    time_on: str,
    logid: str,
    *,
    date: str = "2026-09-13",
    band: str = "15M",
    mode: str = "FT8",
    received: str = "N",
    received_date: str = "",
    status: str = "N",
    lotw_received: str = "N",
    lotw_date: str = "",
    contest: str = "",
):
    row = {
        "CALL": call,
        "QSO_DATE": date,
        "TIME_ON": time_on,
        "BAND": band,
        "MODE": mode,
        "APP_QRZLOG_LOGID": logid,
        "EQSL_QSL_RCVD": received,
        "APP_QRZLOG_STATUS": status,
        "LOTW_QSL_RCVD": lotw_received,
    }
    if received_date:
        row["EQSL_QSLRDATE"] = received_date
    if lotw_date:
        row["LOTW_QSLRDATE"] = lotw_date
    if contest:
        row["CONTEST_ID"] = contest
    return row


def eqsl(
    call: str,
    time_on: str,
    received_date: str | None,
    *,
    date: str = "2026-09-13",
    band: str = "15M",
    mode: str = "FT8",
):
    row = {
        "CALL": call,
        "QSO_DATE": date,
        "TIME_ON": time_on,
        "BAND": band,
        "MODE": mode,
        "EQSL_QSL_RCVD": "Y",
    }
    if received_date:
        row["EQSL_QSLRDATE"] = received_date
    return row


def adif_record(record):
    parts = []
    for key, value in record.items():
        if value in (None, ""):
            continue
        text = str(value).replace("-", "") if key == "QSO_DATE" else str(value).replace(":", "") if key == "TIME_ON" else str(value)
        parts.append(f"<{key}:{len(text)}>{text}")
    return "".join(parts) + "<EOR>"


def build_service(tmp_path: Path, qrz_rows, eqsl_rows, adapter_factory=None):
    credentials = CredentialStore(root=tmp_path / "credentials")
    credentials.set("QRZ", {"api_key": "test-key"})
    snapshots = CloudSnapshotStore(root=tmp_path / "snapshots")
    snapshots.save("QRZ", qrz_rows, {"coverage": "API_FULL_SYNC"})
    snapshots.save("EQSL_INBOX", eqsl_rows, {"coverage": "API_FULL_SYNC", "confirmations_only": True})
    return EqslQrzSyncService(
        credentials=credentials,
        snapshots=snapshots,
        adapter_factory=adapter_factory,
    )


def test_plan_is_strict_one_to_one_and_separates_manual_cases(tmp_path: Path):
    qrz_rows = [
        qrz("K1NEW", "12:00:00", "101"),
        qrz("K1DATE", "13:00:00", "102", received="Y", received_date="20260101"),
        qrz("K1OK", "13:30:00", "103", received="Y", received_date="20260913"),
        qrz("K1COL", "14:00:00", "104"),
        qrz("K1COL", "14:01:00", "105"),
        qrz("K1REVIEW", "15:00:00", "106"),
        qrz("K1NODATE", "16:00:00", "107"),
    ]
    eqsl_rows = [
        eqsl("K1NEW", "12:01:00", "20260913"),
        eqsl("K1DATE", "13:00:00", "20260913"),
        eqsl("K1OK", "13:30:00", "20260913"),
        eqsl("K1COL", "14:00:30", "20260913"),
        eqsl("K1REVIEW", "15:03:00", "20260913"),
        eqsl("K1NODATE", "16:00:00", None),
    ]
    service = build_service(tmp_path, qrz_rows, eqsl_rows)

    plan = service.plan()

    assert plan["summary"]["safe_updates"] == 2
    assert plan["summary"]["new_confirmations"] == 1
    assert plan["summary"]["date_alignments"] == 1
    assert plan["summary"]["already_aligned"] == 1
    assert plan["summary"]["collisions"] >= 1
    assert plan["summary"]["manual_review"] == 1
    assert plan["summary"]["missing_explicit_date"] == 1

    by_call = {row["call"]: row for row in plan["candidates"]}
    assert by_call["K1NEW"]["kind"] == "NEW_CONFIRMATION"
    assert by_call["K1NEW"]["delta_seconds"] == 60
    assert by_call["K1NEW"]["target_date"] == "20260913"
    assert by_call["K1DATE"]["kind"] == "ALIGN_DATE"
    assert by_call["K1DATE"]["current_date"] == "20260101"

    assert {row["call"] for row in plan["manual_review"]} == {"K1REVIEW"}
    assert all(row["call"] != "K1COL" for row in plan["candidates"])
    assert all(row["call"] != "K1NODATE" for row in plan["candidates"])


def test_plan_collapses_exact_duplicate_cards_with_same_receive_date(tmp_path: Path):
    qrz_rows = [qrz("K2DUP", "12:00:00", "201")]
    eqsl_rows = [
        eqsl("K2DUP", "12:00:30", "20260913"),
        eqsl("K2DUP", "12:00:30", "20260913"),
    ]
    service = build_service(tmp_path, qrz_rows, eqsl_rows)

    plan = service.plan()

    assert plan["summary"]["safe_updates"] == 1
    assert plan["candidates"][0]["evidence_duplicates_collapsed"] == 2
    assert plan["summary"]["date_conflicts"] == 0


def test_plan_blocks_duplicate_card_identity_with_conflicting_receive_dates(tmp_path: Path):
    qrz_rows = [qrz("K3DATE", "12:00:00", "301")]
    eqsl_rows = [
        eqsl("K3DATE", "12:00:00", "20260912"),
        eqsl("K3DATE", "12:00:00", "20260913"),
    ]
    service = build_service(tmp_path, qrz_rows, eqsl_rows)

    plan = service.plan()

    assert plan["summary"]["safe_updates"] == 0
    assert plan["summary"]["date_conflicts"] == 1


def test_qrz_exact_replace_preserves_raw_protected_fields_and_uses_proven_fetch_option():
    initial = (
        "<CALL:5>K1ABC<QSO_DATE:8>20260913<TIME_ON:6>120000"
        "<BAND:3>15M<FREQ:6>21.074<MODE:3>FT8<RST_SENT:3>+06"
        "<CONTEST_ID:7>WW-DIGI<LOTW_QSL_RCVD:1>Y<LOTW_QSLRDATE:8>20260912"
        "<EQSL_QSL_RCVD:1>N<COMMENT:11>keep me 123"
        "<APP_QRZLOG_LOGID:3>123<EOR>"
    )
    current = {"adif": initial}
    seen_fetch_options = []
    seen_insert_payloads = []

    def handler(request):
        form = parse_qs(request.content.decode(), keep_blank_values=True)
        action = form["ACTION"][0]
        if action == "FETCH":
            option = form.get("OPTION", [""])[0]
            seen_fetch_options.append(option)
            assert option == "LOGIDS:123,TYPE:ADIF"
            return httpx.Response(200, text=urlencode({"RESULT": "OK", "COUNT": "1", "ADIF": current["adif"]}))
        if action == "INSERT":
            assert form.get("OPTION") == ["REPLACE"]
            payload = form["ADIF"][0]
            seen_insert_payloads.append(payload)
            assert "APP_QRZLOG_LOGID" not in payload
            assert "<CONTEST_ID:7>WW-DIGI" in payload
            assert "<LOTW_QSL_RCVD:1>Y" in payload
            assert "<LOTW_QSLRDATE:8>20260912" in payload
            assert "<COMMENT:11>keep me 123" in payload
            assert "<RST_SENT:3>+06" in payload
            assert "<EQSL_QSL_RCVD:1>Y" in payload
            assert "<EQSL_QSLRDATE:8>20260913" in payload
            current["adif"] = payload.replace(
                "<EOR>",
                "<APP_QRZLOG_LOGID:3>123<EOR>",
            )
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGID=123")
        raise AssertionError(action)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = QRZCloudAdapterV501({"api_key": "test"}, client=client)

    result = adapter.replace_exact_fields(
        "123",
        {"EQSL_QSL_RCVD": "Y", "EQSL_QSLRDATE": "20260913"},
        protected_fields=("CONTEST_ID", "LOTW_QSL_RCVD", "LOTW_QSLRDATE", "COMMENT"),
        expected_fields={
            "EQSL_QSL_RCVD": "N",
            "EQSL_QSLRDATE": None,
            "CONTEST_ID": "WW-DIGI",
            "LOTW_QSL_RCVD": "Y",
        },
    )

    assert result["ok"] is True
    assert len(seen_fetch_options) == 2
    assert len(seen_insert_payloads) == 1
    assert result["after"]["CONTEST_ID"] == "WW-DIGI"
    assert result["after"]["LOTW_QSL_RCVD"] == "Y"
    assert result["after"]["EQSL_QSL_RCVD"] == "Y"
    assert result["after"]["EQSL_QSLRDATE"] == "20260913"


def test_qrz_exact_replace_fails_closed_if_live_precondition_changed():
    raw = (
        "<CALL:5>K1ABC<QSO_DATE:8>20260913<TIME_ON:6>120000"
        "<BAND:3>15M<MODE:3>FT8<EQSL_QSL_RCVD:1>Y"
        "<APP_QRZLOG_LOGID:3>123<EOR>"
    )
    inserts = []

    def handler(request):
        form = parse_qs(request.content.decode(), keep_blank_values=True)
        if form["ACTION"][0] == "FETCH":
            return httpx.Response(200, text=urlencode({"RESULT": "OK", "COUNT": "1", "ADIF": raw}))
        inserts.append(form)
        return httpx.Response(200, text="RESULT=OK&LOGID=123")

    adapter = QRZCloudAdapterV501(
        {"api_key": "test"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudProviderError, match="changed before REPLACE"):
        adapter.replace_exact_fields(
            "123",
            {"EQSL_QSL_RCVD": "Y", "EQSL_QSLRDATE": "20260913"},
            expected_fields={"EQSL_QSL_RCVD": "N"},
        )

    assert inserts == []


def test_qrz_exact_replace_detects_protected_field_regression():
    initial = (
        "<CALL:5>K1ABC<QSO_DATE:8>20260913<TIME_ON:6>120000"
        "<BAND:3>15M<MODE:3>FT8<CONTEST_ID:7>WW-DIGI"
        "<EQSL_QSL_RCVD:1>N<APP_QRZLOG_LOGID:3>123<EOR>"
    )
    current = {"adif": initial}

    def handler(request):
        form = parse_qs(request.content.decode(), keep_blank_values=True)
        if form["ACTION"][0] == "FETCH":
            return httpx.Response(200, text=urlencode({"RESULT": "OK", "COUNT": "1", "ADIF": current["adif"]}))
        payload = form["ADIF"][0]
        # Simulate a remote-side regression: CONTEST_ID disappears after REPLACE.
        payload = payload.replace("<CONTEST_ID:7>WW-DIGI", "")
        current["adif"] = payload.replace("<EOR>", "<APP_QRZLOG_LOGID:3>123<EOR>")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGID=123")

    adapter = QRZCloudAdapterV501(
        {"api_key": "test"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudProviderError, match="protected fields"):
        adapter.replace_exact_fields(
            "123",
            {"EQSL_QSL_RCVD": "Y", "EQSL_QSLRDATE": "20260913"},
            protected_fields=("CONTEST_ID",),
        )


class FakeQRZAdapter:
    def __init__(self, records):
        self.records = {str(row["APP_QRZLOG_LOGID"]): deepcopy(row) for row in records}
        self.replace_order = []
        self.closed = False

    def _raw(self, record):
        return adif_record(record)

    def fetch_exact(self, logid):
        record = deepcopy(self.records[str(logid)])
        return {"logid": str(logid), "record": record, "raw_adif": self._raw(record)}

    def replace_exact_fields(self, logid, changes, protected_fields=(), expected_fields=None):
        key = str(logid)
        before = deepcopy(self.records[key])
        for name, expected in dict(expected_fields or {}).items():
            actual = before.get(name)
            if str(actual or "").strip().upper() != str(expected or "").strip().upper():
                raise CloudProviderError(f"precondition changed: {name}")
        protected_before = {name: before.get(name) for name in protected_fields}
        after = deepcopy(before)
        after.update(changes)
        assert {name: after.get(name) for name in protected_fields} == protected_before
        self.records[key] = after
        self.replace_order.append(key)
        return {
            "ok": True,
            "logid_before": key,
            "logid_after": key,
            "before": before,
            "after": deepcopy(after),
            "changes": dict(changes),
        }

    def fetch_all(self):
        return {
            "records": [deepcopy(row) for row in self.records.values()],
            "metadata": {"coverage": "API_FULL_SYNC", "strategy": "FAKE_FULL"},
        }

    def close(self):
        self.closed = True


def test_apply_preflights_backs_up_uses_canary_and_resyncs_snapshot(tmp_path: Path):
    qrz_rows = [
        qrz(
            "K1CONF",
            "12:00:00",
            "501",
            status="C",
            lotw_received="Y",
            lotw_date="20260912",
            contest="WW-DIGI",
        ),
        qrz("K1CAN", "13:00:00", "502", status="N", lotw_received="N"),
    ]
    eqsl_rows = [
        eqsl("K1CONF", "12:00:30", "20260913"),
        eqsl("K1CAN", "13:00:30", "20260913"),
    ]
    fake = FakeQRZAdapter(qrz_rows)
    service = build_service(tmp_path, qrz_rows, eqsl_rows, adapter_factory=lambda _creds: fake)

    result = service.apply(confirm=True)

    assert result["ok"] is True
    assert result["updated"] == 2
    assert result["skipped"] == 0
    assert result["full_resync"] is True
    assert Path(result["backup"]).exists()
    assert Path(result["live_backup"]).exists()

    # Canary is deliberately the status N / non-LoTW QSO even though it was second in the plan.
    assert fake.replace_order[0] == "502"
    assert fake.records["501"]["CONTEST_ID"] == "WW-DIGI"
    assert fake.records["501"]["LOTW_QSL_RCVD"] == "Y"
    assert fake.records["501"]["LOTW_QSLRDATE"] == "20260912"
    assert fake.records["501"]["EQSL_QSL_RCVD"] == "Y"
    assert fake.records["501"]["EQSL_QSLRDATE"] == "20260913"

    saved = service.snapshots.load("QRZ")["records"]
    saved_by_id = {str(row["APP_QRZLOG_LOGID"]): row for row in saved}
    assert saved_by_id["501"]["CONTEST_ID"] == "WW-DIGI"
    assert saved_by_id["502"]["EQSL_QSLRDATE"] == "20260913"
    assert fake.closed is True


def test_apply_is_dry_run_by_default(tmp_path: Path):
    qrz_rows = [qrz("K1DRY", "12:00:00", "601")]
    eqsl_rows = [eqsl("K1DRY", "12:00:30", "20260913")]
    fake = FakeQRZAdapter(qrz_rows)
    service = build_service(tmp_path, qrz_rows, eqsl_rows, adapter_factory=lambda _creds: fake)

    result = service.apply()

    assert result["dry_run"] is True
    assert result["attempted"] == 1
    assert fake.replace_order == []
