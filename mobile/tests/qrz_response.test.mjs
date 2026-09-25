import test from 'node:test'
import assert from 'node:assert/strict'
import { decodeQRZAdif, parseQRZResponse } from '../src/qrz_response.js'

const record='<CALL:5>K1ABC<QSO_DATE:8>20260925<TIME_ON:6>013300<BAND:3>20M<MODE:3>FT8<APP_QRZLOG_LOGID:3>123<EOR>'

test('QRZ parser decodes a normal form-encoded ADIF response',()=>{
  const data=parseQRZResponse('RESULT=OK&COUNT=1&LOGIDS=123&ADIF='+encodeURIComponent(record))
  assert.equal(data.RESULT,'OK')
  assert.equal(data.COUNT,'1')
  assert.equal(data.ADIF,record)
})

test('QRZ parser decodes a double-encoded ADIF response from the native client',()=>{
  const twice=encodeURIComponent(encodeURIComponent(record))
  const data=parseQRZResponse('RESULT=OK&COUNT=1&LOGIDS=123&ADIF='+twice)
  assert.equal(data.ADIF,record)
})

test('QRZ parser preserves literal plus signs in raw ADIF',()=>{
  const raw='<CALL:5>K1ABC<RST_SENT:3>+06<COMMENT:11>A&B testing<EOR>'
  const data=parseQRZResponse('RESULT=OK&COUNT=1&ADIF='+raw)
  assert.equal(data.ADIF,raw)
})

test('QRZ ADIF decoder handles HTML-escaped payloads',()=>{
  assert.equal(decodeQRZAdif('&lt;CALL:5&gt;K1ABC&lt;EOR&gt;'),'<CALL:5>K1ABC<EOR>')
})
