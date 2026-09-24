import threading
import time

from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.sync_job_service import SyncJobManager
from app.services.v8_online_service import V8OnlineService


def _reset_jobs():
    with SyncJobManager._lock:
        SyncJobManager._jobs = {}
        SyncJobManager._active_by_provider = {}


def test_sync_all_runs_configured_sources_concurrently(tmp_path, monkeypatch):
    service = V8OnlineService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=CloudSnapshotStore(root=tmp_path),
    )
    enabled = {"QRZ", "LOTW"}
    barrier = threading.Barrier(2)

    monkeypatch.setattr(service, "_configured", lambda provider: provider in enabled)

    def fake_sync(provider):
        barrier.wait(timeout=2)
        return {"provider": provider, "ok": True, "records": 1}

    monkeypatch.setattr(service, "sync", fake_sync)
    monkeypatch.setattr(service, "dashboard", lambda: {"ok": True})

    result = service.sync_all()

    assert result["parallel"] is True
    rows = {row["provider"]: row for row in result["results"]}
    assert rows["QRZ"]["ok"] is True
    assert rows["LOTW"]["ok"] is True
    assert rows["WRL"]["skipped"] is True


def test_background_sync_jobs_run_in_parallel_and_report_progress(monkeypatch):
    import app.services.sync_job_service as module

    _reset_jobs()
    barrier = threading.Barrier(2)

    class FakeSnapshots:
        saved = []

        def save(self, provider, records, metadata):
            self.saved.append((provider, list(records), dict(metadata)))
            return {
                "provider": provider,
                "records": len(records),
                "downloaded_at": "2026-09-24T03:00:00+00:00",
                "metadata": metadata,
            }

    snapshots = FakeSnapshots()

    class FakeAdapter:
        def __init__(self, provider):
            self.provider = provider

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def fetch_all(self):
            barrier.wait(timeout=2)
            return {
                "records": [{"CALL": "K1ABC", "QSO_DATE": "20260924"}],
                "metadata": {"coverage": "API_FULL_SYNC"},
            }

    class FakeService:
        SYNC_PROVIDERS = ("QRZ", "LOTW")
        LABELS = {"QRZ": "QRZ", "LOTW": "LoTW"}

        def __init__(self):
            self.snapshots = snapshots

        def _normalize_provider(self, provider):
            provider = provider.upper()
            if provider not in self.SYNC_PROVIDERS:
                raise ValueError(provider)
            return provider

        def _configured(self, provider):
            return provider in self.SYNC_PROVIDERS

        def _adapter(self, provider):
            return FakeAdapter(provider)

    monkeypatch.setattr(module, "V9ProductService", FakeService)
    monkeypatch.setattr(module.QSOManagerWorkspace, "invalidate_cache", classmethod(lambda cls: None))

    started = SyncJobManager.start_all()
    assert started["parallel"] is True
    assert started["started"] == 2

    deadline = time.time() + 3
    terminal = {}
    while time.time() < deadline:
        terminal = {j["provider"]: SyncJobManager.get(j["job_id"]) for j in started["jobs"]}
        if all(job["status"] in {"succeeded", "failed"} for job in terminal.values()):
            break
        time.sleep(0.02)

    assert set(terminal) == {"QRZ", "LOTW"}
    assert all(job["status"] == "succeeded" for job in terminal.values())
    assert all(job["progress"] == 100 for job in terminal.values())
    assert all(job["records"] == 1 for job in terminal.values())
    assert all(job["remote_write"] is False for job in terminal.values())
    assert {provider for provider, _rows, _meta in snapshots.saved} == {"QRZ", "LOTW"}


def test_failed_background_download_preserves_previous_snapshot(monkeypatch):
    import app.services.sync_job_service as module

    _reset_jobs()

    class FakeSnapshots:
        save_calls = 0

        def save(self, provider, records, metadata):
            self.save_calls += 1
            raise AssertionError("save must not be called after a failed download")

    snapshots = FakeSnapshots()

    class FailingAdapter:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def fetch_all(self):
            raise RuntimeError("remote temporarily unavailable")

    class FakeService:
        SYNC_PROVIDERS = ("QRZ",)
        LABELS = {"QRZ": "QRZ"}

        def __init__(self):
            self.snapshots = snapshots

        def _normalize_provider(self, provider):
            return provider.upper()

        def _configured(self, provider):
            return True

        def _adapter(self, provider):
            return FailingAdapter()

    monkeypatch.setattr(module, "V9ProductService", FakeService)
    job = SyncJobManager.start("QRZ")

    deadline = time.time() + 2
    current = job
    while time.time() < deadline:
        current = SyncJobManager.get(job["job_id"])
        if current["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)

    assert current["status"] == "failed"
    assert current["progress"] == 100
    assert "snapshot anterior foi preservado" in current["message"]
    assert snapshots.save_calls == 0
