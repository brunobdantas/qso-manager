from app.services.adif_comparison_service import ADIFComparisonService


def rec(**fields):
    parts = []
    for key, value in fields.items():
        text = str(value)
        parts.append(f"<{key}:{len(text)}>{text}")
    return " ".join(parts) + " <EOR>\n"


def test_1239_tolerances_never_create_false_missing():
    qrz = rec(CALL="TEST1", QSO_DATE="20260903", TIME_ON="123900", BAND="15m", FREQ="21.076100", MODE="MFSK", SUBMODE="FT4", RST_SENT="-10", RST_RCVD="-12")
    wrl = rec(CALL="TEST1", QSO_DATE="20260903", TIME_ON="123920", BAND="15m", FREQ="21.076900", MODE="FT4", RST_SENT="-10", RST_RCVD="-12")
    result = ADIFComparisonService().compare(qrz, wrl, "QRZ", "WRL", "FULL_EXPORT", "FULL_EXPORT")
    assert result["summary"]["matched"] == 1
    assert result["summary"]["missing_in_a"] == 0
    assert result["summary"]["missing_in_b"] == 0


def test_best_one_to_one_match_wins_before_60_second_candidate():
    wrl = "".join([
        rec(CALL="DL2AKT", QSO_DATE="20260413", TIME_ON="143400", BAND="15m", FREQ="21.074", MODE="FT8", RST_SENT="-7", RST_RCVD="-20"),
        rec(CALL="DL2AKT", QSO_DATE="20260413", TIME_ON="143500", BAND="15m", FREQ="21.074", MODE="FT8"),
    ])
    qrz = rec(CALL="DL2AKT", QSO_DATE="20260413", TIME_ON="143500", BAND="15m", FREQ="21.074", MODE="FT8")
    result = ADIFComparisonService().compare(wrl, qrz, "WRL", "QRZ", "FULL_EXPORT", "FULL_EXPORT")
    assert result["summary"]["matched"] == 1
    assert result["summary"]["missing_in_b"] == 1
    assert result["missing_in_b"][0]["time"] == "14:34:00"
    assert result["missing_in_b"][0]["confidence"] == "HIGH"


def test_near_identical_same_source_record_is_probable_duplicate_not_missing():
    wrl = "".join([
        rec(CALL="KB0XY", QSO_DATE="20260903", TIME_ON="230601", BAND="15m", FREQ="21.074", MODE="FT8", RST_SENT="-17", RST_RCVD="-08", GRIDSQUARE="EN41rn"),
        rec(CALL="KB0XY", QSO_DATE="20260903", TIME_ON="230602", BAND="15m", FREQ="21.074", MODE="FT8", RST_SENT="-17", RST_RCVD="-08", GRIDSQUARE="EN41rn"),
    ])
    qrz = rec(CALL="KB0XY", QSO_DATE="20260903", TIME_ON="230601", BAND="15m", FREQ="21.074", MODE="FT8", RST_SENT="-17", RST_RCVD="-08", GRIDSQUARE="EN41rn")
    result = ADIFComparisonService().compare(wrl, qrz, "WRL", "QRZ", "FULL_EXPORT", "FULL_EXPORT")
    assert result["summary"]["matched"] == 1
    assert result["summary"]["probable_duplicates"] == 1
    assert result["summary"]["missing_in_b"] == 0


def test_partial_export_never_claims_high_confidence_missing():
    a = rec(CALL="PY2ABC", QSO_DATE="20260903", TIME_ON="120000", BAND="10m", FREQ="28.074", MODE="FT8")
    b = rec(CALL="OTHER", QSO_DATE="20260903", TIME_ON="130000", BAND="10m", FREQ="28.074", MODE="FT8")
    result = ADIFComparisonService().compare(a, b, "A", "B", "FULL_EXPORT", "PARTIAL_EXPORT")
    assert result["missing_in_b"][0]["confidence"] == "INSUFFICIENT_COVERAGE"
