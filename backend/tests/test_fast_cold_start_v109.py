"""Regression coverage for persistent analysis cache and fast WRL ingest."""
from pathlib import Path

import httpx
import pytest

from app.adapters.cloud_logs import WRLCloudAdapter, CloudProviderError
from app.services.bootstrap_cache_service import BootstrapCache
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.v9_product_service import V9ProductService


def _service(tmp_path: Path):
    return V9ProductService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=CloudSnapshotStore(root=tmp_path),
    )


def test_bootstrap_persists_derived_analysis_across_restart(tmp_path, monkeypatch):
    first = _service(tmp_path)
    first.snapshots.save("QRZ", [{
        "CALL": "K1ABC", "QSO_DATE": "2026-11-09",
        "TIME_ON": "12:00:00", "BAND": "15M", "MODE": "FT8",
    }])
    first_boot = first.bootstrap()
    assert first_boot["workspace"]["summary"]["logical_qsos"] == 1
    assert BootstrapCache(first.snapshots).path.exists()

    restarted = _service(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("expensive analysis was recomputed on cold start")
    monkeypatch.setattr(restarted, "_workspace", forbidden)
    monkeypatch.setattr(restarted, "qsl_analysis", forbidden)
    cached_boot = restarted.bootstrap()
    assert cached_boot["workspace"] == first_boot["workspace"]
    assert cached_boot["dashboard"]["summary"] == first_boot["dashboard"]["summary"]


def test_cache_invalidates_when_snapshot_changes(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [{
        "CALL": "K1ABC", "QSO_DATE": "2026-11-09",
        "TIME_ON": "12:00:00", "BAND": "15M", "MODE": "FT8",
    }])
    service.bootstrap()
    assert BootstrapCache(service.snapshots).load() is not None
    service.snapshots.save("WRL", [{
        "CALL": "K1XYZ", "QSO_DATE": "2026-11-09",
        "TIME_ON": "12:01:00", "BAND": "15M", "MODE": "FT8",
    }])
    assert BootstrapCache(service.snapshots).load() is None
    assert service.bootstrap()["workspace"]["summary"]["logical_qsos"] >= 2


def test_full_wrl_adif_can_be_imported_and_preserves_previous_on_error(tmp_path):
    service = _service(tmp_path)
    sample = "<EOH><CALL:5>K1ABC<QSO_DATE:8>20261109<TIME_ON:6>120000<BAND:3>15M<MODE:3>FT8<EOR>"
    result = service.import_local_adif("WRL", sample, "wrl-full.adi")
    assert result["records"] == 1
    assert service.snapshots.summary("WRL")["metadata"]["source"] == "manual_wrl_adif"
    with pytest.raises(CloudProviderError):
        service.import_local_adif("WRL", "<EOH><CALL:5>K1ABC<EOR>", "bad.adi")
    assert service.snapshots.summary("WRL")["records"] == 1


def test_wrl_pagination_negotiation_falls_back_to_100():
    queries = []
    def handler(request):
        limit = request.url.params.get("limit")
        queries.append(limit)
        if limit == "250":
            return httpx.Response(422, json={"error": {"message": "page size too large"}})
        return httpx.Response(200, json={"data": [{
            "id": "one", "call": "K1ABC", "timestamp": "2026-11-09T12:00:00Z", "band": "15m", "mode": "FT8"
        }], "meta": {"nextCursor": None}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with WRLCloudAdapter({"api_key": "fake"}, client=client) as adapter:
            result = adapter.fetch_all()
    assert queries == ["250", "100"]
    assert result["metadata"]["page_size_requested"] == 100
    assert result["records"][0]["CALL"] == "K1ABC"


def test_wrl_can_request_250_when_supported():
    observed = []
    def handler(request):
        observed.append(request.url.params.get("limit"))
        return httpx.Response(200, json={"data": [], "meta": {}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with WRLCloudAdapter({"api_key": "fake"}, client=client) as adapter:
            result = adapter.fetch_all()
    assert observed == ["250"]
    assert result["metadata"]["page_size_requested"] == 250
