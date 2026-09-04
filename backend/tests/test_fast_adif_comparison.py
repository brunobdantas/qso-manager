from app.services.fast_adif_comparison_service import FastADIFComparisonService


def rec(**fields):
    parts = []
    for key, value in fields.items():
        text = str(value)
        parts.append(f"<{key}:{len(text)}>{text}")
    return " ".join(parts) + " <EOR>\n"


def test_fast_comparator_keeps_probable_duplicate_out_of_missing_list():
    wrl = "".join([
        rec(CALL="KB0XY", QSO_DATE="20260903", TIME_ON="230601", BAND="15m", FREQ="21.074", MODE="FT8", RST_SENT="-17", RST_RCVD="-08", GRIDSQUARE="EN41rn"),
        rec(CALL="KB0XY", QSO_DATE="20260903", TIME_ON="230602", BAND="15m", FREQ="21.074", MODE="FT8", RST_SENT="-17", RST_RCVD="-08", GRIDSQUARE="EN41rn"),
    ])
    qrz = rec(CALL="KB0XY", QSO_DATE="20260903", TIME_ON="230601", BAND="15m", FREQ="21.074", MODE="FT8", RST_SENT="-17", RST_RCVD="-08", GRIDSQUARE="EN41rn")
    result = FastADIFComparisonService().compare(wrl, qrz, "WRL", "QRZ", "FULL_EXPORT", "FULL_EXPORT")
    assert result["summary"]["probable_duplicates"] == 1
    assert result["summary"]["missing_in_b"] == 0
