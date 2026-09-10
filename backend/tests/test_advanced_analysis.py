from app.services.advanced_analysis_service import AdvancedAnalysisService


def adif_record(**fields):
    parts = []
    for key, value in fields.items():
        text = str(value)
        parts.append(f"<{key}:{len(text)}>{text}")
    return "".join(parts) + "<EOR>"


def source(name, *records, kind=None, coverage="FULL_EXPORT", assume_received=True):
    payload = {
        "content": "".join(records),
        "source": name,
        "filename": f"{name.lower()}.adi",
        "coverage": coverage,
        "assume_received": assume_received,
    }
    if kind:
        payload["kind"] = kind
    return payload


def test_multi_source_comparison_returns_detailed_findings_and_match_evidence():
    ref = source(
        "QRZ",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120000", BAND="20M", MODE="FT8", FREQ="14.074", RST_SENT="-10"),
        adif_record(CALL="K2BBB", QSO_DATE="20260901", TIME_ON="130000", BAND="20M", MODE="FT8", FREQ="14.074"),
    )
    wrl = source(
        "WRL",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120030", BAND="20M", MODE="FT8", FREQ="14.074", RST_SENT="-12"),
    )
    hrd_history = source(
        "HRD_2026_09_01",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120000", BAND="20M", MODE="FT8", FREQ="14.074"),
        adif_record(CALL="K3CCC", QSO_DATE="20260901", TIME_ON="140000", BAND="20M", MODE="FT8", FREQ="14.074"),
    )

    result = AdvancedAnalysisService().compare_sources([ref, wrl, hrd_history])

    assert result["reference_source"] == "QRZ"
    assert result["summary"]["source_count"] == 3
    assert result["summary"]["matched_pairs"] == 2
    assert result["summary"]["presence_differences"] == 3
    assert result["summary"]["missing_in_reference"] == 1
    assert result["summary"]["missing_in_sources"] == 2
    assert result["summary"]["field_differences"] >= 1

    k3 = next(row for row in result["presence_differences"] if row["call"] == "K3CCC")
    assert k3["category"] == "MISSING_IN_REFERENCE"
    assert k3["confidence"] == "HIGH"

    wrl_match = next(row for row in result["matches"] if row["compared_source"] == "WRL")
    assert wrl_match["reference"]["call"] == "K1AAA"
    assert wrl_match["compared"]["call"] == "K1AAA"
    assert wrl_match["evidence"]["time_diff_seconds"] == 30
    assert "Δtempo 30 s" in wrl_match["reason"]


def test_qsl_analysis_consolidates_eqsl_lotw_and_preserves_date_safety():
    reference = source(
        "QRZ",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120000", BAND="20M", MODE="FT8", FREQ="14.074"),
        adif_record(CALL="K2BBB", QSO_DATE="20260902", TIME_ON="130000", BAND="20M", MODE="FT8", FREQ="14.074", EQSL_QSL_RCVD="Y", EQSL_QSLRDATE="20260815"),
    )
    eqsl = source(
        "EQSL_INBOX",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120010", BAND="20M", MODE="FT8", FREQ="14.074", EQSL_QSLRDATE="20260905"),
        adif_record(CALL="K2BBB", QSO_DATE="20260902", TIME_ON="130000", BAND="20M", MODE="FT8", FREQ="14.074", EQSL_QSLRDATE="20260816"),
        adif_record(CALL="K4DDD", QSO_DATE="20260903", TIME_ON="150000", BAND="20M", MODE="FT8", FREQ="14.074", EQSL_QSLRDATE="20260907"),
        kind="EQSL",
    )
    lotw = source(
        "LOTW_REPORT",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120000", BAND="20M", MODE="FT8", FREQ="14.074", LOTW_QSLRDATE="20260906"),
        adif_record(CALL="K2BBB", QSO_DATE="20260902", TIME_ON="130000", BAND="20M", MODE="FT8", FREQ="14.074"),
        kind="LOTW",
    )

    result = AdvancedAnalysisService().analyze_qsl(reference, [eqsl, lotw])

    assert result["summary"]["matched_confirmation_groups"] == 4
    assert result["summary"]["unmatched_evidence"] == 1
    assert result["policy"]["qso_date_used_as_qsl_date"] is False
    assert result["policy"]["existing_dates_overwritten"] is False

    k1_eqsl = next(p for p in result["proposals"] if p["qso"]["call"] == "K1AAA" and p["service"] == "EQSL")
    assert k1_eqsl["changes"]["EQSL_QSL_RCVD"] == "Y"
    assert k1_eqsl["changes"]["EQSL_QSLRDATE"] == "2026-09-05"

    k1_lotw = next(p for p in result["proposals"] if p["qso"]["call"] == "K1AAA" and p["service"] == "LOTW")
    assert k1_lotw["changes"]["LOTW_QSL_RCVD"] == "Y"
    assert k1_lotw["changes"]["LOTW_QSLRDATE"] == "2026-09-06"

    k2_lotw = next(p for p in result["proposals"] if p["qso"]["call"] == "K2BBB" and p["service"] == "LOTW")
    assert k2_lotw["changes"] == {"LOTW_QSL_RCVD": "Y"}
    assert k2_lotw["evidence_date"] is None
    assert "QSO_DATE não será usado" in k2_lotw["reason"]

    conflict = next(c for c in result["conflicts"] if c["qso"]["call"] == "K2BBB" and c["service"] == "EQSL")
    assert conflict["current_value"] == "2026-08-15"
    assert conflict["evidence_value"] == "2026-08-16"


def test_qsl_evidence_can_require_explicit_received_flag():
    reference = source(
        "QRZ",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120000", BAND="20M", MODE="FT8"),
    )
    evidence = source(
        "CUSTOM",
        adif_record(CALL="K1AAA", QSO_DATE="20260901", TIME_ON="120000", BAND="20M", MODE="FT8", QSL_RCVD="N"),
        kind="PAPER",
        assume_received=False,
    )

    result = AdvancedAnalysisService().analyze_qsl(reference, [evidence])
    assert result["proposals"] == []
    assert result["confirmation_matrix"] == []
