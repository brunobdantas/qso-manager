import test from 'node:test'
import assert from 'node:assert/strict'
import { parseAdif, recordToAdif, matchRecords, consolidate, buildQsl, hrdlogPlan } from '../src/core.js'
import { normalizeQRZKey } from '../src/providers.js'

const q=(call,date,time,extra={})=>({CALL:call,QSO_DATE:date,TIME_ON:time,BAND:'20M',MODE:'FT8',FREQ:'14.074',...extra})

test('ADIF parser and serializer preserve QSO identity',()=>{
  const row=q('K1ABC','20260910','211200')
  const text='<ADIF_VER:5>3.1.4<EOH>'+recordToAdif(row)
  const parsed=parseAdif(text)
  assert.equal(parsed.length,1)
  assert.equal(parsed[0].CALL,'K1ABC')
  assert.equal(parsed[0].QSO_DATE,'20260910')
})

test('matching tolerates small online timestamp drift',()=>{
  const a=[q('LU1EEG','20260910','022300')]
  const b=[q('LU1EEG','20260910','022330')]
  const result=matchRecords(a,b,'QRZ','WRL')
  assert.equal(result.matches.length,1)
  assert.equal(result.matches[0].e.timeDiffSeconds,30)
})

test('consolidation exposes missing providers and field differences',()=>{
  const datasets={
    QRZ:{records:[q('OK1AR','20260908','123900',{RST_RCVD:'-10'})]},
    WRL:{records:[q('OK1AR','20260908','123900',{RST_RCVD:'-08'})]},
    CLUBLOG:{records:[]},EQSL:{records:[]},HRDLOG:{records:[]},
  }
  const rows=consolidate(datasets,['QRZ','WRL','CLUBLOG','EQSL','HRDLOG'])
  assert.equal(rows.length,1)
  assert.deepEqual(rows[0].providers,['QRZ','WRL'])
  assert.equal(rows[0].differences[0].field,'RST_RCVD')
})

test('QSL evidence keeps explicit confirmation date',()=>{
  const qrz=[q('OK1AR','20260908','123900')]
  const lotw=[q('OK1AR','20260908','123900',{QSL_RCVD:'Y',QSLRDATE:'20260910'})]
  const items=buildQsl(qrz,[],lotw)
  assert.equal(items.length,1)
  assert.equal(items[0].services[0].kind,'LOTW')
  assert.equal(items[0].services[0].date,'20260910')
})

test('HRDLog plan excludes close review candidates and returns safe absence',()=>{
  const qrz=[q('K1ABC','20260910','211200'),q('EA1XYZ','20260910','212000')]
  const hrd=[q('K1ABC','20260910','211200')]
  const plan=hrdlogPlan(qrz,hrd)
  assert.equal(plan.length,1)
  assert.equal(plan[0].call,'EA1XYZ')
})


test('QRZ key normalization removes copy/paste whitespace',()=>{
  assert.equal(normalizeQRZKey('  ABCD-1234-5678-90AB\n'), 'ABCD-1234-5678-90AB')
  assert.equal(normalizeQRZKey('ABCD 1234 5678 90AB'), 'ABCD1234567890AB')
})
