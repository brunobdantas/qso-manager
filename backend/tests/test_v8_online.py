from pathlib import Path

from app.adapters.online_v8 import HRDLogCloudAdapter
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.v8_online_service import V8OnlineService


class FakeResponse:
    status_code = 200
    text = "<result><insert>1</insert><id>123</id></result>"

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_hrdlog_realtime_payload_uses_documented_fields():
    client = FakeClient()
    adapter = HRDLogCloudAdapter(
        {"callsign": "PU2BRU", "upload_code": "secret"},
        client=client,
    )
    result = adapter.add_qso({
        "CALL": "K1ABC",
        "QSO_DATE": "2026-09-10",
        "TIME_ON": "21:12:00",
        "BAND": "20M",
        "FREQ": "14.074",
        "MODE": "FT8",
    })
    assert result["ok"] is True
    assert result["status"] == "inserted"
    url, kwargs = client.calls[0]
    assert url == "https://robot.hrdlog.net/NewEntry.aspx"
    assert kwargs["data"]["Callsign"] == "PU2BRU"
    assert kwargs["data"]["Code"] == "secret"
    assert "<CALL:5>K1ABC" in kwargs["data"]["ADIFData"]
    assert kwargs["data"]["ADIFData"].endswith("<EOR>")


def test_hrdlog_bootstrap_and_safe_missing_plan(tmp_path: Path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    credentials = CredentialStore(root=tmp_path)
    service = V8OnlineService(credentials=credentials, snapshots=snapshots)

    snapshots.save("QRZ", [
        {"CALL": "K1ABC", "QSO_DATE": "2026-09-10", "TIME_ON": "211200", "BAND": "20M", "FREQ": "14.074", "MODE": "FT8"},
        {"CALL": "EA1XYZ", "QSO_DATE": "2026-09-10", "TIME_ON": "212000", "BAND": "20M", "FREQ": "14.074", "MODE": "FT8"},
    ], {"coverage": "API_FULL_SYNC"})

    service.import_hrdlog_adif(
        "<ADIF_VER:5>3.1.4<EOH>"
        "<CALL:5>K1ABC<QSO_DATE:8>20260910<TIME_ON:6>211200<BAND:3>20M<FREQ:6>14.074<MODE:3>FT8<EOR>",
        "hrdlog-full.adi",
    )
    plan = service.hrdlog_plan()
    assert plan["known_hrdlog_records"] == 1
    assert plan["safe_missing"] == 1
    assert plan["candidates"][0]["call"] == "EA1XYZ"


def test_v8_qsl_analysis_uses_online_confirmation_snapshots(tmp_path: Path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    credentials = CredentialStore(root=tmp_path)
    service = V8OnlineService(credentials=credentials, snapshots=snapshots)

    snapshots.save("QRZ", [{
        "CALL": "OK1AR",
        "QSO_DATE": "2026-09-08",
        "TIME_ON": "123900",
        "BAND": "20M",
        "MODE": "FT8",
    }], {"coverage": "API_FULL_SYNC"})
    snapshots.save("LOTW", [{
        "CALL": "OK1AR",
        "QSO_DATE": "2026-09-08",
        "TIME_ON": "123900",
        "BAND": "20M",
        "MODE": "FT8",
        "QSL_RCVD": "Y",
        "QSLRDATE": "2026-09-10",
        "LOTW_QSL_RCVD": "Y",
        "LOTW_QSLRDATE": "2026-09-10",
    }], {"coverage": "API_FULL_SYNC", "confirmations_only": True})

    result = service.qsl_analysis()
    assert result["ready"] is True
    assert result["summary"]["actionable_proposals"] == 1
    proposal = result["proposals"][0]
    assert proposal["service"] == "LOTW"
    assert proposal["changes"]["LOTW_QSL_RCVD"] == "Y"
    assert proposal["changes"]["LOTW_QSLRDATE"] == "2026-09-10"


def test_mobile_policy_excludes_local_hrd(tmp_path: Path):
    service = V8OnlineService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=CloudSnapshotStore(root=tmp_path),
    )
    status = service.status()
    assert status["mobile_policy"] == "online_only"
    assert status["hrd_local_in_mobile"] is False
    assert "HRD" not in [p["provider"] for p in status["providers"]]
    assert "HRDLOG" in [p["provider"] for p in status["providers"]]
