import pytest

from app.services.award_master_service import AwardMasterError, AwardMasterService, US_STATES
from app.services.cloud_snapshot_store import CloudSnapshotStore


def adif_record(**fields):
    parts = []
    for key, value in fields.items():
        text = str(value)
        parts.append(f"<{key}:{len(text)}>{text}")
    return "\n".join(parts) + "\n<EOR>\n"


def adif(*records):
    return "<ADIF_VER:5>3.1.4\n<EOH>\n" + "".join(records)


def test_master_preserves_qrz_enrichment_and_lotw_award_authority():
    qrz = adif(adif_record(
        CALL="AC1RI", QSO_DATE="20260329", TIME_ON="222500", BAND="12M", MODE="FT8",
        FREQ="24.9171", STATE="VT", GRIDSQUARE="FN34MQ", IOTA="NA-001",
        LOTW_QSL_RCVD="Y",
    ))
    lotw = adif(adif_record(
        CALL="AC1RI", QSO_DATE="20260329", TIME_ON="222500", BAND="12M", MODE="FT8",
        FREQ="24.91710", STATE="VT", GRIDSQUARE="FN34", DXCC="291",
        COUNTRY="UNITED STATES OF AMERICA", QSL_RCVD="Y", QSLRDATE="20260330",
    ))

    result = AwardMasterService().build(qrz, lotw)
    report = result["report"]
    output = result["content"]

    assert report["safe_to_export"] is True
    assert report["merge"]["matched_pairs"] == 1
    assert report["coverage"]["master"]["ft8_12m_states"] == 1
    assert "<STATE:2>VT" in output
    assert "<GRIDSQUARE:6>FN34MQ" in output
    assert "<IOTA:6>NA-001" in output
    assert "<DXCC:3>291" in output
    assert "<LOTW_QSL_RCVD:1>Y" in output
    assert "<LOTW_QSLRDATE:8>20260330" in output
    assert "<APP_QSOMGR_SOURCES:8>QRZ,LOTW" in output


def test_master_never_silently_merges_ambiguous_near_time_qsos():
    qrz = adif(
        adif_record(CALL="K1ABC", QSO_DATE="20260901", TIME_ON="120000", BAND="15M", MODE="FT8", FREQ="21.074"),
        adif_record(CALL="K1ABC", QSO_DATE="20260901", TIME_ON="120100", BAND="15M", MODE="FT8", FREQ="21.074"),
    )
    lotw = adif(
        adif_record(CALL="K1ABC", QSO_DATE="20260901", TIME_ON="120030", BAND="15M", MODE="FT8", FREQ="21.074"),
        adif_record(CALL="K1ABC", QSO_DATE="20260901", TIME_ON="120130", BAND="15M", MODE="FT8", FREQ="21.074"),
    )

    service = AwardMasterService()
    result = service.build(qrz, lotw)

    assert result["report"]["safe_to_export"] is False
    assert result["report"]["merge"]["ambiguous_groups"] == 1
    assert result["report"]["merge"]["master_records"] == 4
    with pytest.raises(AwardMasterError):
        service.certified_export(qrz, lotw)


