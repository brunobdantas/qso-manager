"""Safety and end-to-end integrity regressions for QSO Manager v1.1.0."""
from __future__ import annotations

import pytest

from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.integrity_service import IntegrityService, IntegrityStore, _failure_type
from app.services.qso_manager_workspace import QSOManagerWorkspace


def _qso(call, time="12:00:00", band="15M", mode="FT8", date="2026-11-09", **kw):
    return {"CALL": call, "QSO_DATE": date, "TIME_ON": time, "BAND": band, "MODE": mode,
            "FREQ": "21.074" if band == "15M" else "14.074", **kw}


def _engine(tmp_path, qrz, wrl=None, clublog=None, lotw=None, eqsl_inbox=None):
    root = tmp_path / "user"
    snaps = CloudSnapshotStore(root=root)
    snaps.save("QRZ", qrz, {"coverage": "API_FULL_SYNC"})
    for name, records in (("WRL", wrl), ("CLUBLOG", clublog),
                          ("LOTW", lotw), ("EQSL_INBOX", eqsl_inbox)):
        if records is not None:
            snaps.save(name, records, {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    hub = CloudHubService(
        credentials=CredentialStore(root=root),
        snapshots=snaps,
    )
    workspace = QSOManagerWorkspace(hub=hub)
    return IntegrityService(workspace=workspace, store=IntegrityStore(root=root))


def test_matching_net_counts_still_show_missing_extra_and_field_conflict(tmp_path):
    engine = _engine(
        tmp_path,
        [_qso("K1AAA", RST_SENT="-10"), _qso("K1BBB", "13:00:00")],
        wrl=[_qso("K1AAA", RST_SENT="-14"), _qso("K9EXTRA", "14:00:00")],
    )
    report = engine.report(page_size=50)
    metrics = report["summary"]["providers"]["WRL"]
    assert metrics["records"] == 2
    assert metrics["matched"] == 1
    assert metrics["missing"] == 1
    assert metrics["extra"] == 1
    assert metrics["different"] == 1
    assert metrics["state"] == "DIVERGENT"
    cases = {(c["kind"], c["call"], c["provider"]) for c in report["items"]}
    assert ("MISSING", "K1BBB", "WRL") in cases
    assert ("EXTRA", "K9EXTRA", "WRL") in cases
    assert ("DIFFERENCE", "K1AAA", "WRL") in cases


def test_duplicate_engine_respects_distinct_modes_and_bands(tmp_path):
    engine = _engine(tmp_path, [_qso("K1AAA")], wrl=[
        _qso("K1AAA", "12:00:00", RST_SENT="-10", RST_RCVD="-12"),
        _qso("K1AAA", "12:00:01", RST_SENT="-10", RST_RCVD="-12"),
        _qso("K1AAA", "12:00:00", mode="FT4", RST_SENT="-10", RST_RCVD="-12"),
        _qso("K1AAA", "12:00:00", band="20M", RST_SENT="-10", RST_RCVD="-12"),
    ])
    report = engine.report(page_size=100)
    assert report["summary"]["providers"]["WRL"]["duplicates"] == 1
    suspects = [c for c in report["items"] if c["kind"] == "DUPLICATE"]
    assert len(suspects) == 1
    assert len(suspects[0]["member_ids"]) == 2
    assert suspects[0]["actionable"] is False


def test_nearby_time_mismatch_blocks_assisted_publish(tmp_path):
    engine = _engine(tmp_path, [_qso("K1AAA", "12:00:00")],
                     wrl=[_qso("K1AAA", "12:03:00")])
    report = engine.report(page_size=100)
    missing = next(c for c in report["items"] if c["kind"] == "MISSING")
    assert not missing["actionable"]
    assert "5 minutos" in missing["reason"]
    plan = engine.reconcile_plan("WRL")
    assert plan["selected"] == 0
    assert plan["total_candidates"] == 0


def test_safe_plan_only_returns_qrz_missing_from_fresh_complete_source(tmp_path):
    engine = _engine(tmp_path, [_qso("K1AAA"), _qso("K1BBB", "13:00:00")],
                     wrl=[_qso("K1AAA")])
    plan = engine.reconcile_plan("WRL")
    assert plan["ready"]
    assert plan["selected"] == 1
    assert plan["sample"][0]["call"] == "K1BBB"
    assert plan["action"] == "PUBLISH"
    assert plan["source"] == "QRZ"
    assert plan["target"] == "WRL"


def test_decision_is_durable_and_suppresses_future_assisted_insertion(tmp_path):
    engine = _engine(tmp_path, [_qso("K1AAA")], wrl=[])
    case = next(c for c in engine.report()["items"] if c["kind"] == "MISSING")
    engine.store.decide(case["case_key"], "WRL", "ACCEPT_EXCEPTION",
                        "Provedor não admite este registro", {"ticket": "teste"})
    again = IntegrityService(workspace=engine.workspace, store=IntegrityStore(root=tmp_path / "user"))
    row = next(c for c in again.report()["items"] if c["case_key"] == case["case_key"])
    assert row["decision"] == "ACCEPT_EXCEPTION"
    assert row["actionable"] is False
    assert again.reconcile_plan("WRL")["selected"] == 0
    assert "ticket" in again.store.history()[0]["evidence"]


def test_incomplete_source_is_not_declared_aligned_or_written_to(tmp_path):
    engine = _engine(tmp_path, [_qso("K1AAA")])
    metrics = engine.report()["summary"]["providers"]["WRL"]
    assert metrics["state"] == "NO_COMPLETE_SNAPSHOT"
    assert not engine.reconcile_plan("WRL")["ready"]
    assert not engine.reconcile_plan("WRL")["logical_ids"]


def test_qsl_hunter_distinguishes_confirmed_and_unconfirmed_dxcc(tmp_path):
    engine = _engine(tmp_path, [
        _qso("K1AAA", DXCC="291", COUNTRY="United States"),
        _qso("K1BBB", "13:00:00", DXCC="110", COUNTRY="Hawaii", QSL_RCVD="Y"),
    ])
    result = engine.qsl_opportunities()
    assert result["ready"]
    assert result["summary"]["confirmed_dxcc"] == 1
    assert result["summary"]["pending_dxcc"] == 1
    assert result["items"][0]["dxcc"] == "291"
    assert result["items"][0]["new_dxcc"] is True
    engine.workspace.hub.snapshots.save("LOTW", [_qso("K1AAA", DXCC="291", QSL_RCVD="Y")],
                                        {"coverage": "API_FULL_SYNC"})
    with_confirmed_lotw = engine.qsl_opportunities()
    assert with_confirmed_lotw["summary"]["pending_dxcc"] == 0
    assert with_confirmed_lotw["summary"]["confirmed_dxcc"] == 2


def test_received_unverified_eqsl_is_not_assumed_award_confirmation(tmp_path):
    engine = _engine(tmp_path, [_qso("K1AAA", DXCC="291")],
                     eqsl_inbox=[_qso("K1AAA", DXCC="291")])
    result = engine.qsl_opportunities()
    assert result["summary"]["confirmed_dxcc"] == 0
    assert result["summary"]["pending_dxcc"] == 1


@pytest.mark.parametrize("error,expected", [
    ("WRL rate limit reached HTTP 429", "RATE_LIMIT"),
    ("HTTP 401 invalid key", "AUTH"),
    ("unsupported endpoint", "UNSUPPORTED"),
    ("409 duplicate QSO", "CONFLICT"),
    ("read timeout", "TRANSIENT"),
])
def test_provider_failure_classification(error, expected):
    assert _failure_type(error) == expected


def test_provider_exception_persists_and_success_resolves_it(tmp_path):
    store = IntegrityStore(root=tmp_path)
    store.provider_result("WRL", "HTTP 401 invalid API Key")
    store.provider_result("WRL", "HTTP 401 invalid API Key")
    assert store.errors()["WRL"]["failures"] == 2
    assert store.errors()["WRL"]["active"] == 1
    assert store.errors()["WRL"]["classification"] == "AUTH"
    store.provider_result("WRL", None)
    assert store.errors()["WRL"]["active"] == 0


def test_monitor_is_opt_in_and_never_starts_download_at_enable(tmp_path, monkeypatch):
    from app.services.integrity_monitor import IntegrityMonitor
    import app.services.integrity_monitor as module
    store = IntegrityStore(root=tmp_path)
    monkeypatch.setattr(module, "IntegrityStore", lambda: store)
    configured = IntegrityMonitor.configure(True, 6)
    assert configured["enabled"] is True
    assert configured["next_due_seconds"] > 10000
    assert IntegrityMonitor.tick()["reason"] == "not_due_or_disabled"
    disabled = IntegrityMonitor.configure(False, 12)
    assert disabled["enabled"] is False


def test_api_refuses_unconfirmed_assisted_writes_without_remote_calls():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.post("/api/integrity/apply", json={
        "target": "WRL", "signature": "deadbeefdeadbeef",
        "logical_ids": ["nonexistent"], "reason": "Teste sem autorização", "confirm": False,
    })
    assert resp.status_code == 422


def test_integrity_case_keys_do_not_depend_on_provider_snapshot_indexes(tmp_path):
    engine = _engine(tmp_path, [_qso("K1AAA"), _qso("K1BBB", "13:00:00")], wrl=[])
    before = {c["call"]: c["case_key"] for c in engine.report()["items"]}
    engine.workspace.hub.snapshots.save("QRZ", [_qso("K1BBB", "13:00:00"), _qso("K1AAA")],
                                        {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    after = {c["call"]: c["case_key"] for c in engine.report()["items"]}
    assert before == after
