from app.services.cloud_snapshot_store import CloudSnapshotStore


def test_summary_cache_reuses_json_and_detects_replacement(tmp_path, monkeypatch):
    store = CloudSnapshotStore(root=tmp_path)
    original = store.load
    calls = []

    def counted(provider):
        calls.append(provider)
        return original(provider)

    monkeypatch.setattr(store, "load", counted)
    assert store.summary("QRZ")["records"] == 0
    assert store.summary("QRZ")["records"] == 0
    assert calls == ["QRZ"]

    store.save("QRZ", [{"CALL": "K1ABC"}], {"coverage": "API_FULL_SYNC"})
    assert store.summary("QRZ")["records"] == 1
    # One load after the save; repeated requests must not reparse the JSON.
    assert len(calls) == 2
    store._path("QRZ").write_text(
        '{"provider":"QRZ","downloaded_at":"new","records":[{},{}],"metadata":{}}',
        encoding="utf-8",
    )
    assert store.summary("QRZ")["records"] == 2
    assert len(calls) == 3
    store.clear("QRZ")
    assert store.summary("QRZ")["records"] == 0
