from urllib.parse import parse_qs, quote_plus

import httpx
import pytest

from app.adapters.cloud_logs import CloudProviderError
from app.adapters.qrz_cloud_v501 import QRZCloudAdapterV501


def _record(logid: int, call: str = "K1ABC") -> str:
    return (
        f"<CALL:{len(call)}>{call}"
        "<QSO_DATE:8>20260904<TIME_ON:6>123900<BAND:3>20m"
        "<FREQ:6>14.074<MODE:3>FT8"
        f"<APP_QRZLOG_LOGID:{len(str(logid))}>{logid}<EOR>"
    )


def _form(request):
    return {k: v[-1] for k, v in parse_qs(request.content.decode()).items()}


def test_qrz_v504_validates_connection_with_status():
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


def test_qrz_v504_uses_logid_manifest_and_never_afterlogid():
    calls = []
    adif = _record(123, "K1ABC") + _record(456, "W1XYZ")

    def handler(request):
        form = _form(request)
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D2")
        option = form.get("OPTION", "")
        if option == "ALL,TYPE:LOGIDS,STATUS:ALL":
            return httpx.Response(200, text="RESULT=OK&COUNT=2&LOGIDS=123,456")
        if option.startswith("LOGIDS:123+456"):
            return httpx.Response(200, text="RESULT=OK&COUNT=2&LOGIDS=123,456&ADIF=" + quote_plus(adif))
        raise AssertionError(option)

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert len(result["records"]) == 2
    assert result["metadata"]["strategy"] == "LOGID_MANIFEST_BATCHED"
    assert result["metadata"]["manifest_count"] == 2
    assert result["metadata"]["verified_record_count"] == 2
    assert not any("AFTERLOGID" in x.get("OPTION", "") for x in calls)
    assert any(x.get("OPTION") == "ALL,TYPE:LOGIDS,STATUS:ALL" for x in calls)


def test_qrz_v504_decodes_double_encoded_batch_adif():
    adif = _record(123)

    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        option = form.get("OPTION", "")
        if option == "ALL,TYPE:LOGIDS,STATUS:ALL":
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + quote_plus(quote_plus(adif)))

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert result["records"][0]["CALL"] == "K1ABC"


def test_qrz_v504_splits_exact_logid_batches():
    calls = []
    ids = [101, 102, 103]

    def handler(request):
        form = _form(request)
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D3")
        option = form.get("OPTION", "")
        if option == "ALL,TYPE:LOGIDS,STATUS:ALL":
            return httpx.Response(200, text="RESULT=OK&COUNT=3&LOGIDS=101,102,103")
        if option.startswith("LOGIDS:101+102"):
            adif = _record(101, "K1ABC") + _record(102, "W1XYZ")
            return httpx.Response(200, text="RESULT=OK&COUNT=2&LOGIDS=101,102&ADIF=" + quote_plus(adif))
        if option.startswith("LOGIDS:103"):
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=103&ADIF=" + quote_plus(_record(103, "N1ABC")))
        raise AssertionError(option)

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter.BATCH_SIZE = 2
    result = adapter.fetch_all()
    assert len(result["records"]) == 3
    assert result["metadata"]["batches"] == 2


def test_qrz_v504_rejects_incomplete_manifest():
    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D2")
        return httpx.Response(200, text="RESULT=OK&COUNT=2&LOGIDS=123")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    text = str(exc.value)
    assert "2 LOGIDs" in text
    assert "1 identificadores" in text
    assert "snapshot anterior foi preservado" in text


def test_qrz_v504_rejects_incomplete_exact_batch():
    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D2")
        option = form.get("OPTION", "")
        if option == "ALL,TYPE:LOGIDS,STATUS:ALL":
            return httpx.Response(200, text="RESULT=OK&COUNT=2&LOGIDS=123,456")
        return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + quote_plus(_record(123)))

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    assert "deveria retornar 2 QSOs" in str(exc.value)


def test_qrz_v504_never_accepts_silent_zero_when_status_is_nonzero():
    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D21672")
        return httpx.Response(200, text="RESULT=OK&COUNT=0&LOGIDS=")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    assert "21672" in str(exc.value)
    assert "manifesto retornou 0 LOGIDs" in str(exc.value)


def test_qrz_v504_removes_accidental_whitespace_from_pasted_key():
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
