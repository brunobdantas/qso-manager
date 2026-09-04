from urllib.parse import urlencode

import httpx

from app.adapters.cloud_logs import (
    ClubLogCloudAdapter,
    EQSLCloudAdapter,
    QRZCloudAdapter,
    WRLCloudAdapter,
    record_to_adif,
)


def test_record_to_adif_restores_adif_date_and_time_format():
    value = record_to_adif({"CALL": "K1ABC", "QSO_DATE": "2026-09-04", "TIME_ON": "12:39:00", "BAND": "20m"})
    assert "<QSO_DATE:8>20260904" in value
    assert "<TIME_ON:6>123900" in value


def test_qrz_status_fetch_and_exact_verification():
    page = "<CALL:5>K1ABC<QSO_DATE:8>20260904<TIME_ON:6>123900<BAND:3>20m<FREQ:6>14.074<MODE:3>FT8<APP_QRZLOG_LOGID:3>123<EOR>"

    def handler(request):
        body = request.content.decode()
        if "ACTION=STATUS" in body:
            return httpx.Response(200, text="RESULT=OK&DATA=COUNT%3D1")
        return httpx.Response(200, text=urlencode({"RESULT": "OK", "COUNT": "1", "ADIF": page, "LOGIDS": "123"}))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = QRZCloudAdapter({"api_key": "test"}, client=client)
    assert adapter.test_connection()["ok"] is True
    result = adapter.fetch_all()
    assert len(result["records"]) == 1
    assert result["records"][0]["QSO_DATE"] == "2026-09-04"
    assert adapter.fetch_logids(["123"])["verified"] is True


def test_wrl_cursor_paging_and_conversion():
    calls = {"contacts": 0}

    def handler(request):
        if request.url.path == "/v1/me":
            return httpx.Response(200, json={"data": {"uid": "u"}, "meta": {}, "error": None})
        calls["contacts"] += 1
        if calls["contacts"] == 1:
            return httpx.Response(200, json={
                "data": [{"id": "one", "call": "K1ABC", "timestamp": "2026-09-04T12:39:00Z", "freq": 14.074, "band": 20, "mode": "FT8"}],
                "meta": {"nextCursor": "opaque"}, "error": None,
            })
        return httpx.Response(200, json={
            "data": [{"id": "two", "call": "K2ABC", "timestamp": "2026-09-04T12:40:00Z", "freq": 21.074, "band": 15, "mode": "FT8"}],
            "meta": {"nextCursor": None}, "error": None,
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = WRLCloudAdapter({"api_key": "wrl_live_test"}, client=client)
    assert adapter.test_connection()["ok"] is True
    result = adapter.fetch_all()
    assert [r["APP_WRL_ID"] for r in result["records"]] == ["one", "two"]
    assert result["records"][0]["BAND"] == "20m"
    assert calls["contacts"] == 2


def test_clublog_download_and_eqsl_outbox_are_parsed_as_adif():
    adif = "<CALL:5>K1ABC<QSO_DATE:8>20260904<TIME_ON:6>123900<BAND:3>20m<FREQ:6>14.074<MODE:3>FT8<EOR>"

    def club_handler(request):
        return httpx.Response(200, text=adif)

    club = ClubLogCloudAdapter(
        {"email": "x@example.com", "app_password": "secret", "callsign": "PU2BRU", "api_key": "api"},
        client=httpx.Client(transport=httpx.MockTransport(club_handler)),
    )
    assert len(club.fetch_all()["records"]) == 1

    def eqsl_handler(request):
        if request.url.path.endswith("DisplayLastUploadDate.cfm"):
            return httpx.Response(200, text="Last Upload 2026-09-04")
        if request.url.path.endswith("DownloadADIF.cfm"):
            return httpx.Response(200, text=adif)
        return httpx.Response(200, text="Result: 1 out of 1 records added")

    eqsl = EQSLCloudAdapter(
        {"username": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(eqsl_handler)),
    )
    assert eqsl.test_connection()["ok"] is True
    assert len(eqsl.fetch_all()["records"]) == 1
    assert eqsl.add_qso({"CALL": "K1ABC", "QSO_DATE": "2026-09-04", "TIME_ON": "12:39:00", "BAND": "20m", "FREQ": 14.074, "MODE": "FT8"})["ok"] is True
