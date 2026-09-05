from urllib.parse import parse_qs

import httpx

from app.adapters.qrz_cloud_v501 import QRZCloudAdapterV501


def test_qrz_v502_validates_connection_with_status_not_fetch():
    seen = {}

    def handler(request):
        seen.update({k: v[-1] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D21668")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.test_connection()
    assert result["ok"] is True
    assert result["records"] == 21668
    assert seen["ACTION"] == "STATUS"
    assert "OPTION" not in seen


def test_qrz_v502_uses_documented_minimal_paging_options():
    calls = []
    page = "<CALL:5>K1ABC<QSO_DATE:8>20260904<TIME_ON:6>123900<BAND:3>20m<FREQ:6>14.074<MODE:3>FT8<APP_QRZLOG_LOGID:3>123<EOR>"

    def handler(request):
        form = {k: v[-1] for k, v in parse_qs(request.content.decode()).items()}
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&ADIF=" + page.replace("<", "%3C").replace(">", "%3E"))

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert len(result["records"]) == 1
    fetch = [x for x in calls if x["ACTION"] == "FETCH"][0]
    assert fetch["OPTION"] == "MAX:250,AFTERLOGID:0"
    assert result["metadata"]["strategy"] == "PAGED"


def test_qrz_v502_falls_back_to_all_when_first_paged_fetch_fails():
    calls = []
    page = "<CALL:5>K1ABC<QSO_DATE:8>20260904<TIME_ON:6>123900<BAND:3>20m<FREQ:6>14.074<MODE:3>FT8<EOR>"

    def handler(request):
        form = {k: v[-1] for k, v in parse_qs(request.content.decode()).items()}
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        if form.get("OPTION") == "MAX:250,AFTERLOGID:0":
            return httpx.Response(200, text="RESULT=FAIL")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&ADIF=" + page.replace("<", "%3C").replace(">", "%3E"))

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert len(result["records"]) == 1
    assert result["metadata"]["strategy"] == "ALL_FALLBACK"
    assert any(x.get("OPTION") == "ALL,TYPE:ADIF,STATUS:ALL" for x in calls)


def test_qrz_v502_removes_accidental_whitespace_from_pasted_key():
    captured = {}

    def handler(request):
        captured.update({k: v[-1] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D0")

    adapter = QRZCloudAdapterV501(
        {"api_key": "  ABCD-0000-1111-2222\r\n"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter.test_connection()
    assert captured["KEY"] == "ABCD-0000-1111-2222"
