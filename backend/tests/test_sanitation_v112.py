"""Regression coverage for v1.1.2 sanitation and safety semantics."""
from pathlib import Path

from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.integrity_service import IntegrityService, IntegrityStore
from app.services.qso_manager_workspace import QSOManagerWorkspace
from app.services.v9_product_service import V9ProductService


def _qso(call="K1ABC", time="12:00:00", mode="FT8", **extra):
    return {
        "CALL": call,
        "QSO_DATE": "2026-11-10",
        "TIME_ON": time,
        "BAND": "15M",
        "MODE": mode,
        **extra,
    }


def _service(tmp_path: Path) -> V9ProductService:
    return V9ProductService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=CloudSnapshotStore(root=tmp_path),
    )


def test_reference_count_is_not_inflated_by_external_observation(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [_qso()], {"coverage": "API_FULL_SYNC"})
    service.snapshots.save("WRL", [_qso(), _qso("K9EXTRA", "13:00:00")], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    summary = service._workspace().options()["summary"]
    assert summary["reference_qsos"] == 1
    assert summary["observed_logical_qsos"] == 2
    assert summary["external_observations"] == 1


def test_metadata_normalization_removes_accent_punctuation_noise(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [_qso(NAME="José da Silva", QTH="São Paulo-SP")])
    service.snapshots.save("WRL", [_qso(NAME="JOSE DA SILVA", QTH="SAO PAULO SP")])
    QSOManagerWorkspace.invalidate_cache()
    row = service.log(page=1, page_size=10)["items"][0]
    assert row["difference_fields"] == []


def test_issues_group_types_and_do_not_count_qsl_as_pending(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [_qso(RST_SENT="-10", QSL_RCVD="Y")], {"coverage": "API_FULL_SYNC"})
    service.snapshots.save("WRL", [_qso(RST_SENT="599")], {"coverage": "API_FULL_SYNC"})
    service.snapshots.save("CLUBLOG", [], {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    result = service.issues(limit=50)
    assert result["total"] == 1
    assert result["counts"]["qsl"] == 1
    assert "QSL" not in result["items"][0]["types"]
    assert set(result["items"][0]["types"]) == {"MISSING", "DIFFERENCE"}
    assert result["items"][0]["severity"] == "HIGH"


def test_hrdlog_plan_explains_all_unsupported_missing_records(tmp_path):
    root = tmp_path / "user"
    snapshots = CloudSnapshotStore(root=root)
    snapshots.save("QRZ", [_qso(), _qso("K1XYZ", "13:00:00")], {"coverage": "API_FULL_SYNC"})
    snapshots.save("HRDLOG", [], {"coverage": "FULL_EXPORT"})
    QSOManagerWorkspace.invalidate_cache()
    workspace = QSOManagerWorkspace(hub=CloudHubService(
        credentials=CredentialStore(root=root), snapshots=snapshots,
    ))
    plan = IntegrityService(workspace=workspace, store=IntegrityStore(root=root)).reconcile_plan("HRDLOG")
    assert plan["missing_total"] == 2
    assert plan["blocked"] == 2
    assert plan["blocked_reasons"] == {"WRITE_NOT_SUPPORTED": 2}
    assert plan["logical_ids"] == []


def test_reference_export_contains_only_qrz(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [_qso()])
    service.snapshots.save("WRL", [_qso("K9EXTRA")])
    exported = service.export_reference_adif()
    assert exported["records"] == 1
    assert "K1ABC" in exported["content"]
    assert "K9EXTRA" not in exported["content"]


def test_spa_index_is_not_cached_across_upgrades(tmp_path):
    from app.main import _spa_index_response

    index = tmp_path / "index.html"
    index.write_text("<html></html>", encoding="utf-8")
    response = _spa_index_response(index)
    assert response.headers["cache-control"] == "no-store, max-age=0"
