import httpx
import pytest

from app.adapters.cloud_logs import CloudProviderError
from app.adapters.online_v8 import EQSLInboxAdapter


def _record(call: str, date: str = "20260913", time: str = "120000") -> str:
    return (
        f"<CALL:{len(call)}>{call}"
        f"<QSO_DATE:8>{date}"
        f"<TIME_ON:6>{time}"
        "<BAND:3>15M"
        "<MODE:3>FT8"
        "<QSL_SENT:1>Y"
        "<QSL_SENT_VIA:1>E"
        "<EOR>"
    )


def test_eqsl_inbox_html_control_page_is_never_parsed_as_adif():
    html_page = f"""
    <html><body>
      <h3>Your ADIF log file has been built</h3>
      <p>There were 3 records</p>
      <pre>{_record("BOGUS")}</pre>
      <input name="CALL" value="NOT_A_QSO">
      <a href="/downloadedfiles/PU2BRU_INBOX.adi">.ADI file</a>
      <a href="/downloadedfiles/PU2BRU_INBOX.txt">.TXT file</a>
    </body></html>
    """
    adif = (
        "<PROGRAMID:21>eQSL.cc DownloadInBox<ADIF_Ver:5>3.1.6<EOH>"
        + _record("K1ABC")
        + _record("W1XYZ", time="120100")
        + _record("PY2TEST", time="120200")
    )
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path.lower().endswith("/qslcard/downloadinbox.cfm"):
            assert request.url.params["Username"] == "PU2BRU"
            assert request.url.params["RcvdSince"] == "19000101"
            return httpx.Response(
                200,
                text=html_page,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        if request.url.path == "/downloadedfiles/PU2BRU_INBOX.adi":
            return httpx.Response(200, text=adif, headers={"content-type": "text/plain"})
        raise AssertionError(str(request.url))

    adapter = EQSLInboxAdapter(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )
    result = adapter.fetch_all()

    assert [row["CALL"] for row in result["records"]] == ["K1ABC", "W1XYZ", "PY2TEST"]
    assert all(row["EQSL_QSL_RCVD"] == "Y" for row in result["records"])
    assert "BOGUS" not in [row["CALL"] for row in result["records"]]
    assert result["metadata"]["download_strategy"] == "INBOX_ADIF_FILE"
    assert result["metadata"]["remote_reported_count"] == 3
    assert result["metadata"]["download_file"] == "PU2BRU_INBOX.adi"
    assert len(calls) == 2


def test_eqsl_inbox_rejects_incomplete_generated_file_and_preserves_snapshot_contract():
    html_page = """
    <html><body>
      <p>There were 2 records</p>
      <a href="/downloadedfiles/inbox.adi">.ADI file</a>
    </body></html>
    """

    def handler(request):
        if request.url.path.lower().endswith("/qslcard/downloadinbox.cfm"):
            return httpx.Response(200, text=html_page, headers={"content-type": "text/html"})
        if request.url.path == "/downloadedfiles/inbox.adi":
            return httpx.Response(200, text=_record("K1ABC"), headers={"content-type": "text/plain"})
        raise AssertionError(str(request.url))

    adapter = EQSLInboxAdapter(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()

    message = str(exc.value)
    assert "página informa 2 registros" in message
    assert "arquivo ADIF contém 1" in message
    assert "snapshot anterior foi preservado" in message


def test_eqsl_inbox_falls_back_to_txt_when_adi_download_fails():
    html_page = """
    <html><body>
      <p>There were 1 records</p>
      <a href="/downloadedfiles/inbox.adi">.ADI file</a>
      <a href="/downloadedfiles/inbox.txt">.TXT file</a>
    </body></html>
    """
    adif = "<PROGRAMID:21>eQSL.cc DownloadInBox<ADIF_Ver:5>3.1.6<EOH>" + _record("K1ABC")

    def handler(request):
        if request.url.path.lower().endswith("/qslcard/downloadinbox.cfm"):
            return httpx.Response(200, text=html_page, headers={"content-type": "text/html"})
        if request.url.path == "/downloadedfiles/inbox.adi":
            return httpx.Response(503, text="temporary failure")
        if request.url.path == "/downloadedfiles/inbox.txt":
            return httpx.Response(200, text=adif, headers={"content-type": "text/plain"})
        raise AssertionError(str(request.url))

    adapter = EQSLInboxAdapter(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()

    assert len(result["records"]) == 1
    assert result["records"][0]["CALL"] == "K1ABC"
    assert result["metadata"]["download_file"] == "inbox.txt"


def test_eqsl_inbox_reports_authentication_failure_from_html_page():
    def handler(request):
        return httpx.Response(
            200,
            text="<html><body>You are not yet logged in</body></html>",
            headers={"content-type": "text/html"},
        )

    adapter = EQSLInboxAdapter(
        {"username": "PU2BRU", "password": "bad"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudProviderError, match="credenciais"):
        adapter.fetch_all()


def test_eqsl_inbox_accepts_direct_adif_response():
    adif = "<PROGRAMID:21>eQSL.cc DownloadInBox<ADIF_Ver:5>3.1.6<EOH>" + _record("K1ABC")

    def handler(request):
        return httpx.Response(200, text=adif, headers={"content-type": "text/plain"})

    adapter = EQSLInboxAdapter(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()

    assert len(result["records"]) == 1
    assert result["records"][0]["CALL"] == "K1ABC"
    assert result["metadata"]["download_strategy"] == "DIRECT_ADIF"
