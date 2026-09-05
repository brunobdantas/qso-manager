import httpx
import pytest

from app.adapters.cloud_logs import CloudProviderError
from app.adapters.eqsl_cloud_v510 import EQSLCloudAdapterV510


def _record(call: str, date: str = "20260904", time: str = "123900") -> str:
    return f"<CALL:{len(call)}>{call}<QSO_DATE:8>{date}<TIME_ON:6>{time}<BAND:3>20m<MODE:3>FT8<EOR>"


def test_eqsl_html_control_page_follows_generated_adi_and_ignores_embedded_adif_like_markup():
    html_page = f"""
    <html><body>
      <p>Your ADIF log file has been built</p>
      <p>There were 2 records</p>
      <pre>{_record('FAKE1')}</pre>
      <a href="/downloadedfiles/PU2BRU_TEST.adi">.ADI file</a>
    </body></html>
    """
    adif = _record("K1ABC") + _record("W1XYZ", time="124000")

    def handler(request):
        if request.url.path.lower().endswith("downloadadif.cfm"):
            return httpx.Response(200, text=html_page, headers={"content-type": "text/html; charset=utf-8"})
        if request.url.path == "/downloadedfiles/PU2BRU_TEST.adi":
            return httpx.Response(200, text=adif, headers={"content-type": "text/plain"})
        raise AssertionError(str(request.url))

    adapter = EQSLCloudAdapterV510(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )
    result = adapter.fetch_all()
    assert [r["CALL"] for r in result["records"]] == ["K1ABC", "W1XYZ"]
    assert result["metadata"]["remote_reported_count"] == 2
    assert result["metadata"]["download_strategy"] == "OUTBOX_ADIF_FILE"


def test_eqsl_rejects_generated_file_when_reported_count_does_not_match():
    html_page = "<html><body>There were 2 records <a href='/downloadedfiles/test.adi'>.ADI file</a></body></html>"

    def handler(request):
        if request.url.path.lower().endswith("downloadadif.cfm"):
            return httpx.Response(200, text=html_page, headers={"content-type": "text/html"})
        return httpx.Response(200, text=_record("K1ABC"), headers={"content-type": "text/plain"})

    adapter = EQSLCloudAdapterV510(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    assert "página informa 2 QSOs" in str(exc.value)
    assert "arquivo ADIF contém 1" in str(exc.value)


def test_eqsl_accepts_direct_adif_response():
    adif = _record("K1ABC")

    def handler(request):
        return httpx.Response(200, text=adif, headers={"content-type": "text/plain"})

    adapter = EQSLCloudAdapterV510(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()
    assert len(result["records"]) == 1
    assert result["metadata"]["download_strategy"] == "DIRECT_ADIF"


def test_eqsl_reports_authentication_failure_from_html_page():
    def handler(request):
        return httpx.Response(200, text="<html><body>You are not yet logged in</body></html>", headers={"content-type": "text/html"})

    adapter = EQSLCloudAdapterV510(
        {"username": "PU2BRU", "password": "bad"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    assert "credenciais" in str(exc.value)
