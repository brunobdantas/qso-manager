import time

from app.services import sync_job_service
from app.services.sync_job_service import SyncJobManager


class _FakeSnapshots:
    def save(self, provider, records, metadata):
        return {"provider": provider, "records": len(records), "metadata": metadata, "downloaded_at": "now"}


class _FakeAdapter:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def fetch_all(self):
        time.sleep(0.02)
        return {"records": [{"CALL": "K1ABC"}, {"CALL": "W1XYZ"}], "metadata": {"coverage": "API_FULL_SYNC"}}


class _FakeService:
    SYNC_PROVIDERS = ("QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW")
    LABELS = {"QRZ": "QRZ", "WRL": "World Radio League", "CLUBLOG": "Club Log", "EQSL": "eQSL OutBox", "EQSL_INBOX": "eQSL Inbox", "LOTW": "LoTW"}

    def __init__(self):
        self.snapshots = _FakeSnapshots()

    def _normalize_provider(self, provider):
        value = str(provider).strip().upper()
        if value not in self.SYNC_PROVIDERS:
            raise RuntimeError("unsupported")
        return value

    def _configured(self, provider):
        return True

    def _adapter(self, provider):
        return _FakeAdapter()


def _reset():
    SyncJobManager._jobs = {}
    SyncJobManager._active_by_provider = {}


def test_sync_job_exposes_progress_and_finishes(monkeypatch):
    monkeypatch.setattr(sync_job_service, "V9ProductService", _FakeService)
    monkeypatch.setattr(sync_job_service.QSOManagerWorkspace, "invalidate_cache", classmethod(lambda cls: None))
    _reset()

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
    assert current["remote_write"] is False


def test_sync_job_reuses_active_job_for_same_provider(monkeypatch):
    class _SlowAdapter(_FakeAdapter):
        def fetch_all(self):
            time.sleep(0.15)
            return super().fetch_all()

    class _SlowService(_FakeService):
        def _adapter(self, provider):
            return _SlowAdapter()

    monkeypatch.setattr(sync_job_service, "V9ProductService", _SlowService)
    monkeypatch.setattr(sync_job_service.QSOManagerWorkspace, "invalidate_cache", classmethod(lambda cls: None))
    _reset()

    first = SyncJobManager.start("WRL")
    second = SyncJobManager.start("WRL")
    assert second["job_id"] == first["job_id"]
