import pytest
from urllib.parse import urlencode

import httpx

from app.adapters.cloud_logs import (
    ClubLogCloudAdapter,
    EQSLCloudAdapter,
    QRZCloudAdapter,
    WRLCloudAdapter,
    CloudProviderError,
    record_to_adif,
)
from app.adapters.online_v8 import LoTWConfirmationAdapter


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



def test_lotw_connection_uses_small_current_query_and_accepts_zero_records():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            text="<ADIF_VER:5>3.1.4<APP_LoTW_NUMREC:1>0<EOH>",
            headers={"content-type": "text/plain"},
        )

    adapter = LoTWConfirmationAdapter(
        {"login": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.test_connection()

    assert result["ok"] is True
    assert result["records"] == 0
    assert seen["params"]["qso_query"] == "1"
    assert seen["params"]["qso_qsl"] == "yes"
    assert seen["params"]["qso_qsldetail"] == "yes"
    assert seen["params"]["qso_withown"] == "yes"
    assert seen["params"]["qso_qslsince"]
    assert seen["params"]["qso_qslsince"] != "1945-11-15"


def test_lotw_authentication_error_is_reported_clearly():
    def handler(request):
        return httpx.Response(
            200,
            text="<html><body>Username/password incorrect</body></html>",
            headers={"content-type": "text/html"},
        )

    adapter = LoTWConfirmationAdapter(
        {"login": "PU2BRU", "password": "wrong"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudProviderError, match="recusou o username/senha"):
        adapter.test_connection()


def test_lotw_timeout_fails_with_actionable_message():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    adapter = LoTWConfirmationAdapter(
        {"login": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudProviderError, match="não respondeu"):
        adapter.test_connection()



def _lotw_report(header_fields, records):
    header = "<ADIF_VER:5>3.1.4"
    for key, value in header_fields.items():
        value = str(value)
        header += f"<{key}:{len(value)}>{value}"
    body = header + "<EOH>"
    for record in records:
        for key, value in record.items():
            value = str(value)
            body += f"<{key}:{len(value)}>{value}"
        body += "<EOR>"
    return body


def test_lotw_full_sync_downloads_all_accepted_qsos_not_only_qsls():
    seen = []

    def handler(request):
        params = dict(request.url.params)
        seen.append(params)
        assert params["qso_qsl"] == "no"
        assert params["qso_qsorxsince"] == "1945-11-15"
        assert params["qso_qsldetail"] == "yes"
        return httpx.Response(200, text=_lotw_report(
            {
                "APP_LoTW_LASTQSORX": "2026-09-24 12:00:00",
                "APP_LoTW_NUMREC": "2",
            },
            [
                {
                    "CALL": "K1AAA", "QSO_DATE": "20260924", "TIME_ON": "100000",
                    "BAND": "15M", "MODE": "FT8", "STATION_CALLSIGN": "PU2BRU",
                    "APP_LoTW_RXQSO": "2026-09-24 11:00:00", "QSL_RCVD": "N",
                },
                {
                    "CALL": "K1BBB", "QSO_DATE": "20260924", "TIME_ON": "101000",
                    "BAND": "15M", "MODE": "FT8", "STATION_CALLSIGN": "PU2BRU",
                    "APP_LoTW_RXQSO": "2026-09-24 11:05:00", "QSL_RCVD": "Y",
                    "QSLRDATE": "20260924", "APP_LoTW_RXQSL": "2026-09-24 11:30:00",
                    "STATE": "VT", "GRIDSQUARE": "FN34MQ",
                },
            ],
        ))

    adapter = LoTWConfirmationAdapter(
        {"login": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_all()

    assert len(result["records"]) == 2
    assert result["metadata"]["confirmations_only"] is False
    assert result["metadata"]["accepted_qsos"] == 2
    assert result["metadata"]["confirmed_qsos"] == 1
    assert result["metadata"]["lotw_last_qso_rx"] == "2026-09-24 12:00:00"
    assert result["metadata"]["lotw_last_qsl"] == "2026-09-24 11:30:00"
    assert result["records"][1]["LOTW_QSL_RCVD"] == "Y"
    assert len(seen) == 1


def test_lotw_incremental_sync_uses_both_official_cursors_and_merges_qsl_updates():
    requests = []

    def handler(request):
        params = dict(request.url.params)
        requests.append(params)
        if params["qso_qsl"] == "no":
            assert params["qso_qsorxsince"] == "2026-09-23 20:00:00"
            return httpx.Response(200, text=_lotw_report(
                {"APP_LoTW_LASTQSORX": "2026-09-24 12:00:00", "APP_LoTW_NUMREC": "1"},
                [{
                    "CALL": "K1NEW", "QSO_DATE": "20260924", "TIME_ON": "090000",
                    "BAND": "10M", "MODE": "FT8", "STATION_CALLSIGN": "PU2BRU",
                    "APP_LoTW_RXQSO": "2026-09-24 10:00:00", "QSL_RCVD": "N",
                }],
            ))
        assert params["qso_qsl"] == "yes"
        assert params["qso_qslsince"] == "2026-09-23 21:00:00"
        return httpx.Response(200, text=_lotw_report(
            {"APP_LoTW_LASTQSL": "2026-09-24 12:30:00", "APP_LoTW_NUMREC": "1"},
            [{
                "CALL": "K1OLD", "QSO_DATE": "20260923", "TIME_ON": "180000",
                "BAND": "12M", "MODE": "FT8", "STATION_CALLSIGN": "PU2BRU",
                "QSL_RCVD": "Y", "QSLRDATE": "20260924",
                "APP_LoTW_RXQSL": "2026-09-24 12:30:00",
                "STATE": "SD", "GRIDSQUARE": "EN12HV", "DXCC": "291",
            }],
        ))

    previous = {
        "records": [{
            "CALL": "K1OLD", "QSO_DATE": "2026-09-23", "TIME_ON": "18:00:00",
            "BAND": "12M", "MODE": "FT8", "STATION_CALLSIGN": "PU2BRU",
            "QSL_RCVD": "N", "APP_QSOMGR_LOTW_ACCEPTED": "Y",
        }],
        "metadata": {
            "coverage": "API_FULL_SYNC",
            "source": "lotw_qso_qsl_api",
            "confirmations_only": False,
            "lotw_last_qso_rx": "2026-09-23 20:00:00",
            "lotw_last_qsl": "2026-09-23 21:00:00",
        },
    }
    adapter = LoTWConfirmationAdapter(
        {"login": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_incremental(previous)

    assert len(requests) == 2
    assert len(result["records"]) == 2
    assert result["metadata"]["incremental"] is True
    assert result["metadata"]["delta_qso_records"] == 1
    assert result["metadata"]["delta_qsl_records"] == 1
    assert result["metadata"]["lotw_last_qso_rx"] == "2026-09-24 12:00:00"
    assert result["metadata"]["lotw_last_qsl"] == "2026-09-24 12:30:00"
    old = next(r for r in result["records"] if r["CALL"] == "K1OLD")
    assert old["LOTW_QSL_RCVD"] == "Y"
    assert old["STATE"] == "SD"
    assert old["GRIDSQUARE"] == "EN12HV"


def test_lotw_old_confirmation_only_snapshot_forces_one_full_migration():
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, text=_lotw_report(
            {"APP_LoTW_LASTQSORX": "2026-09-24 12:00:00", "APP_LoTW_NUMREC": "1"},
            [{
                "CALL": "K1AAA", "QSO_DATE": "20260924", "TIME_ON": "100000",
                "BAND": "15M", "MODE": "FT8", "STATION_CALLSIGN": "PU2BRU",
                "APP_LoTW_RXQSO": "2026-09-24 11:00:00", "QSL_RCVD": "N",
            }],
        ))

    adapter = LoTWConfirmationAdapter(
        {"login": "PU2BRU", "password": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch_incremental({
        "records": [{"CALL": "K1OLD"}],
        "metadata": {"confirmations_only": True},
    })

    assert len(calls) == 1
    assert calls[0]["qso_qsl"] == "no"
    assert result["metadata"]["migration_from_confirmation_only"] is True
    assert result["metadata"]["confirmations_only"] is False
