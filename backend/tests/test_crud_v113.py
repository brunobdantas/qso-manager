"""v1.1.3 provider CRUD contracts and destructive-write guardrails."""
from pathlib import Path
from urllib.parse import parse_qs, quote_plus

import httpx
import pytest

from app.adapters.cloud_logs import (
    ClubLogCloudAdapter,
    CloudProviderError,
    EQSLCloudAdapter,
    WRLCloudAdapter,
)
from app.adapters.hrdlog import HRDLogCloudAdapter
from app.adapters.online_v8 import LoTWConfirmationAdapter
from app.adapters.qrz_cloud_v501 import QRZCloudAdapterV501
from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.qso_manager_workspace import QSOManagerWorkspace


def _form(request: httpx.Request):
    return {key: values[-1] for key, values in parse_qs(request.content.decode()).items()}


def _qso(**extra):
    return {
        "CALL": "K1ABC", "QSO_DATE": "2026-11-10", "TIME_ON": "12:34:56",
        "BAND": "20M", "FREQ": "14.074", "MODE": "FT8",
        "STATION_CALLSIGN": "PU2BRU", **extra,
    }


def test_wrl_uses_openapi_iso_timestamp_and_full_crud_routes():
    seen = []

    def handler(request):
        body = request.read()
        seen.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "contact-1"}, "meta": {}, "error": None})
        if request.method == "PATCH":
            return httpx.Response(200, json={"data": {"id": "contact-1"}, "meta": {}, "error": None})
        return httpx.Response(204)

    adapter = WRLCloudAdapter(
        {"api_key": "secret", "callsign": "PU2BRU"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    created = adapter.add_qso(_qso())
    adapter.update_qso("contact-1", {"COMMENT": "corrigido"}, record=_qso())
    adapter.delete_qso("contact-1", record=_qso())

    assert created["external_id"] == "contact-1"
    post_json = __import__("json").loads(seen[0][2])
    assert post_json["timestamp"] == "2026-11-10T12:34:56Z"
    assert post_json["stationCallsign"] == "PU2BRU"
    assert [(method, path) for method, path, _ in seen] == [
        ("POST", "/v1/contacts"),
        ("PATCH", "/v1/contacts/contact-1"),
        ("DELETE", "/v1/contacts/contact-1"),
    ]


def test_hrdlog_official_adif_key_update_and_delete_protocol():
    seen = []

    def handler(request):
        form = _form(request)
        seen.append(form)
        tag = str(form.get("Cmd") or "INSERT").lower()
        return httpx.Response(
            200,
            text=f'<r xmlns="http://xml.hrdlog.com"><NewEntry><{tag}>1</{tag}></NewEntry></r>',
        )

    adapter = HRDLogCloudAdapter(
        {"callsign": "PU2BRU", "upload_code": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert adapter.add_qso(_qso())["status"] == "inserted"
    assert adapter.update_qso("", {"COMMENT": "novo"}, record=_qso(COMMENT="antigo"))["status"] == "updated"
    assert adapter.delete_qso("", record=_qso())["status"] == "deleted"

    assert "Cmd" not in seen[0]
    assert seen[1]["Cmd"] == "UPDATE"
    assert seen[2]["Cmd"] == "DELETE"
    for form in seen[1:]:
        assert "<CALL:5>K1ABC" in form["ADIFKey"]
        assert "<QSO_DATE:8>20261110" in form["ADIFKey"]
        assert "<TIME_ON:6>123456" in form["ADIFKey"]
    assert "<COMMENT:4>novo" in seen[1]["ADIFData"]
    assert "ADIFData" not in seen[2]
    assert all(form["App"].startswith("PU2BRU-QSO-Manager/") for form in seen)


def test_hrdlog_zero_update_or_delete_is_not_false_success():
    def handler(request):
        tag = str(_form(request).get("Cmd") or "INSERT").lower()
        return httpx.Response(200, text=f"<result><{tag}>0</{tag}></result>")

    adapter = HRDLogCloudAdapter(
        {"callsign": "PU2BRU", "upload_code": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError, match="matched no QSO"):
        adapter.update_qso("", {"COMMENT": "x"}, record=_qso())
    with pytest.raises(CloudProviderError, match="matched no QSO"):
        adapter.delete_qso("", record=_qso())


def test_clublog_update_is_call_only_and_uses_qslcall():
    seen = []

    def handler(request):
        seen.append(_form(request))
        return httpx.Response(200, text="QSO Modified")

    adapter = ClubLogCloudAdapter(
        {"email": "bruno@example.com", "app_password": "secret", "callsign": "PU2BRU", "api_key": "api"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.update_qso("", {"CALL": "K1XYZ"}, record=_qso())
    assert result["status"] == "call_corrected"
    assert "<CALL:5>K1ABC" in seen[0]["adif"]
    assert "<QSLCALL:5>K1XYZ" in seen[0]["adif"]
    with pytest.raises(CloudProviderError, match="only CALL"):
        adapter.update_qso("", {"COMMENT": "not supported"}, record=_qso())
    assert len(seen) == 1


def test_qrz_safe_update_preserves_confirmation_fields_and_delete_uses_logid():
    requests = []
    current = {
        "adif": (
            "<CALL:5>K1ABC<QSO_DATE:8>20261110<TIME_ON:6>123456<BAND:3>20M"
            "<FREQ:6>14.074<MODE:3>FT8<STATION_CALLSIGN:6>PU2BRU"
            "<QSL_RCVD:1>Y<QSLRDATE:8>20261111<COMMENT:6>antigo"
            "<APP_QRZLOG_LOGID:3>123<EOR>"
        )
    }

    def handler(request):
        form = _form(request)
        requests.append(form)
        if form["ACTION"] == "FETCH":
            return httpx.Response(200, text="RESULT=OK&COUNT=1&ADIF=" + quote_plus(current["adif"]))
        if form["ACTION"] == "INSERT":
            current["adif"] = form["ADIF"]
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGID=123")
        if form["ACTION"] == "DELETE":
            return httpx.Response(200, text="RESULT=OK&COUNT=1")
        raise AssertionError(form)

    adapter = QRZCloudAdapterV501(
        {"api_key": "key"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    snapshot = _qso(QSL_RCVD="Y", QSLRDATE="2026-11-11", COMMENT="antigo")
    result = adapter.update_qso("123", {"COMMENT": "corrigido"}, record=snapshot)
    assert result["ok"] is True
    written = next(form["ADIF"] for form in requests if form["ACTION"] == "INSERT")
    assert "<COMMENT:9>corrigido" in written
    assert "<QSL_RCVD:1>Y" in written
    assert "<QSLRDATE:8>20261111" in written
    with pytest.raises(CloudProviderError, match="identity/confirmation"):
        adapter.update_qso("123", {"MODE": "FT4"}, record=snapshot)
    deleted = adapter.delete_qso("123", record={**snapshot, "COMMENT": "corrigido"})
    assert deleted["status"] == "deleted"
    assert requests[-1]["ACTION"] == "DELETE"
    assert requests[-1]["LOGIDS"] == "123"


def test_capability_matrix_is_honest_for_non_crud_providers():
    assert EQSLCloudAdapter.capabilities["read"] is True
    assert EQSLCloudAdapter.capabilities["add"] is True
    assert EQSLCloudAdapter.capabilities["update"] is False
    assert EQSLCloudAdapter.capabilities["delete"] is False
    assert LoTWConfirmationAdapter.capabilities == {
        "read": True, "add": False, "update": False, "delete": False,
    }


def test_hrdlog_confirmed_patches_update_snapshot_atomically(tmp_path: Path):
    hub = CloudHubService(
        credentials=CredentialStore(root=tmp_path / "credentials"),
        snapshots=CloudSnapshotStore(root=tmp_path / "data"),
    )
    hub.snapshots.save("HRDLOG", [_qso(CALL="K1ONE"), _qso(CALL="K1TWO")], {"coverage": "FULL_EXPORT"})
    result = hub.apply_snapshot_patches("HRDLOG", [
        {"op": "update", "index": 0, "changes": {"COMMENT": "ok"}},
        {"op": "delete", "index": 1},
        {"op": "append", "record": _qso(CALL="K1THREE")},
    ])
    records = hub.snapshots.load("HRDLOG")["records"]
    assert result["records"] == 2
    assert [row["CALL"] for row in records] == ["K1ONE", "K1THREE"]
    assert records[0]["COMMENT"] == "ok"
    assert records[1]["APP_QSOMANAGER_HRDLOG_STATUS"] == "managed_online"


def test_workspace_exposes_crud_matrix_and_enforces_fields_ids_and_batch_limits(tmp_path: Path):
    hub = CloudHubService(
        credentials=CredentialStore(root=tmp_path / "credentials"),
        snapshots=CloudSnapshotStore(root=tmp_path / "data"),
    )
    hub.snapshots.save("QRZ", [_qso(APP_QRZLOG_LOGID="123")], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    workspace = QSOManagerWorkspace(hub=hub)
    logical_id = workspace.ids()["ids"][0]
    options = workspace.options()

    assert options["capability_matrix"]["QRZ"]["update"] is True
    assert options["capability_matrix"]["HRDLOG"]["delete"] is True
    assert options["capability_matrix"]["EQSL"]["delete"] is False
    assert {"QRZ", "WRL", "CLUBLOG", "EQSL", "HRDLOG"}.issubset(options["write_targets"])
    assert workspace.plan_bulk("UPDATE", [logical_id], target="QRZ", changes={"COMMENT": "ok"})["actionable"] == 1
    blocked = workspace.plan_bulk("UPDATE", [logical_id], target="QRZ", changes={"MODE": "FT4"})
    assert blocked["actionable"] == 0
    assert blocked["sample"][0]["status"] == "unsupported_fields:MODE"
    assert workspace.plan_bulk("DELETE", [logical_id], target="QRZ")["actionable"] == 1

    club_rows = [
        _qso(CALL=f"K1{i:02d}X", TIME_ON=f"12:34:{i:02d}") for i in range(12)
    ]
    hub.snapshots.save("CLUBLOG", club_rows, {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    club_ids = QSOManagerWorkspace(hub=hub).ids(provider="CLUBLOG")["ids"]
    plan = QSOManagerWorkspace(hub=hub).plan_bulk("DELETE", club_ids, target="CLUBLOG")
    assert plan["actionable"] == 10
    assert plan["unsupported"] == 2
    assert plan["max_batch"] == 10
