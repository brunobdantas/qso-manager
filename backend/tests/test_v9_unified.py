from pathlib import Path

from app.adapters.online_v8 import HRDLogCloudAdapter
from app.adapters.provider_registry import PROVIDER_ADAPTERS, capabilities_for
from app.adapters.qrz_cloud_v501 import QRZCloudAdapterV501
from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.qso_manager_workspace import QSOManagerWorkspace
from app.services.v8_online_service import V8OnlineService


def test_production_provider_registry_is_deterministic():
    assert PROVIDER_ADAPTERS["QRZ"] is QRZCloudAdapterV501
    assert PROVIDER_ADAPTERS["HRDLOG"] is HRDLogCloudAdapter
    assert capabilities_for("WRL") == {"read": True, "add": True, "update": True, "delete": True}
    assert capabilities_for("HRDLOG")["add"] is True
    assert capabilities_for("HRD") == {"read": True, "add": False, "update": False, "delete": False}


def test_unified_v9_status_exposes_same_log_sources(tmp_path: Path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    credentials = CredentialStore(root=tmp_path)
    service = V8OnlineService(credentials=credentials, snapshots=snapshots)
    status = service.status()

    assert status["version"] == "9.0.0"
    assert status["mobile_policy"] == "unified_cross_platform"
    assert status["hrd_local_in_mobile"] is True
    names = [row["provider"] for row in status["providers"]]
    for provider in ("QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW", "HRDLOG", "HRD"):
        assert provider in names


def test_hrd_adif_is_importable_in_unified_service(tmp_path: Path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    service = V8OnlineService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=snapshots,
    )
    result = service.import_source_adif(
        "HRD",
        "<ADIF_VER:5>3.1.4<EOH>"
        "<CALL:5>K1ABC<QSO_DATE:8>20260912<TIME_ON:6>010203<BAND:3>20M<MODE:3>FT8<EOR>",
        "hrd-local.adi",
    )
    assert result["records"] == 1
    loaded = snapshots.load("HRD")
    assert loaded["records"][0]["CALL"] == "K1ABC"
    status = next(x for x in service.status()["providers"] if x["provider"] == "HRD")
    assert status["configured"] is True
    assert status["source_kind"] == "local_adif"


def test_workspace_can_plan_hrdlog_publish(tmp_path: Path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    credentials = CredentialStore(root=tmp_path)
    credentials.set("HRDLOG", {"callsign": "PU2BRU", "upload_code": "secret"})
    snapshots.save("QRZ", [{
        "CALL": "K1ABC",
        "QSO_DATE": "20260912",
        "TIME_ON": "010203",
        "BAND": "20M",
        "FREQ": "14.074",
        "MODE": "FT8",
    }], {"coverage": "API_FULL_SYNC"})

    hub = CloudHubService(credentials=credentials, snapshots=snapshots)
    workspace = QSOManagerWorkspace(hub=hub)
    row = workspace.query(page_size=10)["items"][0]
    plan = workspace.plan_bulk("PUBLISH", [row["logical_id"]], target="HRDLOG")

    assert plan["actionable"] == 1
    assert plan["unsupported"] == 0


def test_main_registers_v9_diagnostics_route():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/diagnostics" in paths
    assert "/api/diagnostics/launcher-log" in paths
    assert "/api/v8/status" in paths
