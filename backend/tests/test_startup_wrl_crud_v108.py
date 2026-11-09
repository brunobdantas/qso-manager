"""Regression tests for startup snapshot caching and WRL pagination."""
import json

import httpx

from app.adapters.cloud_logs import WRLCloudAdapter, CloudProviderError
from app.services.cloud_snapshot_store import CloudSnapshotStore


def test_snapshot_summary_can_load_without_parsing_full_data(tmp_path, monkeypatch):
    store = CloudSnapshotStore(root=tmp_path)
    store.save("WRL", [
        {"CALL": "PY2AAA", "QSO_DATE": "2026-11-09", "TIME_ON": "10:00:00", "MODE": "FT8"},
        {"CALL": "PY2BBB", "QSO_DATE": "2026-11-09", "TIME_ON": "10:01:00", "MODE": "FT8"},
    ])
    assert (tmp_path / "wrl.summary.json").exists()
    # In a new service instance, summaries must not parse the full 26k+ QSO JSON.
    another = CloudSnapshotStore(root=tmp_path)
    monkeypatch.setattr(another, "load", lambda *_: (_ for _ in ()).throw(AssertionError("large snapshot parsed")))
    assert another.summary("WRL")["records"] == 2
    assert another.summary("WRL")["records"] == 2


def test_legacy_snapshot_is_upgraded_to_small_summary(tmp_path):
    (tmp_path / "wrl.json").write_text(json.dumps({
        "provider": "WRL", "downloaded_at": "2026-11-09T00:00:00Z",
        "records": [{"CALL": "ZZ1A"}], "metadata": {}
    }), encoding="utf-8")
    store = CloudSnapshotStore(root=tmp_path)
    assert store.summary("WRL")["records"] == 1
    assert (tmp_path / "wrl.summary.json").exists()
    store.clear("WRL")
    assert not (tmp_path / "wrl.summary.json").exists()


def test_wrl_full_sync_reports_cursor_page_progress():
    queries = []
    def handler(request):
        cursor = request.url.params.get("cursor")
        queries.append(cursor)
        if cursor is None:
            return httpx.Response(200, json={"data": [{
                "id": "a", "call": "K1AAA", "timestamp": "2026-11-09T12:00:00Z",
                "mode": "FT8", "band": "15m"
            }], "meta": {"nextCursor": "page-two"}})
        return httpx.Response(200, json={"data": [{
            "id": "b", "call": "K1BBB", "timestamp": "2026-11-09T12:01:00Z",
            "mode": "FT4", "band": "12m"
        }], "meta": {"nextCursor": None}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with WRLCloudAdapter({"api_key": "fake"}, client=client) as adapter:
            events = []
            result = adapter.fetch_all(progress_callback=lambda pages, count, elapsed: events.append((pages, count)))
    assert queries == [None, "page-two"]
    assert result["metadata"]["pages"] == 2
    assert len(result["records"]) == 2
    assert events == [(1, 1), (2, 2)]


def test_wrl_get_retries_transient_failure_without_retrying_writes(monkeypatch):
    monkeypatch.setattr("app.adapters.cloud_logs.time.sleep", lambda _seconds: None)
    attempts = []
    def handler(request):
        attempts.append(request.method)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"message": "temporarily unavailable"}})
        return httpx.Response(200, json={"data": [], "meta": {}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with WRLCloudAdapter({"api_key": "fake"}, client=client) as adapter:
            result = adapter.fetch_all()
    assert result["records"] == []
    assert attempts == ["GET", "GET"]
