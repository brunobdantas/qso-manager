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


def test_qrz_v505_validates_connection_with_status():
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


def test_qrz_v505_uses_canonical_all_only_for_full_download():
    calls = []
    adif = _record(123, "K1ABC") + _record(456, "W1XYZ")

    def handler(request):
        form = _form(request)
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D2")
        assert form["OPTION"] == "ALL"
        return httpx.Response(
            200,
            text="RESULT=OK&COUNT=2&LOGIDS=123,456&ADIF=" + quote_plus(adif),
        )

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert len(result["records"]) == 2
    assert result["metadata"]["strategy"] == "DIRECT_ALL"
    assert result["metadata"]["verified_record_count"] == 2
    fetches = [x for x in calls if x["ACTION"] == "FETCH"]
    assert [x["OPTION"] for x in fetches] == ["ALL"]


def test_qrz_v505_decodes_double_encoded_direct_adif():
    adif = _record(123)

    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        return httpx.Response(
            200,
            text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + quote_plus(quote_plus(adif)),
        )

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert result["records"][0]["CALL"] == "K1ABC"


def test_qrz_v505_falls_back_to_exact_documented_paging_when_all_fails():
    calls = []
    adif = _record(123)

    def handler(request):
        form = _form(request)
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D1")
        if form["OPTION"] == "ALL":
            return httpx.Response(200, text="RESULT=FAIL")
        assert form["OPTION"] == "MAX:250,AFTERLOGID:0"
        return httpx.Response(
            200,
            text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + quote_plus(adif),
        )

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert result["metadata"]["strategy"] == "PAGED_MINIMAL"
    assert len(result["records"]) == 1
    fetch_options = [x["OPTION"] for x in calls if x["ACTION"] == "FETCH"]
    assert fetch_options == ["ALL", "MAX:250,AFTERLOGID:0"]


def test_qrz_v505_paging_advances_from_response_logids():
    calls = []
    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=None,
    )
    adapter.PAGE_SIZE = 2

    def handler(request):
        form = _form(request)
        calls.append(form)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D3")
        if form["OPTION"] == "ALL":
            return httpx.Response(200, text="RESULT=FAIL")
        if form["OPTION"] == "MAX:2,AFTERLOGID:0":
            adif = _record(10, "K1ABC") + _record(20, "W1XYZ")
            return httpx.Response(200, text="RESULT=OK&COUNT=2&LOGIDS=10,20&ADIF=" + quote_plus(adif))
        if form["OPTION"] == "MAX:2,AFTERLOGID:21":
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=30&ADIF=" + quote_plus(_record(30, "N1ABC")))
        raise AssertionError(form["OPTION"])

    adapter.client.close()
    adapter.client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter._owns_client = True
    result = adapter.fetch_all()
    assert len(result["records"]) == 3
    assert result["metadata"]["pages"] == 2
    assert any(x.get("OPTION") == "MAX:2,AFTERLOGID:21" for x in calls)
    adapter.close()


def test_qrz_v505_reports_both_read_failures_without_blame_on_valid_key():
    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D21672")
        return httpx.Response(200, text="RESULT=FAIL")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    text = str(exc.value)
    assert "STATUS informa 21672 QSOs" in text
    assert "FETCH ALL" in text
    assert "PAGINAÇÃO" in text
    assert "não é necessário recadastrar a chave" in text
    assert "Confirme a Logbook API Access Key" not in text


def test_qrz_v505_rejects_direct_incomplete_download_and_preserves_snapshot():
    adif = _record(123)

    def handler(request):
        form = _form(request)
        if form["ACTION"] == "STATUS":
            return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D2")
        if form["OPTION"] == "ALL":
            return httpx.Response(200, text="RESULT=OK&COUNT=1&LOGIDS=123&ADIF=" + quote_plus(adif))
        return httpx.Response(200, text="RESULT=FAIL")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    assert "FETCH ALL retornou 1 QSOs, mas STATUS informa 2" in str(exc.value)
    assert "snapshot anterior foi preservado" in str(exc.value)


def test_qrz_v505_removes_accidental_whitespace_from_pasted_key():
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


def test_qrz_read_retries_transient_server_failure(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(_form(request))
        if len(attempts) < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, text="RESULT=OK&DATA=QSOS%3D10")

    monkeypatch.setattr("app.adapters.qrz_cloud_v501.time.sleep", lambda _: None)
    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.test_connection()
    assert result["ok"] is True
    assert len(attempts) == 3


def test_qrz_insert_never_retries_ambiguous_write_failure(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(_form(request))
        return httpx.Response(503, text="temporarily unavailable")

    monkeypatch.setattr("app.adapters.qrz_cloud_v501.time.sleep", lambda _: None)
    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError):
        adapter.add_qso({"CALL": "K1ABC", "QSO_DATE": "20260905", "TIME_ON": "123900"})
    assert len(attempts) == 1
    assert attempts[0]["ACTION"] == "INSERT"
