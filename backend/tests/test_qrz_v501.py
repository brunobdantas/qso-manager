from urllib.parse import parse_qs

import httpx
import pytest

from app.adapters.cloud_logs import CloudProviderError
from app.adapters.qrz_cloud_v501 import QRZCloudAdapterV501


def test_qrz_v501_tests_fetch_permission_with_count_only():
    seen = {}

    def handler(request):
        seen.update({k: v[-1] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, text="RESULT=OK&COUNT=21621")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.test_connection()
    assert result["ok"] is True
    assert result["records"] == 21621
    assert seen["ACTION"] == "FETCH"
    assert seen["OPTION"] == "MAX:0,TYPE:LOGIDS,STATUS:ALL"


def test_qrz_v501_turns_bare_fail_into_actionable_message():
    def handler(request):
        return httpx.Response(200, text="RESULT=FAIL")

    adapter = QRZCloudAdapterV501(
        {"api_key": "ABCD-0000-1111-2222"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CloudProviderError) as exc:
        adapter.fetch_all()
    text = str(exc.value)
    assert "Logbook API Access Key" in text
    assert "XML/callsign" in text
    assert "XML ou superior" in text


def test_qrz_v501_removes_accidental_whitespace_from_pasted_key():
    captured = {}

    def handler(request):
        captured.update({k: v[-1] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, text="RESULT=OK&COUNT=0")

    adapter = QRZCloudAdapterV501(
        {"api_key": "  ABCD-0000-1111-2222\r\n"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter.test_connection()
    assert captured["KEY"] == "ABCD-0000-1111-2222"
