from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore


def _qso(call, time):
    return {
        "CALL": call,
        "QSO_DATE": "2026-09-04",
        "TIME_ON": time,
        "BAND": "20m",
        "FREQ": "14.074",
        "MODE": "FT8",
    }


def test_legacy_eqsl_snapshot_is_ignored_until_resynced(tmp_path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    credentials = CredentialStore(root=tmp_path)
    snapshots.save("QRZ", [_qso("K1ABC", "12:39:00")], {"coverage": "API_FULL_SYNC", "source": "remote_api"})
    snapshots.save(
        "EQSL",
        [_qso("FAKE1", "01:00:00")],
        {"coverage": "API_FULL_SYNC", "source": "remote_api", "normalized_export": True},
    )

    result = CloudHubService(credentials=credentials, snapshots=snapshots).analysis()
    assert result["ready"] is True
    assert result["ignored_sources"] == ["EQSL"]
    assert result["pairwise"] == {}
    assert result["qrz_stale_candidates"] == []
    assert result["missing_elsewhere"] == []
    assert result["field_differences"] == []
    assert result["summary"]["missing_elsewhere"] == 0


def test_new_verified_eqsl_snapshot_participates_in_analysis(tmp_path):
    snapshots = CloudSnapshotStore(root=tmp_path)
    credentials = CredentialStore(root=tmp_path)
    snapshots.save("QRZ", [_qso("K1ABC", "12:39:00")], {"coverage": "API_FULL_SYNC", "source": "remote_api"})
    snapshots.save(
        "EQSL",
        [_qso("FAKE1", "01:00:00")],
        {
            "coverage": "API_FULL_SYNC",
            "source": "remote_api",
            "normalized_export": True,
            "download_strategy": "OUTBOX_ADIF_FILE",
            "remote_reported_count": 1,
        },
    )

    result = CloudHubService(credentials=credentials, snapshots=snapshots).analysis()
    assert "ignored_sources" not in result
    assert "EQSL" in result["pairwise"]
    assert result["summary"]["missing_elsewhere"] >= 1
