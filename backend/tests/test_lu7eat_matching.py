"""Regression for LU7EAT Club Log generic PSK vs QRZ PSK31."""
from __future__ import annotations

from app.services.adif_comparison_service import ADIFComparisonService
from app.services.cloud_hub_fast_service import CloudHubService
from app.services.cloud_snapshot_store import CloudSnapshotStore
from app.services.credential_store import CredentialStore
from app.services.integrity_service import IntegrityService, IntegrityStore
from app.services.qso_manager_workspace import QSOManagerWorkspace


def qso(call="LU7EAT", date="2015-11-02", time="23:03:00",
        band="10m", mode="PSK31", freq="28.12", **fields):
    row = {
        "CALL": call, "QSO_DATE": date, "TIME_ON": time,
        "BAND": band, "MODE": mode,
    }
    if freq is not None:
        row["FREQ"] = freq
    row.update(fields)
    return row


def compare(qrz, clublog):
    comparator = ADIFComparisonService()
    return comparator._match(comparator._normalize(qrz, "QRZ"),
                             comparator._normalize(clublog, "CLUBLOG"))


def build_workspace(tmp_path, sources):
    root = tmp_path / "profile"
    snapshots = CloudSnapshotStore(root=root)
    for provider, records in sources.items():
        snapshots.save(provider, records, {"coverage": "API_FULL_SYNC"})
    QSOManagerWorkspace.invalidate_cache()
    hub = CloudHubService(credentials=CredentialStore(root=root), snapshots=snapshots)
    return QSOManagerWorkspace(hub=hub), IntegrityStore(root=root)


def test_lu7eat_2015_psk31_qrz_and_generic_psk_clublog_are_same_qso(tmp_path):
    qr = qso(NAME="Fernando Kler", GRIDSQUARE="GF05tg", RST_SENT="599",
             RST_RCVD="599", QSL_SENT="N", STATION_CALLSIGN="PU2BRU")
    cl = qso(mode="PSK", RST_SENT="599", RST_RCVD="599")
    wrl = qso(GRIDSQUARE="GF05", RST_SENT="599", RST_RCVD="599")
    eqsl = qso(mode="PSK", SUBMODE="PSK31", QSL_SENT="Y")
    hrdlog = qso(GRIDSQUARE="GF05TG")
    work, store = build_workspace(tmp_path, {
        "QRZ": [qr], "CLUBLOG": [cl], "WRL": [wrl],
        "EQSL": [eqsl], "HRDLOG": [hrdlog],
    })
    rows, _ = work._cached()
    assert len(rows) == 1, "All five providers represent one logical QSO"
    row = rows[0]
    assert set(row["providers"]) == {"QRZ", "CLUBLOG", "WRL", "EQSL", "HRDLOG"}
    assert row["missing_in"] == []
    assert row["difference_fields"] == [], "Grid precision/QSL delivery channels are not conflicts"
    engine = IntegrityService(workspace=work, store=store)
    report = engine.report(page_size=50)
    assert report["summary"]["providers"]["CLUBLOG"]["matched"] == 1
    assert report["summary"]["providers"]["CLUBLOG"]["missing"] == 0
    assert report["summary"]["providers"]["CLUBLOG"]["extra"] == 0
    assert not [c for c in report["items"] if c["provider"] == "CLUBLOG"]
    assert engine.reconcile_plan("CLUBLOG")["selected"] == 0


def test_lu7eat_2026_ft8_contact_stays_separate_from_2015_psk(tmp_path):
    qr = [qso(), qso(date="2026-04-20", time="21:46:00", mode="FT8", freq="28.074")]
    cl = [
        qso(mode="PSK"),
        qso(date="2026-04-20", time="21:46:00", mode="FT8", freq="28.074"),
    ]
    work, _ = build_workspace(tmp_path, {"QRZ": qr, "CLUBLOG": cl})
    rows, _ = work._cached()
    assert len(rows) == 2
    assert all("CLUBLOG" in row["providers"] for row in rows)
    assert len({(row["date"], row["mode"]) for row in rows}) == 2


def test_generic_psk_with_missing_frequency_requires_exact_utc_second():
    matched, _, _, _ = compare([qso()], [qso(mode="PSK", freq=None)])
    assert len(matched) == 1
    matched, _, _, _ = compare([qso()], [qso(mode="PSK", freq=None, time="23:03:01")])
    assert len(matched) == 0
    matched, _, _, _ = compare([qso()], [qso(mode="PSK", band="20m")])
    assert len(matched) == 0


def test_distinct_specific_psk31_and_psk63_never_auto_match():
    for freq in ("28.12", None):
        matched, _, _, _ = compare([qso(mode="PSK31", freq=freq)],
                                   [qso(mode="PSK63", freq=freq)])
        assert matched == []


def test_generic_psk_ambiguous_with_two_specific_modes_requires_review():
    qrz = [
        qso(mode="PSK31"),
        qso(mode="PSK63"),
    ]
    matched, unmatched_qrz, unmatched_cl, reviews = compare(qrz, [qso(mode="PSK")])
    assert matched == []
    assert len(unmatched_qrz) == 2
    assert len(unmatched_cl) == 1
    assert any(x[2].get("reason") == "ambiguous_generic_psk" for x in reviews)


def test_generic_psk_requires_strong_frequency_evidence_when_times_differ():
    matched, _, _, _ = compare(
        [qso(mode="PSK31", freq="28.12")],
        [qso(mode="PSK", freq="28.14", time="23:03:01")],
    )
    assert matched == []


def test_generic_psk_and_specific_digital_ft8_are_not_equated():
    matched, _, _, _ = compare([qso(mode="FT8")], [qso(mode="PSK")])
    assert matched == []
