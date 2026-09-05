from pathlib import Path

from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.cloud_hub_fast_service import CloudHubService
from app.services.credential_store import CredentialStore


def test_clear_snapshot_removes_only_active_local_copy(tmp_path: Path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    credentials = CredentialStore(root=tmp_path)
    credentials.set("EQSL", {"username": "PU2BRU", "password": "secret"})
    snapshots.save("EQSL", [{"CALL": "PY2ABC", "QSO_DATE": "2026-01-01", "TIME_ON": "12:00:00"}], {"coverage": "API_FULL_SYNC"})

    service = CloudHubService(credentials=credentials, snapshots=snapshots)
    result = service.clear_snapshot("EQSL")

    assert result["ok"] is True
    assert result["cleared"] is True
    assert result["records_removed"] == 1
    assert result["remote_affected"] is False
    assert result["credentials_affected"] is False
    assert snapshots.summary("EQSL")["records"] == 0
    assert credentials.get("EQSL")["username"] == "PU2BRU"


def test_clear_empty_snapshot_is_idempotent(tmp_path: Path):
    service = CloudHubService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=CloudSnapshotStore(root=tmp_path),
    )

    first = service.clear_snapshot("CLUBLOG")
    second = service.clear_snapshot("CLUBLOG")

    assert first["records_removed"] == 0
    assert second["records_removed"] == 0
    assert first["cleared"] is False
    assert second["cleared"] is False
