from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.qso_manager_workspace import QSOManagerWorkspace
from app.adapters.cloud_logs import CloudProviderError
import pytest


def qso(call, time_on, band="20m", freq=14.074, mode="FT8"):
    return {"CALL": call, "QSO_DATE": "2026-09-04", "TIME_ON": time_on, "BAND": band, "FREQ": freq, "MODE": mode}


def test_qrz_first_analysis_can_flag_qrz_as_likely_stale(tmp_path):
    credentials = CredentialStore(tmp_path / "credentials")
    snapshots = CloudSnapshotStore(tmp_path / "data")
    hub = CloudHubService(credentials=credentials, snapshots=snapshots)

    base = qso("K1BASE", "12:00:00")
    missing_from_qrz = qso("K1NEW", "12:39:00")
    qrz_only = qso("K1QRZ", "13:00:00", band="15m", freq=21.074)

    snapshots.save("QRZ", [base, qrz_only], {"coverage": "API_FULL_SYNC"})
    snapshots.save("WRL", [base, missing_from_qrz], {"coverage": "API_FULL_SYNC"})
    snapshots.save("CLUBLOG", [base, missing_from_qrz], {"coverage": "API_FULL_SYNC"})

    result = hub.analysis()
    assert result["ready"] is True
    assert result["summary"]["qrz_records"] == 2
    assert result["summary"]["qrz_likely_stale"] == 1
    candidate = result["qrz_stale_candidates"][0]
    assert candidate["call"] == "K1NEW"
    assert set(candidate["sources"]) == {"WRL", "CLUBLOG"}
    assert candidate["assessment"] == "QRZ_LIKELY_STALE"

    targets = {(row["call"], row["target"]) for row in result["missing_elsewhere"]}
    assert ("K1QRZ", "WRL") in targets
    assert ("K1QRZ", "CLUBLOG") in targets


def test_credentials_are_encrypted_and_masked(tmp_path):
    store = CredentialStore(tmp_path)
    store.set("QRZ", {"api_key": "ABCD-SUPER-SECRET", "callsign": "PU2BRU"})
    assert store.get("QRZ")["api_key"] == "ABCD-SUPER-SECRET"
    assert "ABCD-SUPER-SECRET" not in store.store_path.read_text(encoding="utf-8")
    masked = store.masked(store.get("QRZ"))
    assert masked["api_key"].startswith("••••")
    assert masked["callsign"] == "PU2BRU"


def test_publish_defaults_to_dry_run(tmp_path):
    credentials = CredentialStore(tmp_path / "credentials")
    snapshots = CloudSnapshotStore(tmp_path / "data")
    hub = CloudHubService(credentials=credentials, snapshots=snapshots)
    snapshots.save("QRZ", [qso("K1ABC", "12:39:00")])
    preview = hub.publish("QRZ", 0, "WRL", confirm=False)
    assert preview["dry_run"] is True
    assert preview["qso"]["record"]["CALL"] == "K1ABC"


def test_hrd_adif_becomes_persistent_comparison_source(tmp_path):
    credentials = CredentialStore(tmp_path / "credentials")
    snapshots = CloudSnapshotStore(tmp_path / "data")
    hub = CloudHubService(credentials=credentials, snapshots=snapshots)
    snapshots.save("QRZ", [qso("K1BASE", "12:00:00")], {"coverage": "API_FULL_SYNC"})
    content = (
        "<ADIF_VER:5>3.1.4<EOH>"
        "<CALL:5>K1NEW<QSO_DATE:8>20260904<TIME_ON:6>123900"
        "<BAND:3>20m<FREQ:6>14.074<MODE:3>FT8<EOR>"
    )

    imported = hub.import_adif_snapshot("HRD", content, "HRDLogbook.adi")

    assert imported["records"] == 1
    hrd = next(p for p in hub.status()["providers"] if p["provider"] == "HRD")
    assert hrd["configured"] is True
    assert hrd["source_kind"] == "local_adif"
    assert hrd["snapshot"]["metadata"]["filename"] == "HRDLogbook.adi"
    result = hub.analysis()
    assert result["pairwise"]["HRD"]["summary"]["records_b"] == 1
    assert result["qrz_stale_candidates"][0]["sources"] == ["HRD"]
    assert hub.search("K1NEW")["items"][0]["provider"] == "HRD"
    workspace = QSOManagerWorkspace(hub=hub)
    manager_rows = workspace.query(q="K1NEW")["items"]
    assert manager_rows[0]["providers"] == ["HRD"]
    assert "HRD" in workspace.options()["available_providers"]


def test_hrd_reimport_replaces_snapshot_and_keeps_backup(tmp_path):
    hub = CloudHubService(
        credentials=CredentialStore(tmp_path / "credentials"),
        snapshots=CloudSnapshotStore(tmp_path / "data"),
    )
    first = "<CALL:5>K1OLD<QSO_DATE:8>20260904<TIME_ON:6>120000<EOR>"
    second = "<CALL:5>K1NEW<QSO_DATE:8>20260904<TIME_ON:6>123900<EOR>"
    hub.import_adif_snapshot("HRD", first, "first.adi")

    result = hub.import_adif_snapshot("HRD", second, "second.adi")

    assert result["backup"] is not None
    assert [r["CALL"] for r in hub.snapshots.load("HRD")["records"]] == ["K1NEW"]


def test_remote_provider_cannot_be_overwritten_by_manual_adif(tmp_path):
    hub = CloudHubService(
        credentials=CredentialStore(tmp_path / "credentials"),
        snapshots=CloudSnapshotStore(tmp_path / "data"),
    )
    with pytest.raises(CloudProviderError):
        hub.import_adif_snapshot("QRZ", "<CALL:5>K1ABC<EOR>", "qrz.adi")
