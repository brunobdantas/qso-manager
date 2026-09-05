import time

from app.services import sync_job_service
from app.services.sync_job_service import SyncJobManager


class _FakeCredentials:
    def configured(self, provider):
        return True


class _FakeSnapshots:
    def save(self, provider, records, metadata):
        return {"provider": provider, "records": len(records), "metadata": metadata, "downloaded_at": "now"}


class _FakeService:
    def __init__(self):
        self.credentials = _FakeCredentials()
        self.snapshots = _FakeSnapshots()

    @classmethod
    def _provider(cls, provider):
        value = str(provider).strip().upper()
        if value not in {"QRZ", "WRL", "CLUBLOG", "EQSL"}:
            raise RuntimeError("unsupported")
        return value

    def _credentials(self, provider):
        return {"api_key": "fake"}


class _FakeAdapter:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def fetch_all(self):
        time.sleep(0.02)
        return {"records": [{"CALL": "K1ABC"}, {"CALL": "W1XYZ"}], "metadata": {"coverage": "API_FULL_SYNC"}}


def test_sync_job_exposes_progress_and_finishes(monkeypatch):
    monkeypatch.setattr(sync_job_service, "CloudHubService", _FakeService)
    monkeypatch.setattr(sync_job_service, "adapter_for", lambda provider, credentials: _FakeAdapter())
    SyncJobManager._jobs = {}
    SyncJobManager._active_by_provider = {}

    started = SyncJobManager.start("qrz")
    assert started["provider"] == "QRZ"
    assert started["status"] in {"queued", "running"}

    deadline = time.time() + 2
    current = started
    while time.time() < deadline:
        current = SyncJobManager.get(started["job_id"])
        if current["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert current["status"] == "succeeded"
    assert current["progress"] == 100
    assert current["records"] == 2
    assert current["snapshot"]["records"] == 2
    assert "QRZ atualizado" in current["message"]


def test_sync_job_reuses_active_job_for_same_provider(monkeypatch):
    class _SlowAdapter(_FakeAdapter):
        def fetch_all(self):
            time.sleep(0.15)
            return super().fetch_all()

    monkeypatch.setattr(sync_job_service, "CloudHubService", _FakeService)
    monkeypatch.setattr(sync_job_service, "adapter_for", lambda provider, credentials: _SlowAdapter())
    SyncJobManager._jobs = {}
    SyncJobManager._active_by_provider = {}

    first = SyncJobManager.start("WRL")
    second = SyncJobManager.start("WRL")
    assert second["job_id"] == first["job_id"]
