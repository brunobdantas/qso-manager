"""Regression cases derived from actual ADIF/QSL review workflows."""
import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.adif_workbench import ADIFWorkbench, patch_adif, scan_adif, csv_report
from app.adapters.cloud_logs import records_to_adif
from app.api import adif_workbench as api


def qso(time='022300', **fields):
    return {'CALL':'LU1EEG','QSO_DATE':'20151028','TIME_ON':time,'BAND':'20m','MODE':'JT65',
            'FREQ':'14.076000','STATION_CALLSIGN':'PU2BRU',**fields}


def save(w, name, rows, kind='LOG', coverage='FULL_EXPORT'):
    return w.save(name,kind,coverage,records_to_adif(rows),name+'.adi')['id']


def test_named_sources_are_persistent_with_backup_and_original(tmp_path):
    w=ADIFWorkbench(tmp_path)
    sid=save(w,'QRZ set',[qso()])
    original=w.load(sid)['content']
    w.save('QRZ set','LOG','PARTIAL_EXPORT',records_to_adif([qso('030000')]),'new.adi',sid)
    assert ADIFWorkbench(tmp_path).load(sid)['coverage']=='PARTIAL_EXPORT'
    backup=next((w.directory/'backups').glob('*.json'))
    assert json.loads(backup.read_text())['content']==original
    w.delete(sid)
    assert not w.sources()
    assert len(list((w.directory/'backups').glob('*.json')))==2
    with pytest.raises(ValueError):w.load('../outside')


def test_partial_comparison_multiple_sources_and_field_details(tmp_path):
    w=ADIFWorkbench(tmp_path)
    base=save(w,'QRZ',[qso(RST_SENT='-10'),qso('090000',CALL='OK1AR')])
    partial=save(w,'HRD',[qso(RST_SENT='-15')],coverage='PARTIAL_EXPORT')
    other=save(w,'WRL',[qso(RST_SENT='-12')])
    r=w.compare(base,[partial,other])
    assert len(r['comparisons'])==2
    missing=r['comparisons'][0]['missing_in_b']
    assert missing[0]['confidence']=='INSUFFICIENT_COVERAGE'
    assert any(x.get('field')=='RST_SENT' for x in r['findings'])
    assert 'RST_SENT' in csv_report(r['findings'])


def test_qsl_unique_four_minutes_and_patch_preserve_every_other_byte(tmp_path):
    w=ADIFWorkbench(tmp_path)
    original=records_to_adif([qso(APP_QRZLOG_LOGID='999',EQSL_QSL_SENT='Y',EQSL_QSLSDATE='20160101',APP_CUSTOM2='literal <EOR> é',COMMENT='unchanged'),qso('090000',CALL='OK1AR')]).replace('<EOH>','<APP_HEADER:4:S>test<eoh>').replace('<EOR>','<eor>')
    base=w.save('QRZ','LOG','FULL_EXPORT',original,'original.adi')['id']
    received=save(w,'eQSL Inbox',[qso('022700',EQSL_QSL_RCVD='Y',EQSL_QSLRDATE='20160203')],'EQSL_RECEIVED')
    r=w.qsl(base,[received])
    assert r['summary']=={'READY':1}
    p=r['proposals'][0]
    assert p['evidence'][0]['delta_seconds']==240
    assert p['changes']=={'EQSL_QSL_RCVD':'Y','EQSL_QSLRDATE':'20160203'}
    corrected,unchanged,_=w.export_qsl(base,[received],300,r['revision'],[p['id']])
    assert unchanged==original
    parsed,_=scan_adif(corrected)
    before,_=scan_adif(original)
    assert len(parsed)==len(before)==2
    assert parsed[1]==before[1]
    for field,value in before[0].items():assert parsed[0][field]==value
    assert '<APP_HEADER:4:S>test<eoh>' in corrected
    assert w.load(base)['content']==original
    assert not w.qsl(base,[received],60)['proposals']


def test_multiple_candidates_are_never_exportable(tmp_path):
    w=ADIFWorkbench(tmp_path)
    base=save(w,'QRZ',[qso(),qso('022600')])
    received=save(w,'eQSL',[qso('022700',EQSL_QSL_RCVD='Y')],'EQSL_RECEIVED')
    r=w.qsl(base,[received])
    assert not r['proposals']
    assert r['unmatched'][0]['status']=='AMBIGUOUS'
    with pytest.raises(ValueError):w.export_qsl(base,[received],300,r['revision'],['invented'])


def test_deduplicate_receipts_and_block_conflicting_dates(tmp_path):
    w=ADIFWorkbench(tmp_path)
    base=save(w,'QRZ',[qso()])
    receipt=qso(EQSL_QSL_RCVD='Y',EQSL_QSLRDATE='20160203')
    src=save(w,'eQSL',[receipt,receipt],'EQSL_RECEIVED')
    r=w.qsl(base,[src]); assert len(r['proposals'])==1
    assert len(r['proposals'][0]['evidence'])==2
    second=save(w,'eQSL outro',[{**receipt,'EQSL_QSLRDATE':'20160204'}],'EQSL_RECEIVED')
    assert w.qsl(base,[src,second])['proposals'][0]['status']=='REVIEW'


