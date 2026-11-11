"""Regression coverage for v1.1.4 usability and comparison semantics."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.frequency_normalization import normalize_frequency_mhz
from app.services.qso_manager_workspace import QSOManagerWorkspace
from app.services.source_freshness import classify_snapshot_freshness
from app.services.v9_product_service import V9ProductService


def _service(tmp_path: Path) -> V9ProductService:
    return V9ProductService(
        credentials=CredentialStore(root=tmp_path),
        snapshots=CloudSnapshotStore(root=tmp_path),
    )


def _qso(call: str, time_on: str, **extra):
    return {
        "CALL": call,
        "QSO_DATE": "2026-11-10",
        "TIME_ON": time_on,
        "BAND": "12M",
        "MODE": "FT8",
        **extra,
    }


def test_frequency_normalization_repairs_only_band_backed_factor_1000():
    assert normalize_frequency_mhz("0.0249", "12M") == (24.9, True)
    assert normalize_frequency_mhz("24915", "12M") == (24.915, True)
    assert normalize_frequency_mhz("24.915", "12M") == (24.915, False)
    # 0.475 MHz is already valid on 630 m and must never be multiplied.
    assert normalize_frequency_mhz("0.475", "630M") == (0.475, False)
    # Without a declared known band, the application preserves the source.
    assert normalize_frequency_mhz("0.0249", "") == (0.0249, False)


def test_real_eqsl_rounded_ghz_shape_matches_qrz_with_exact_utc(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [_qso("EA5GMC", "18:31:00", FREQ="24.915")])
    service.snapshots.save("EQSL", [_qso("EA5GMC", "18:31:00", FREQ="0.0249")])
    QSOManagerWorkspace.invalidate_cache()

    result = service.log(page=1, page_size=10)
    assert result["total"] == 1
    row = result["items"][0]
    assert row["providers"] == ["QRZ", "EQSL"]
    assert row["missing_in"] == []


def test_unit_repair_does_not_merge_different_modes_or_loose_times(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [_qso("EA5GMC", "18:31:00", FREQ="24.915")])
    service.snapshots.save("EQSL", [
        _qso("EA5GMC", "18:31:00", FREQ="0.0249", MODE="FT4"),
        _qso("EA5GMC", "18:34:00", FREQ="0.0249"),
    ])
    QSOManagerWorkspace.invalidate_cache()

    assert service.log(page=1, page_size=10)["total"] == 3


def test_source_freshness_uses_age_and_relative_lag():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    summaries = {
        "QRZ": {"downloaded_at": (now - timedelta(hours=1)).isoformat()},
        "WRL": {"downloaded_at": (now - timedelta(hours=9)).isoformat()},
        "CLUBLOG": {"downloaded_at": None},
    }
    result = classify_snapshot_freshness(summaries, summaries, now=now)
    assert result["QRZ"]["state"] == "CURRENT"
    assert result["WRL"]["state"] == "STALE"
    assert result["WRL"]["lag_hours"] == 8.0
    assert result["WRL"]["stale_by_lag"] is True
    assert result["CLUBLOG"]["state"] == "NOT_LOADED"


def test_issues_are_server_paginated_and_searchable(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [
        _qso("K1AAA", "10:00:00", FREQ="24.915"),
        _qso("K2BBB", "10:01:00", FREQ="24.915"),
        _qso("K3CCC", "10:02:00", FREQ="24.915"),
    ])
    service.snapshots.save("WRL", [])
    QSOManagerWorkspace.invalidate_cache()

    second = service.issues(limit=1, offset=1, kind="MISSING")
    assert second["total"] == 3
    assert second["filtered_total"] == 3
    assert len(second["items"]) == 1
    assert second["offset"] == 1
    searched = service.issues(limit=10, q="K2BBB")
    assert searched["filtered_total"] == 1
    assert searched["items"][0]["call"] == "K2BBB"


def test_missing_in_stale_snapshot_waits_for_refresh(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.snapshots.save("QRZ", [_qso("K1AAA", "10:00:00", FREQ="24.915")])
    service.snapshots.save("WRL", [])

    def freshness(_summaries, providers):
        return {
            provider: {
                "state": "STALE" if provider == "WRL" else "CURRENT",
                "age_hours": 48.0 if provider == "WRL" else 1.0,
                "lag_hours": 47.0 if provider == "WRL" else 0.0,
                "stale_by_age": provider == "WRL",
                "stale_by_lag": provider == "WRL",
            }
            for provider in providers
        }

    monkeypatch.setattr(
        "app.services.qso_manager_workspace.classify_snapshot_freshness",
        freshness,
    )
    QSOManagerWorkspace.invalidate_cache()
    row = service.log(page=1, page_size=10)["items"][0]
    assert row["stale_missing_in"] == ["WRL"]
    assert row["actionable_missing_in"] == []
    issues = service.issues(limit=10)
    assert issues["total"] == 0
    assert issues["counts"]["awaiting_refresh"] == 1


def test_qsl_proposals_are_paged_filtered_and_searched(tmp_path, monkeypatch):
    service = _service(tmp_path)
    proposals = [
        {
            "service": "EQSL" if index % 2 == 0 else "LOTW",
            "qso": {"index": index, "call": f"K{index:02d}TEST"},
            "changes": {"QSL_RCVD": "Y"},
            "reason": "evidence",
        }
        for index in range(25)
    ]
    monkeypatch.setattr(service, "qsl_analysis", lambda: {
        "ready": True,
        "summary": {"actionable_proposals": 25},
        "proposals": proposals,
    })

    page = service.qsl_page(page=2, page_size=10)
    assert page["pagination"] == {
        "page": 2,
        "page_size": 10,
        "pages": 3,
        "total": 25,
        "filtered_total": 25,
    }
    assert len(page["proposals"]) == 10
    eqsl = service.qsl_page(page=1, page_size=10, service="eqsl")
    assert eqsl["pagination"]["filtered_total"] == 13
    assert all(item["service"] == "EQSL" for item in eqsl["proposals"])
    searched = service.qsl_page(page=1, page_size=10, q="K07TEST")
    assert [item["qso"]["call"] for item in searched["proposals"]] == ["K07TEST"]


def test_provider_filters_accept_human_labels(tmp_path):
    service = _service(tmp_path)
    service.snapshots.save("WRL", [_qso("K1ABC", "11:00:00", FREQ="24.915")])
    QSOManagerWorkspace.invalidate_cache()
    assert service.log(provider="World Radio League", page=1, page_size=10)["total"] == 1

