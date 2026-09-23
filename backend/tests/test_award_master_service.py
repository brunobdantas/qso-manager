import pytest

from app.services.award_master_service import AwardMasterError, AwardMasterService, US_STATES


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