def test_master_preserves_all_50_ft8_12m_states():
    states = sorted(US_STATES)
    qrz_records = []
    lotw_records = []
    for i, state in enumerate(states):
        call = f"K{i:02d}ZZ"
        minute = i % 60
        hour = 10 + (i // 60)
        time_on = f"{hour:02d}{minute:02d}00"
        grid = f"FN{i % 10}{i % 10}AA"
        qrz_records.append(adif_record(
            CALL=call, QSO_DATE="20260902", TIME_ON=time_on, BAND="12M", MODE="FT8",
            STATE=state, GRIDSQUARE=grid,
        ))
        lotw_records.append(adif_record(
            CALL=call, QSO_DATE="20260902", TIME_ON=time_on, BAND="12M", MODE="FT8",
            STATE=state, GRIDSQUARE=grid, DXCC="291", COUNTRY="UNITED STATES OF AMERICA",
            QSL_RCVD="Y",
        ))

    result = AwardMasterService().build(adif(*qrz_records), adif(*lotw_records))

    assert result["report"]["safe_to_export"] is True
    assert result["report"]["coverage"]["sources"]["QRZ"]["ft8_12m_states"] == 50
    assert result["report"]["coverage"]["sources"]["LOTW"]["ft8_12m_states"] == 50
    assert result["report"]["coverage"]["master"]["ft8_12m_states"] == 50
    assert result["report"]["coverage"]["regressions"] == []


def test_grid_conflict_for_us_qso_prefers_lotw_and_is_audited():
    qrz = adif(adif_record(
        CALL="N0MHL", QSO_DATE="20260726", TIME_ON="193000", BAND="12M", MODE="FT8",
        STATE="SD", GRIDSQUARE="DM33AA",
    ))
    lotw = adif(adif_record(
        CALL="N0MHL", QSO_DATE="20260726", TIME_ON="193000", BAND="12M", MODE="FT8",
        STATE="SD", GRIDSQUARE="EN12HV", DXCC="291", QSL_RCVD="Y",
    ))

    result = AwardMasterService().build(qrz, lotw)
    conflicts = result["report"]["conflicts"]["items"]

    assert "<GRIDSQUARE:6>EN12HV" in result["content"]
    assert any(item["field"] == "GRIDSQUARE" for item in conflicts)


def test_ft4_mfsk_submode_is_not_a_critical_identity_conflict():
    qrz = adif(adif_record(
        CALL="N8TR", QSO_DATE="20260124", TIME_ON="120000", BAND="12M",
        MODE="FT4", FREQ="24.915",
    ))
    lotw = adif(adif_record(
        CALL="N8TR", QSO_DATE="20260124", TIME_ON="120000", BAND="12M",
        MODE="MFSK", SUBMODE="FT4", FREQ="24.915", QSL_RCVD="Y",
    ))

    result = AwardMasterService().build(qrz, lotw)

    assert result["report"]["safe_to_export"] is True
    assert result["report"]["conflicts"]["critical"] == 0
    assert result["report"]["merge"]["matched_pairs"] == 1


def test_conflicting_grid_count_regression_is_audited_but_does_not_duplicate_qso():
    qrz = adif(
        adif_record(
            CALL="K1AAA", QSO_DATE="20260101", TIME_ON="120000", BAND="15M",
            MODE="FT8", STATE="MA", GRIDSQUARE="FN42AA",
        ),
        adif_record(
            CALL="K1BBB", QSO_DATE="20260101", TIME_ON="120100", BAND="15M",
            MODE="FT8", STATE="MA", GRIDSQUARE="FN43AA",
        ),
    )
    lotw = adif(
        adif_record(
            CALL="K1AAA", QSO_DATE="20260101", TIME_ON="120000", BAND="15M",
            MODE="FT8", STATE="MA", GRIDSQUARE="FN42BB", DXCC="291", QSL_RCVD="Y",
        ),
        adif_record(
            CALL="K1BBB", QSO_DATE="20260101", TIME_ON="120100", BAND="15M",
            MODE="FT8", STATE="MA", GRIDSQUARE="FN42CC", DXCC="291", QSL_RCVD="Y",
        ),
    )

    service = AwardMasterService()
    result = service.build(qrz, lotw)

    assert result["report"]["safe_to_export"] is True
    assert result["report"]["certification"] == "SAFE_WITH_WARNINGS"
    assert result["report"]["merge"]["master_records"] == 2
    assert result["report"]["coverage"]["master"]["grids4"] == 1
    assert result["report"]["coverage"]["warnings"][0]["metric"] == "grids4"
    assert result["report"]["coverage"]["blocking_regressions"] == []
    assert service.certified_export(qrz, lotw)["report"]["safe_to_export"] is True


def test_audit_csv_uses_complete_conflict_trail():
    qrz = adif(adif_record(
        CALL="K1ABC", QSO_DATE="20260101", TIME_ON="120000", BAND="15M",
        MODE="FT8", STATE="MA", GRIDSQUARE="FN42AA",
    ))
    lotw = adif(adif_record(
        CALL="K1ABC", QSO_DATE="20260101", TIME_ON="120000", BAND="15M",
        MODE="FT8", STATE="MA", GRIDSQUARE="FN31AA", DXCC="291", QSL_RCVD="Y",
    ))

    service = AwardMasterService()
    result = service.build(qrz, lotw)
    csv_text = service.audit_csv(result)

    assert "GRIDSQUARE" in csv_text
    assert "FN42AA" in csv_text
    assert "FN31AA" in csv_text



def test_master_can_use_loaded_snapshots_without_manual_upload(tmp_path):
    store = CloudSnapshotStore(root=tmp_path)
    qso = {
        "CALL": "N0MHL", "QSO_DATE": "2026-07-26", "TIME_ON": "19:30:00",
        "BAND": "12M", "MODE": "FT8", "STATE": "SD", "GRIDSQUARE": "EN12HV",
        "DXCC": "291", "COUNTRY": "UNITED STATES OF AMERICA",
    }
    store.save("QRZ", [dict(qso, IOTA="NA-001")], {"coverage": "API_FULL_SYNC"})
    store.save("LOTW", [dict(qso, QSL_RCVD="Y", LOTW_QSL_RCVD="Y")], {
        "coverage": "API_FULL_SYNC",
        "source": "lotw_qso_qsl_api",
        "confirmations_only": False,
        "accepted_qsos": 1,
        "confirmed_qsos": 1,
        "lotw_last_qso_rx": "2026-09-24 12:00:00",
        "lotw_last_qsl": "2026-09-24 12:30:00",
    })

    result = AwardMasterService().build_from_snapshots(store)

    assert result["report"]["source_mode"] == "snapshots"
    assert result["report"]["snapshot_sources"]["QRZ"]["records"] == 1
    assert result["report"]["snapshot_sources"]["LOTW"]["accepted_qsos"] == 1
    assert result["report"]["safe_to_export"] is True
    assert "<CALL:5>N0MHL" in result["content"]


def test_snapshot_master_rejects_legacy_confirmation_only_lotw(tmp_path):
    store = CloudSnapshotStore(root=tmp_path)
    store.save("QRZ", [{
        "CALL": "K1ABC", "QSO_DATE": "2026-09-24", "TIME_ON": "12:00:00",
        "BAND": "15M", "MODE": "FT8",
    }], {"coverage": "API_FULL_SYNC"})
    store.save("LOTW", [{
        "CALL": "K1ABC", "QSO_DATE": "2026-09-24", "TIME_ON": "12:00:00",
        "BAND": "15M", "MODE": "FT8", "QSL_RCVD": "Y",
    }], {"coverage": "API_FULL_SYNC", "confirmations_only": True})

    with pytest.raises(AwardMasterError, match="somente QSLs"):
        AwardMasterService().build_from_snapshots(store)

def test_iota_placeholders_are_omitted_from_master_and_metrics():
    qrz = adif(adif_record(
        CALL="PY2ABC", QSO_DATE="20260927", TIME_ON="120000", BAND="10M",
        MODE="FT8", IOTA="NONE",
    ))
    lotw = adif(adif_record(
        CALL="PY2ABC", QSO_DATE="20260927", TIME_ON="120000", BAND="10M",
        MODE="FT8",
    ))

    result = AwardMasterService().build(qrz, lotw)

    assert "<IOTA:" not in result["content"]
    assert result["report"]["coverage"]["master"]["iota"] == 0
    assert result["report"]["data_quality"]["iota_placeholder_removed"] == 1


def test_lotw_explicit_invalid_grid_removes_bad_qrz_grid_without_guessing():
    qrz = adif(adif_record(
        CALL="KQ4YWT", QSO_DATE="20260927", TIME_ON="121000", BAND="10M",
        MODE="FT8", DXCC="6", STATE="AK", CQZ="1", GRIDSQUARE="FM06",
    ))
    lotw = adif(adif_record(
        CALL="KQ4YWT", QSO_DATE="20260927", TIME_ON="121000", BAND="10M",
        MODE="FT8", DXCC="6", STATE="AK", CQZ="1", QSL_RCVD="Y",
        APP_LOTW_GRIDSQUARE_INVALID="FM06",
    ))

    result = AwardMasterService().build(qrz, lotw)

    assert "<GRIDSQUARE:" not in result["content"]
    assert result["report"]["data_quality"]["lotw_explicit_invalid_grid_removed"] == 1
    assert any(
        item["field"] == "GRIDSQUARE" and item["winner"] == "lotw_invalid"
        for item in result["report"]["conflicts"]["items"]
    )


def test_lotw_native_invalid_zone_flag_allows_explicit_correction():
    qrz = adif(adif_record(
        CALL="DO9SAM", QSO_DATE="20260528", TIME_ON="174000", BAND="15M",
        MODE="FT8", DXCC="230", GRIDSQUARE="JO61", CQZ="34",
    ))
    lotw = adif(adif_record(
        CALL="DO9SAM", QSO_DATE="20260528", TIME_ON="174000", BAND="15M",
        MODE="FT8", DXCC="230", GRIDSQUARE="JO61", CQZ="14", QSL_RCVD="Y",
        APP_LOTW_CQZ_INVALID="34", APP_LOTW_CQZ_INFERRED="Y",
    ))

    result = AwardMasterService().build(qrz, lotw)

    assert "<CQZ:2>14" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:14>LOTW_CORRECTED" in result["content"]
    assert result["report"]["data_quality"]["lotw_explicit_invalid_cqz"] == 1


def test_unexplained_zone_conflict_at_same_location_preserves_qrz_and_audits():
    qrz = adif(adif_record(
        CALL="IT9LCC", QSO_DATE="20260927", TIME_ON="122000", BAND="12M",
        MODE="FT8", DXCC="248", GRIDSQUARE="JM78SF", CQZ="15", ITUZ="28",
    ))
    lotw = adif(adif_record(
        CALL="IT9LCC", QSO_DATE="20260927", TIME_ON="122000", BAND="12M",
        MODE="FT8", DXCC="248", GRIDSQUARE="JM78SF", CQZ="33", ITUZ="37",
        QSL_RCVD="Y",
    ))

    result = AwardMasterService().build(qrz, lotw)

    assert "<CQZ:2>15" in result["content"]
    assert "<ITUZ:2>28" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:10>QRZ_REVIEW" in result["content"]
    assert any(
        item["field"] == "CQZ" and item["winner"] == "qrz_review"
        for item in result["report"]["conflicts"]["items"]
    )


def test_confirmed_lotw_history_can_normalize_qrz_only_zone_with_two_observations():
    qrz = adif(
        adif_record(
            CALL="DL1XYZ", QSO_DATE="20260920", TIME_ON="100000", BAND="10M",
            MODE="FT8", DXCC="230", GRIDSQUARE="JO61AA", CQZ="14", ITUZ="28",
        ),
        adif_record(
            CALL="DL1XYZ", QSO_DATE="20260921", TIME_ON="100000", BAND="12M",
            MODE="FT8", DXCC="230", GRIDSQUARE="JO61AA", CQZ="14", ITUZ="28",
        ),
        adif_record(
            CALL="DL1XYZ", QSO_DATE="20260922", TIME_ON="100000", BAND="15M",
            MODE="FT8", DXCC="230", GRIDSQUARE="JO61AA", CQZ="34", ITUZ="14",
        ),
    )
    lotw = adif(
        adif_record(
            CALL="DL1XYZ", QSO_DATE="20260920", TIME_ON="100000", BAND="10M",
            MODE="FT8", DXCC="230", GRIDSQUARE="JO61AA", CQZ="14", ITUZ="28",
            QSL_RCVD="Y",
        ),
        adif_record(
            CALL="DL1XYZ", QSO_DATE="20260921", TIME_ON="100000", BAND="12M",
            MODE="FT8", DXCC="230", GRIDSQUARE="JO61AA", CQZ="14", ITUZ="28",
            QSL_RCVD="Y",
        ),
    )

    result = AwardMasterService().build(qrz, lotw)

    assert result["content"].count("<CQZ:2>14") == 3
    assert result["content"].count("<ITUZ:2>28") == 3
    assert result["report"]["data_quality"]["cqz_normalized_by_same_call_lotw_history"] == 1
    assert result["report"]["data_quality"]["ituz_normalized_by_same_call_lotw_history"] == 1


def test_qrz_only_plausible_grid_is_never_removed_without_source_native_evidence():
    qrz = adif(adif_record(
        CALL="K2IDA", QSO_DATE="20260927", TIME_ON="123000", BAND="15M",
        MODE="FT8", DXCC="202", COUNTRY="Puerto Rico", GRIDSQUARE="FK68KJ", CQZ="8",
    ))
    lotw = adif(adif_record(
        CALL="K2IDA", QSO_DATE="20260927", TIME_ON="123000", BAND="15M",
        MODE="FT8",
    ))

    result = AwardMasterService().build(qrz, lotw)

    assert "<GRIDSQUARE:6>FK68KJ" in result["content"]
    assert "<CQZ:1>8" in result["content"]

def test_qrz_lotw_zone_consensus_is_never_overridden_by_other_calls_history():
    qrz = adif(
        adif_record(
            CALL="W3GLH", QSO_DATE="20150531", TIME_ON="200500", BAND="10M",
            MODE="SSB", DXCC="291", GRIDSQUARE="EN91VC", CQZ="5", ITUZ="8",
        ),
    )
    lotw = adif(
        adif_record(
            CALL="W3GLH", QSO_DATE="20150531", TIME_ON="200500", BAND="10M",
            MODE="SSB", DXCC="291", GRIDSQUARE="EN91VC", CQZ="05", ITUZ="08",
            QSL_RCVD="Y",
        ),
        adif_record(
            CALL="K3AAA", QSO_DATE="20260101", TIME_ON="100000", BAND="10M",
            MODE="FT8", DXCC="291", GRIDSQUARE="EN91AA", CQZ="4", ITUZ="8",
            QSL_RCVD="Y",
        ),
        adif_record(
            CALL="K3BBB", QSO_DATE="20260102", TIME_ON="100000", BAND="10M",
            MODE="FT8", DXCC="291", GRIDSQUARE="EN91BB", CQZ="4", ITUZ="8",
            QSL_RCVD="Y",
        ),
    )

    result = AwardMasterService().build(qrz, lotw)

    assert "<CQZ:1>5" in result["content"]
    assert "<ITUZ:1>8" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:9>CONSENSUS" in result["content"]
    assert result["report"]["data_quality"].get("cqz_normalized_by_same_call_lotw_history", 0) == 0


def test_cross_callsign_dxcc_grid_history_never_changes_qrz_only_zone():
    qrz = adif(adif_record(
        CALL="K8FER", QSO_DATE="20150606", TIME_ON="211900", BAND="12M",
        MODE="PSK63", DXCC="291", GRIDSQUARE="EM88VK", CQZ="5", ITUZ="8",
    ))
    lotw = adif(
        adif_record(
            CALL="K8AAA", QSO_DATE="20260101", TIME_ON="100000", BAND="12M",
            MODE="FT8", DXCC="291", GRIDSQUARE="EM88AA", CQZ="4", ITUZ="8",
            QSL_RCVD="Y",
        ),
        adif_record(
            CALL="K8BBB", QSO_DATE="20260102", TIME_ON="100000", BAND="12M",
            MODE="FT8", DXCC="291", GRIDSQUARE="EM88BB", CQZ="4", ITUZ="8",
            QSL_RCVD="Y",
        ),
    )

    result = AwardMasterService().build(qrz, lotw)

    assert "<CQZ:1>5" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:3>QRZ" in result["content"]
    assert result["report"]["data_quality"].get("cqz_normalized_by_same_call_lotw_history", 0) == 0


def test_zone_leading_zero_is_equivalent_source_consensus():
    qrz = adif(adif_record(
        CALL="KF5SFJ", QSO_DATE="20150606", TIME_ON="212600", BAND="12M",
        MODE="PSK63", DXCC="291", GRIDSQUARE="EM50LJ", CQZ="4", ITUZ="7",
    ))
    lotw = adif(adif_record(
        CALL="KF5SFJ", QSO_DATE="20150606", TIME_ON="212600", BAND="12M",
        MODE="PSK63", DXCC="291", GRIDSQUARE="EM50LJ", CQZ="04", ITUZ="07",
        QSL_RCVD="Y",
    ))

    result = AwardMasterService().build(qrz, lotw)

    assert "<CQZ:1>4" in result["content"]
    assert "<ITUZ:1>7" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:9>CONSENSUS" in result["content"]
    assert "<APP_QSOMGR_ITUZ_SOURCE:9>CONSENSUS" in result["content"]
    zone_conflicts = [
        item for item in result["report"]["conflicts"]["items"]
        if item.get("field") in {"CQZ", "ITUZ"}
    ]
    assert zone_conflicts == []

def test_cross_callsign_geo_consensus_corrects_only_qrz_derived_grid4_zone_with_five_confirmations():
    qrz = adif(adif_record(
        CALL="KK9AWA", QSO_DATE="20260422", TIME_ON="001000", BAND="10M",
        MODE="FT8", DXCC="291", GRIDSQUARE="EN52", CQZ="37", ITUZ="99",
    ))
    lotw_rows = []
    for i, call in enumerate(("K9A", "K9B", "K9C", "K9D", "K9E")):
        lotw_rows.append(adif_record(
            CALL=call, QSO_DATE=f"20260{1+i}01", TIME_ON="100000", BAND="10M",
            MODE="FT8", DXCC="291", GRIDSQUARE="EN52", CQZ="4", ITUZ="8",
            QSL_RCVD="Y",
        ))

    result = AwardMasterService().build(qrz, adif(*lotw_rows))

    assert "<CQZ:1>4" in result["content"]
    assert "<ITUZ:1>8" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:18>LOTW_GEO_CONSENSUS" in result["content"]
    assert "<APP_QSOMGR_ITUZ_SOURCE:18>LOTW_GEO_CONSENSUS" in result["content"]
    assert result["report"]["data_quality"]["cqz_normalized_by_lotw_geo_consensus"] == 1
    assert result["report"]["data_quality"]["ituz_normalized_by_lotw_geo_consensus"] == 1


def test_cross_callsign_geo_consensus_never_overrides_qrz_lotw_consensus_even_with_five_confirmations():
    qrz = adif(adif_record(
        CALL="W3GLH", QSO_DATE="20150531", TIME_ON="200500", BAND="10M",
        MODE="SSB", DXCC="291", GRIDSQUARE="EN91VC", CQZ="5", ITUZ="8",
    ))
    lotw_rows = [
        adif_record(
            CALL="W3GLH", QSO_DATE="20150531", TIME_ON="200500", BAND="10M",
            MODE="SSB", DXCC="291", GRIDSQUARE="EN91VC", CQZ="05", ITUZ="08",
            QSL_RCVD="Y",
        )
    ]
    for i, call in enumerate(("K3A", "K3B", "K3C", "K3D", "K3E")):
        lotw_rows.append(adif_record(
            CALL=call, QSO_DATE=f"20260{1+i}02", TIME_ON="100000", BAND="10M",
            MODE="FT8", DXCC="291", GRIDSQUARE="EN91", CQZ="4", ITUZ="8",
            QSL_RCVD="Y",
        ))

    result = AwardMasterService().build(qrz, adif(*lotw_rows))

    assert "<CQZ:1>5" in result["content"]
    assert "<ITUZ:1>8" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:9>CONSENSUS" in result["content"]
    assert result["report"]["data_quality"].get("cqz_normalized_by_lotw_geo_consensus", 0) == 0


def test_grid6_geo_consensus_requires_only_two_unanimous_confirmations_for_qrz_derived_zone():
    qrz = adif(adif_record(
        CALL="CX2JO", QSO_DATE="20260705", TIME_ON="134400", BAND="15M",
        MODE="FT8", DXCC="144", GRIDSQUARE="GF18AO", CQZ="2", ITUZ="1",
    ))
    lotw = adif(
        adif_record(
            CALL="CX1AA", QSO_DATE="20260101", TIME_ON="100000", BAND="15M",
            MODE="FT8", DXCC="144", GRIDSQUARE="GF18AO", CQZ="13", ITUZ="14",
            QSL_RCVD="Y",
        ),
        adif_record(
            CALL="CX2BB", QSO_DATE="20260102", TIME_ON="100000", BAND="15M",
            MODE="FT8", DXCC="144", GRIDSQUARE="GF18AO", CQZ="13", ITUZ="14",
            QSL_RCVD="Y",
        ),
    )

    result = AwardMasterService().build(qrz, lotw)

    assert "<CQZ:2>13" in result["content"]
    assert "<ITUZ:2>14" in result["content"]
    assert "<APP_QSOMGR_CQZ_SOURCE:18>LOTW_GEO_CONSENSUS" in result["content"]

