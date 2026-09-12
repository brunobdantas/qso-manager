import test from 'node:test'
import assert from 'node:assert/strict'
import { consolidate } from '../src/core.js'

const q=(call,date,time)=>({CALL:call,QSO_DATE:date,TIME_ON:time,BAND:'20M',MODE:'FT8',FREQ:'14.074'})

test('Ham Radio Deluxe ADIF participates in the same consolidated mobile workspace',()=>{
  const datasets={
    QRZ:{records:[q('K1ABC','20260910','211200')]},
    HRD:{records:[q('K1ABC','20260910','211220'),q('EA1XYZ','20260910','212000')]},
  }
  const rows=consolidate(datasets,['QRZ','HRD'])
  assert.equal(rows.length,2)
  const matched=rows.find(x=>x.call==='K1ABC')
  const hrdOnly=rows.find(x=>x.call==='EA1XYZ')
  assert.deepEqual(matched.providers,['QRZ','HRD'])
  assert.deepEqual(hrdOnly.providers,['HRD'])
})
