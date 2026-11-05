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


def test_export_adif_large_selection_indexes_rows_once(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    rows = [
        {
            "logical_id": f"logical-{index}",
            "canonical_record": {
                "CALL": f"T{index:04d}ST",
                "QSO_DATE": "2026-11-04",
                "TIME_ON": "12:00:00",
                "BAND": "15M",
                "MODE": "FT8",
            },
        }
        for index in range(1500)
    ]
    calls = []
    def cached_once():
        calls.append(True)
        return rows, {}

    monkeypatch.setattr(ws, "_cached", cached_once)
    selected = [f"logical-{index}" for index in reversed(range(1500))]
    adif = ws.export_adif(selected)
    assert len(calls) == 1
    assert adif.count("<EOR>") == len(selected)
    assert adif.index("T1499ST") < adif.index("T0000ST")


def test_export_adif_rejects_missing_logical_id(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    monkeypatch.setattr(ws, "_cached", lambda: ([], {}))
    import pytest
    with pytest.raises(LookupError, match="Logical QSO not found"):
        ws.export_adif(["missing"])


def test_lookup_and_bulk_plan_use_cached_id_index(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    ws.hub.snapshots.save("QRZ", [
        {"CALL": f"T{i:04d}ST", "QSO_DATE": "2026-11-04",
         "TIME_ON": f"12:{i // 60:02d}:{i % 60:02d}", "BAND": "15M", "MODE": "FT8"}
        for i in range(120)
    ], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    ids = ws.ids()["ids"]
    assert len(ids) == 120
    expected = ws.get(ids[0])
    assert ws._raw(ids[0])["logical_id"] == ids[0]
    assert ws.get(ids[0]) == expected
    plan = ws.plan_bulk("PUBLISH", ids, target="EQSL")
    assert plan["selected"] == 120
    assert plan["actionable"] == 120
    assert len(ws._cache_by_id) == 120
    QSOManagerWorkspace.invalidate_cache()
    assert ws._cache_by_id == {}
    assert ws.get(ids[0])["logical_id"] == ids[0]
