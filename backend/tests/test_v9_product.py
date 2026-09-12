from pathlib import Path

from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.v9_product_service import V9ProductService


def service(tmp_path: Path) -> V9ProductService:
    return V9ProductService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=CloudSnapshotStore(root=tmp_path),
    )


def test_v9_status_is_unified_and_includes_hrd(tmp_path: Path):
    s = service(tmp_path)
    status = s.status()
    assert status["version"] == "9.0.0"
    assert status["product_mode"] == "unified"
    assert status["capability_parity"] is True
    assert status["hrd_local_in_mobile"] is True
    assert status["navigation"] == ["overview", "log", "inbox", "qsl", "sources", "tools"]
    providers = {row["provider"]: row for row in status["providers"]}
    assert set(["QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW", "HRDLOG", "HRD"]).issubset(providers)
    assert providers["HRD"]["source_kind"] == "local_adif"
    assert providers["HRD"]["credentials"] == {}


def test_hrd_adif_is_part_of_the_same_workspace(tmp_path: Path):
    s = service(tmp_path)
    result = s.import_local_adif(
        "HRD",
        "<ADIF_VER:5>3.1.4<EOH>"
        "<CALL:5>K1ABC<QSO_DATE:8>20260912<TIME_ON:6>120000<BAND:3>20M<MODE:3>FT8<EOR>",
        "hrd.adi",
    )
    assert result["records"] == 1
    status = s.status()
    hrd = next(row for row in status["providers"] if row["provider"] == "HRD")
    assert hrd["configured"] is True
    assert hrd["snapshot"]["records"] == 1
    log = s.log(page=1, page_size=10)
    assert log["total"] == 1
    assert log["items"][0]["call"] == "K1ABC"
    assert "HRD" in log["items"][0]["providers"]


def test_clearing_local_hrd_does_not_touch_credentials(tmp_path: Path):
    s = service(tmp_path)
    s.credentials.set("QRZ", {"api_key": "secret"})
    s.import_local_adif(
        "HRD",
        "<EOH><CALL:5>K1ABC<QSO_DATE:8>20260912<TIME_ON:6>120000<BAND:3>20M<MODE:3>FT8<EOR>",
        "hrd.adi",
    )
    result = s.clear_snapshot("HRD")
    assert result["records_removed"] == 1
    assert s.snapshots.summary("HRD")["records"] == 0
    assert s.credentials.get("QRZ")["api_key"] == "secret"


def test_bootstrap_and_diagnostics_do_not_expose_secret_values(tmp_path: Path):
    s = service(tmp_path)
    s.credentials.set("QRZ", {"api_key": "super-secret-key"})
    boot = s.bootstrap()
    assert boot["version"] == "9.0.0"
    text = str(boot)
    assert "super-secret-key" not in text
    diagnostic = s.diagnostics()
    assert diagnostic["capability_parity"] is True
    assert "super-secret-key" not in str(diagnostic)
