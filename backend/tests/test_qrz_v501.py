from urllib.parse import parse_qs, quote_plus

import httpx
import pytest

from app.adapters.cloud_logs import CloudProviderError
from app.adapters.qrz_cloud_v501 import QRZCloudAdapterV501


PAGE = "<CALL:5>K1ABC<QSO_DATE:8>20260904<TIME_ON:6>123900<BAND:3>20m<FREQ:6>14.074<MODE:3>FT8<APP_QRZLOG_LOGID:3>123<EOR>"


def _form(request):
    return {k: v[-1] for k, v in parse_qs(request.content.decode()).items()}


def test_qrz_v503_validates_connection_with_status():
    seen = {}

    def handler(request):
        seen.update(_form(request))
        return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D21672")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.test_connection()
    assert result["ok"] is True
    assert result["records"] == 21672
    assert seen["ACTION"] == "STATUS"


def test_qrz_v503_requests_adif_explicitly_and_verifies_count():
    calls = []

    def handler(request):
        form = _form(request)
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + quote_plus(PAGE))

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert len(result["records"]) == 1
    fetch = [x for x in calls if x["ACTION"] == "FETCH"][0]
    assert fetch["OPTION"] == "MAX:250,AFTERLOGID:0,TYPE:ADIF,STATUS:ALL"
    assert result["metadata"]["verified_record_count"] == 1
    assert result["metadata"]["remote_status_count"] == 1


def test_qrz_v503_decodes_double_encoded_adif():
    encoded_twice = quote_plus(quote_plus(PAGE))

    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + encoded_twice)

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert result["records"][0]["CALL"] == "K1ABC"


def test_qrz_v503_uses_logids_two_step_when_page_has_no_adif():
    calls = []

    def handler(request):
        form = _form(request)
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        option = form.get("OPTION", "")
        if option.startswith("LOGIDS:123"):
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + quote_plus(PAGE))
        if "TYPE:LOGIDS" in option:
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert len(result["records"]) == 1
    assert any("TYPE:LOGIDS" in x.get("OPTION", "") for x in calls)
    assert any(x.get("OPTION", "").startswith("LOGIDS:123") for x in calls)


def test_qrz_v503_never_accepts_silent_zero_when_status_is_nonzero():
    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D21672")
        return httpx.Response(200, text="RESULT=OK&COUNT=0&ADIF=")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    assert "21672" in str(exc.value)
    assert "snapshot anterior foi preservado" in str(exc.value)


def test_qrz_v503_removes_accidental_whitespace_from_pasted_key():
    captured = {}

    def handler(request):
        captured.update(_form(request))
        return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D0")

    adapter = QRZCloudAdapterV501(
        {"api_key": "  ABCD-0000-1111-2222\r\n"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter.test_connection()
    assert captured["KEY"] == "ABCD-0000-1111-2222"