@pytest.mark.parametrize('date',['20150230','20141028','not-a-date'])
def test_bad_receipt_dates_never_proposed(tmp_path,date):
    w=ADIFWorkbench(tmp_path)
    base=save(w,'QRZ',[qso()]);src=save(w,'eQSL',[qso(EQSL_QSL_RCVD='Y',EQSL_QSLRDATE=date)])
    assert w.qsl(base,[src])['proposals'][0]['status']=='REVIEW'


def test_missing_date_is_not_invented_and_sent_preserved(tmp_path):
    w=ADIFWorkbench(tmp_path)
    base=save(w,'QRZ',[qso(EQSL_QSL_SENT='Y',QSL_RCVD='Y')]);src=save(w,'Inbox',[qso()],'EQSL_RECEIVED')
    r=w.qsl(base,[src]);p=r['proposals'][0]
    assert p['changes']=={'EQSL_QSL_RCVD':'Y'}
    assert r['matrix'][0]['channels']['PAPER']['received']=='Y'
    assert r['matrix'][0]['channels']['EQSL']['received']==''


def test_lotw_requires_explicit_status_and_channels_are_separate(tmp_path):
    w=ADIFWorkbench(tmp_path);base=save(w,'QRZ',[qso()])
    lotw=save(w,'LoTW',[qso(LOTW_QSL_RCVD='N',QSL_RCVD='Y')],'LOTW')
    assert not w.qsl(base,[lotw])['proposals']
    confirmed=save(w,'LoTW sim',[qso(LOTW_QSL_RCVD='Y',LOTW_QSLRDATE='20260908')],'LOTW')
    p=w.qsl(base,[confirmed])['proposals'][0]
    assert p['channel']=='LOTW'
    assert set(p['changes'])=={'LOTW_QSL_RCVD','LOTW_QSLRDATE'}


def test_stale_revision_rejected(tmp_path):
    w=ADIFWorkbench(tmp_path);base=save(w,'QRZ',[qso()]);src=save(w,'eQSL',[qso(EQSL_QSL_RCVD='Y')])
    r=w.qsl(base,[src])
    w.save('eQSL','LOG','FULL_EXPORT',records_to_adif([qso('023000')]),'new.adi',src)
    with pytest.raises(ValueError,match='mudaram'):w.export_qsl(base,[src],300,r['revision'],[r['proposals'][0]['id']])


def test_existing_date_conflict_and_unchanged(tmp_path):
    w=ADIFWorkbench(tmp_path);base=save(w,'QRZ',[qso(EQSL_QSL_RCVD='Y',EQSL_QSLRDATE='20160203')])
    src=save(w,'eQSL',[qso(EQSL_QSL_RCVD='Y',EQSL_QSLRDATE='20160204')])
    assert w.qsl(base,[src])['proposals'][0]['status']=='REVIEW'
    same=save(w,'same',[qso(EQSL_QSL_RCVD='Y',EQSL_QSLRDATE='20160203')])
    assert w.qsl(base,[same])['proposals'][0]['status']=='UNCHANGED'


def test_malformed_and_unterminated_adif_rejected():
    with pytest.raises(ValueError):scan_adif('<CALL:99>NO<EOR>')
    with pytest.raises(ValueError):scan_adif('<CALL:3>ABC<QSO_DATE:8>20260908')
    with pytest.raises(ValueError):scan_adif('<CALL:3>ABC<CALL:3>DEF<EOR>')
    assert "'=SUM" in csv_report([{'comment':'=SUM(A1:A2)'}])


def test_api_end_to_end_zip_and_source_validation(tmp_path,monkeypatch):
    w=ADIFWorkbench(tmp_path)
    monkeypatch.setattr(api,'ADIFWorkbench',lambda:w)
    app=FastAPI();app.include_router(api.router)
    client=TestClient(app)
    base=save(w,'QRZ',[qso()]);src=save(w,'eQSL',[qso(EQSL_QSL_RCVD='Y')])
    body={'target_id':base,'source_ids':[src],'tolerance':300}
    r=client.post('/api/adif-workbench/qsl',json=body).json()
    export=client.post('/api/adif-workbench/qsl/export',json={**body,'revision':r['revision'],'selected':[r['proposals'][0]['id']]})
    assert export.status_code==200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert {'log-original.adi','log-com-confirmacoes.adi','alteracoes.csv','evidencias.json'} <= set(archive.namelist())
        assert archive.read('log-original.adi').decode()==w.load(base)['content']
    assert client.post('/api/adif-workbench/qsl',json={**body,'tolerance':301}).status_code==422


def test_complete_inbox_is_not_a_complete_qso_log(tmp_path):
    w=ADIFWorkbench(tmp_path)
    base=save(w,'QRZ',[qso(),qso('090000',CALL='OK1AR')])
    inbox=save(w,'Todos os recebidos',[qso()],'EQSL_RECEIVED','FULL_EXPORT')
    result=w.compare(base,[inbox])
    assert result['comparisons'][0]['missing_in_b'][0]['confidence']=='INSUFFICIENT_COVERAGE'
