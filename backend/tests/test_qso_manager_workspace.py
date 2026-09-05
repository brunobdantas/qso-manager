from pathlib import Path

from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.qso_manager_activity import QSOManagerActivityStore
from app.services.qso_manager_workspace import QSOManagerWorkspace


def workspace(tmp_path: Path) -> QSOManagerWorkspace:
    root = tmp_path / "user"
    hub = CloudHubService(
        credentials=CredentialStore(root=root),
        snapshots=CloudSnapshotStore(root=root),
    )
    QSOManagerWorkspace.invalidate_cache()
    return QSOManagerWorkspace(hub=hub)


def test_unified_workspace_matches_real_1249_regression_shape(tmp_path):
    ws = workspace(tmp_path)
    ws.hub.snapshots.save("QRZ", [{
        "CALL": "PU2TEST", "QSO_DATE": "2026-09-01", "TIME_ON": "12:39:00",
        "BAND": "15M", "FREQ": "21.076100", "MODE": "MFSK", "SUBMODE": "FT4",
    }], {"coverage": "API_FULL_SYNC"})
    ws.hub.snapshots.save("WRL", [{
        "CALL": "PU2TEST", "QSO_DATE": "2026-09-01", "TIME_ON": "12:39:20",
        "BAND": "15M", "FREQ": "21.076900", "MODE": "FT4",
    }], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()

    result = ws.query(page=1, page_size=100)
    assert result["total"] == 1
    row = result["items"][0]
    assert row["providers"] == ["QRZ", "WRL"]
    assert row["missing_in"] == []
    assert row["canonical_provider"] == "QRZ"


def test_filters_selection_and_export_use_logical_rows(tmp_path):
    ws = workspace(tmp_path)
    ws.hub.snapshots.save("QRZ", [
        {"CALL": "LU1AAA", "QSO_DATE": "2026-01-01", "TIME_ON": "10:00:00", "BAND": "10M", "FREQ": "28.074", "MODE": "FT8", "COUNTRY": "Argentina"},
        {"CALL": "PY2BBB", "QSO_DATE": "2026-01-02", "TIME_ON": "11:00:00", "BAND": "15M", "FREQ": "21.074", "MODE": "FT8", "COUNTRY": "Brazil"},
    ], {"coverage": "API_FULL_SYNC"})
    ws.hub.snapshots.save("WRL", [
        {"CALL": "LU1AAA", "QSO_DATE": "2026-01-01", "TIME_ON": "10:00:10", "BAND": "10M", "FREQ": "28.074", "MODE": "FT8", "COUNTRY": "Argentina"},
    ], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()

    result = ws.query(country="Argentina", page=1, page_size=25)
    assert result["total"] == 1
    logical_id = result["items"][0]["logical_id"]
    ids = ws.ids(country="Argentina")
    assert ids["ids"] == [logical_id]
    adif = ws.export_adif([logical_id])
    assert "LU1AAA" in adif
    assert "PY2BBB" not in adif


def test_workspace_flags_qrz_missing_and_duplicates(tmp_path):
    ws = workspace(tmp_path)
    ws.hub.snapshots.save("QRZ", [
        {"CALL": "A1AAA", "QSO_DATE": "2026-01-01", "TIME_ON": "10:00:00", "BAND": "15M", "FREQ": "21.074", "MODE": "FT8"},
    ], {"coverage": "API_FULL_SYNC"})
    ws.hub.snapshots.save("WRL", [
        {"CALL": "A1AAA", "QSO_DATE": "2026-01-01", "TIME_ON": "10:00:00", "BAND": "15M", "FREQ": "21.074", "MODE": "FT8", "RST_SENT": "-10", "RST_RCVD": "-15", "GRIDSQUARE": "GG00"},
        {"CALL": "A1AAA", "QSO_DATE": "2026-01-01", "TIME_ON": "10:00:01", "BAND": "15M", "FREQ": "21.074", "MODE": "FT8", "RST_SENT": "-10", "RST_RCVD": "-15", "GRIDSQUARE": "GG00"},
        {"CALL": "B2BBB", "QSO_DATE": "2026-01-03", "TIME_ON": "12:00:00", "BAND": "10M", "FREQ": "28.074", "MODE": "FT8"},
    ], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()

    options = ws.options()
    assert options["summary"]["qrz_missing"] >= 1
    assert options["summary"]["duplicates"] >= 1
    assert ws.query(qrz="missing", page=1, page_size=25)["total"] >= 1
    assert ws.query(duplicate="true", page=1, page_size=25)["total"] >= 1


def test_bulk_plan_respects_provider_capabilities(tmp_path):
    ws = workspace(tmp_path)
    ws.hub.snapshots.save("QRZ", [{
        "CALL": "LU9XYZ", "QSO_DATE": "2026-02-02", "TIME_ON": "12:00:00",
        "BAND": "15M", "FREQ": "21.074", "MODE": "FT8",
    }], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    logical_id = ws.query(page=1, page_size=25)["items"][0]["logical_id"]

    publish = ws.plan_bulk("PUBLISH", [logical_id], target="EQSL")
    assert publish["actionable"] == 1

    update_qrz = ws.plan_bulk("UPDATE", [logical_id], target="QRZ", changes={"COMMENT": "x"})
    assert update_qrz["actionable"] == 0
    assert update_qrz["unsupported"] == 1

    delete_qrz = ws.plan_bulk("DELETE", [logical_id], target="QRZ")
    assert delete_qrz["actionable"] == 0
    assert delete_qrz["unsupported"] == 1


def test_activity_store_persists_recent_events(tmp_path):
    store = QSOManagerActivityStore(root=tmp_path)
    store.append("EXPORT", "2 QSOs exportados", {"records": 2})
    store.append("BULK_COMPLETE", "1 concluído", {"processed": 1})
    rows = store.list(limit=10)
    assert len(rows) == 2
    assert rows[0]["kind"] == "BULK_COMPLETE"
    assert rows[1]["kind"] == "EXPORT"
