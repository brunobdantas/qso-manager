import { CapacitorHttp } from '@capacitor/core'
import { parseAdif, recordToAdif } from './core.js'

function form(data){const p=new URLSearchParams();Object.entries(data).forEach(([k,v])=>{if(v!=null&&v!=='')p.set(k,String(v))});return p.toString()}
function qs(data){const p=new URLSearchParams();Object.entries(data).forEach(([k,v])=>{if(v!=null&&v!=='')p.set(k,String(v))});return p.toString()}
async function request(options){
  const r=await CapacitorHttp.request({...options,responseType:'text'})
  if(r.status<200||r.status>=300)throw new Error('HTTP '+r.status)
  return {text:typeof r.data==='string'?r.data:JSON.stringify(r.data),url:r.url||options.url,headers:r.headers||{}}
}
async function get(url,params={},headers={}){const query=qs(params);return request({method:'GET',url:url+(query?(url.includes('?')?'&':'?')+query:''),headers})}
async function postForm(url,data,headers={}){return request({method:'POST',url,headers:{'Content-Type':'application/x-www-form-urlencoded',...headers},data:form(data)})}
function parsedQuery(text){const p=new URLSearchParams(text);return Object.fromEntries([...p.entries()].map(([k,v])=>[k.toUpperCase(),v]))}
export function normalizeQRZKey(value){return String(value||'').replace(/\s+/g,'').trim()}
function qrzError(data,action){
  const result=String(data.RESULT||'').toUpperCase(), reason=String(data.REASON||'').trim()
  if(result==='AUTH'){
    throw new Error('QRZ recusou '+action+' por permissão/assinatura. A Logbook API exige uma assinatura QRZ no nível XML ou superior. Resposta: '+(reason||'AUTH'))
  }
  if(result==='FAIL'){
    const low=reason.toLowerCase()
    if(low.includes('key')||low.includes('access')||low.includes('invalid')){
      throw new Error('QRZ recusou a Logbook API Key. Confira se é a chave do logbook correto (não a senha do QRZ). Resposta: '+(reason||'FAIL'))
    }
    throw new Error('QRZ recusou '+action+': '+(reason||'FAIL'))
  }
}
async function qrzPost(c,action,option){
  const key=normalizeQRZKey(c?.api_key)
  if(!key)throw new Error('QRZ Logbook API Key não configurada')
  const payload={KEY:key,ACTION:String(action||'').toUpperCase()}
  if(option)payload.OPTION=option
  const r=await postForm('https://logbook.qrz.com/api',payload,{'User-Agent':'PU2BRU-QSO-Manager/9.0 (PU2BRU)'})
  const data=parsedQuery(r.text)
  qrzError(data,payload.ACTION)
  return data
}
function cleanHtml(text){return String(text||'').replace(/<[^>]+>/g,' ').replace(/&nbsp;/gi,' ').replace(/\s+/g,' ').trim()}
export function qrzStatusCount(data){
  for(const value of [data.COUNT,data.QSOS,data.DATA]){
    const text=String(value||'').trim()
    if(/^\d+$/.test(text))return Number(text)
    const m=text.match(/(?:TOTAL(?:_QSO)?S?|QSOS?|COUNT)\s*[=:]\s*(\d+)/i)
    if(m)return Number(m[1])
  }
  return 0
}
function qrzResponseCount(data){
  const n=Number(String(data.COUNT||'').trim())
  return Number.isFinite(n)?n:0
}
function qrzLogIds(data,page=[]){
  const ids=[]
  for(const row of page){
    const n=Number(row.APP_QRZLOG_LOGID||row.QSO_ID)
    if(Number.isFinite(n)&&!ids.includes(n))ids.push(n)
  }
  for(const token of String(data.LOGIDS||'').split(',')){
    const n=Number(token.trim())
    if(Number.isFinite(n)&&!ids.includes(n))ids.push(n)
  }
  return ids
}
function hrefs(text){const out=[];const re=/href=["']([^"']+\.(?:adi|adif|txt)(?:\?[^"']*)?)["']/ig;let m;while((m=re.exec(String(text||''))))out.push(m[1]);return out}
async function adifFromBuildPage(endpoint,params){
  const first=await get(endpoint,params)
  const direct=parseAdif(first.text)
  if(direct.length)return direct
  for(const href of hrefs(first.text)){
    const u=new URL(href,first.url||endpoint).toString()
    const r=await get(u)
    const rows=parseAdif(r.text)
    if(rows.length)return rows
  }
  throw new Error('O serviço não retornou um arquivo ADIF: '+cleanHtml(first.text).slice(0,180))
}

export async function fetchQRZ(c){
  // STATUS is authoritative for access and expected record count.
  const statusBefore=await qrzPost(c,'STATUS')
  const expectedBefore=qrzStatusCount(statusBefore)

  let directError=''
  try{
    const all=await qrzPost(c,'FETCH','ALL')
    const records=parseAdif(all.ADIF||'')
    const responseCount=qrzResponseCount(all)
    if(responseCount&&records.length!==responseCount){
      throw new Error('FETCH ALL incompleto: QRZ informou COUNT='+responseCount+', mas foram lidos '+records.length)
    }
    if(expectedBefore&&records.length!==expectedBefore){
      throw new Error('FETCH ALL retornou '+records.length+' QSOs, mas STATUS informa '+expectedBefore)
    }
    // Never accept a silent empty payload when STATUS says the book has data.
    if(expectedBefore>0&&!records.length){
      throw new Error('FETCH ALL retornou 0 QSOs, mas STATUS informa '+expectedBefore)
    }
    if(records.length||expectedBefore===0){
      const statusAfter=await qrzPost(c,'STATUS')
      const expectedAfter=qrzStatusCount(statusAfter)||expectedBefore
      if(expectedAfter&&records.length!==expectedAfter){
        throw new Error('O log mudou durante o download: QRZ informa '+expectedAfter+' QSOs e foram lidos '+records.length)
      }
      return {records,metadata:{coverage:'API_FULL_SYNC',strategy:'DIRECT_ALL',pages:1,remoteStatusCount:expectedAfter,responseCount,verifiedRecordCount:records.length}}
    }
  }catch(e){
    directError=String(e?.message||e)
    if(directError.startsWith('QRZ recusou'))throw e
  }

  let after=0,pages=0,records=[],seen=new Set()
  while(true){
    const data=await qrzPost(c,'FETCH','MAX:250,AFTERLOGID:'+after)
    const page=parseAdif(data.ADIF||'')
    const ids=qrzLogIds(data,page)
    const signature=[ids.slice(0,3).join(','),ids.slice(-3).join(','),page.length].join('|')
    if(page.length&&seen.has(signature))throw new Error('QRZ repetiu a mesma página durante a paginação')
    seen.add(signature)
    if(!page.length)break
    records=records.concat(page);pages++
    if(page.length<250)break
    if(!ids.length)throw new Error('QRZ não informou LOGID para continuar a paginação')
    const next=Math.max(...ids)+1
    if(next<=after)throw new Error('Paginação do QRZ não avançou')
    after=next
    if(expectedBefore&&records.length>=expectedBefore)break
    if(pages>10000)throw new Error('Limite de paginação QRZ atingido')
  }

  const statusAfter=await qrzPost(c,'STATUS')
  const expectedAfter=qrzStatusCount(statusAfter)||expectedBefore
  if(expectedAfter>0&&!records.length){
    throw new Error('QRZ está conectado e informa '+expectedAfter+' QSOs, mas o download retornou 0. O snapshot anterior foi preservado.')
  }
  if(expectedAfter&&records.length!==expectedAfter){
    throw new Error('Download QRZ incompleto: QRZ informa '+expectedAfter+' QSOs, mas foram baixados '+records.length+'. O snapshot anterior foi preservado.')
  }
  return {records,metadata:{coverage:'API_FULL_SYNC',strategy:'PAGED_MINIMAL',pages,remoteStatusCount:expectedAfter,verifiedRecordCount:records.length,directAllError:directError}}
}

export async function fetchWRL(c){
  if(!c?.api_key)throw new Error('WRL Developer API Key não configurada')
  const records=[];let cursor=null,pages=0
  do{
    const params={limit:100}
    if(cursor)params.cursor=cursor
    if(c.logbook_id)params.logbookId=c.logbook_id
    const r=await get('https://api.worldradioleague.com/v1/contacts',params,{Authorization:'Bearer '+c.api_key,'User-Agent':'PU2BRU-QSO-Manager/9.0'})
    let payload
    try{payload=JSON.parse(r.text)}catch{throw new Error('WRL retornou resposta inválida')}
    if(payload.error)throw new Error(payload.error.message||'Erro WRL')
    for(const x of payload.data||[]){
      const d=new Date(x.timestamp)
      const valid=!Number.isNaN(d.getTime())
      const rec={
        CALL:x.call,QSO_DATE:valid?d.toISOString().slice(0,10).replaceAll('-',''):undefined,
        TIME_ON:valid?d.toISOString().slice(11,19).replaceAll(':',''):undefined,FREQ:x.freq,
        BAND:typeof x.band==='number'?String(x.band)+'M':String(x.band||'').toUpperCase(),MODE:x.mode,
        RST_SENT:x.rstSent,RST_RCVD:x.rstRcvd,GRIDSQUARE:x.gridsquare,STATE:x.state,COUNTRY:x.country,
        COMMENT:x.notes,NAME:x.name,QTH:x.qth,APP_WRL_ID:x.id,APP_WRL_LOGBOOK_ID:x.logbookId,
      }
      Object.keys(rec).forEach(k=>(rec[k]==null||rec[k]==='')&&delete rec[k])
      records.push(rec)
    }
    cursor=payload.meta?.nextCursor||null;pages++
    if(pages>10000)throw new Error('Limite de paginação WRL atingido')
  }while(cursor)
  return {records,metadata:{coverage:'API_FULL_SYNC',pages}}
}

export async function fetchClubLog(c){
  if(!c?.email||!c?.app_password||!c?.callsign)throw new Error('Club Log requer e-mail, Application Password e indicativo')
  const r=await postForm('https://clublog.org/getadif.php',{email:c.email,password:c.app_password,call:c.callsign})
  const records=parseAdif(r.text)
  if(!records.length)throw new Error('Club Log não retornou ADIF: '+cleanHtml(r.text).slice(0,180))
  return {records,metadata:{coverage:'API_FULL_SYNC',minimalist_export:true}}
}

function eqslParams(c){
  if(!c?.username||!c?.password)throw new Error('eQSL requer Username/Indicativo e senha')
  const p={Username:c.username,Password:c.password}
  if(c.qth_nickname)p.QTHNickname=c.qth_nickname
  return p
}
export async function fetchEQSL(c){
  const records=await adifFromBuildPage('https://www.eqsl.cc/qslcard/DownloadADIF.cfm',eqslParams(c))
  return {records,metadata:{coverage:'API_FULL_SYNC',source:'eqsl_outbox'}}
}
export async function fetchEQSLInbox(c){
  const p={...eqslParams(c),RcvdSince:'19000101'}
  const records=await adifFromBuildPage('https://www.eqsl.cc/qslcard/DownloadInbox.cfm',p)
  records.forEach(x=>{x.EQSL_QSL_RCVD='Y';if(x.QSLRDATE&&!x.EQSL_QSLRDATE)x.EQSL_QSLRDATE=x.QSLRDATE})
  return {records,metadata:{coverage:'API_FULL_SYNC',confirmations_only:true,source:'eqsl_inbox'}}
}

export async function fetchLoTW(c){
  if(!c?.login||!c?.password)throw new Error('LoTW requer login e senha')
  const r=await get('https://lotw.arrl.org/lotwuser/lotwreport.adi',{
    login:c.login,password:c.password,qso_query:1,qso_qsl:'yes',qso_qsldetail:'yes',qso_withown:'yes',qso_qslsince:'1945-11-15',
  })
  if(!String(r.text).toUpperCase().includes('<EOH>'))throw new Error('LoTW não retornou ADIF: '+cleanHtml(r.text).slice(0,180))
  const records=parseAdif(r.text)
  records.forEach(x=>{if(String(x.QSL_RCVD||'').toUpperCase()==='Y'){x.LOTW_QSL_RCVD='Y';if(x.QSLRDATE)x.LOTW_QSLRDATE=x.QSLRDATE}})
  return {records,metadata:{coverage:'API_FULL_SYNC',confirmations_only:true,source:'lotw'}}
}

export async function pushHRDLog(c,record){
  if(!c?.callsign||!c?.upload_code)throw new Error('HRDLog requer Indicativo + Upload Code')
  const r=await postForm('https://robot.hrdlog.net/NewEntry.aspx',{Code:c.upload_code,Callsign:c.callsign,ADIFData:recordToAdif(record)},{'User-Agent':'PU2BRU-QSO-Manager/9.0'})
  const low=r.text.toLowerCase()
  if(low.includes('<insert>1'))return {ok:true,status:'inserted'}
  if(low.includes('<insert>0'))return {ok:true,status:'duplicate'}
  if(low.includes('unknown user</error>')||low.includes('invalid token</error>'))throw new Error('HRDLog recusou Indicativo/Upload Code')
  throw new Error(cleanHtml(r.text).slice(0,220)||'HRDLog não confirmou a inclusão')
}


export const REMOTE_CAPABILITIES={
  QRZ:{read:true,add:true,update:false,delete:false},
  WRL:{read:true,add:true,update:true,delete:true},
  CLUBLOG:{read:true,add:true,update:false,delete:true},
  EQSL:{read:true,add:true,update:false,delete:false},
  LOTW:{read:true,add:false,update:false,delete:false},
  HRDLOG:{read:false,add:true,update:false,delete:false},
  HRD:{read:true,add:false,update:false,delete:false},
}

function requireIdentity(record){
  const call=String(record?.CALL||'').trim().toUpperCase()
  const date=String(record?.QSO_DATE||'').replace(/[-/]/g,'')
  const time=String(record?.TIME_ON||'').replace(/:/g,'')
  if(!call||date.length!==8||time.length<4)throw new Error('QSO sem identidade completa (CALL, QSO_DATE, TIME_ON)')
  return {call,date,time:(time+'000000').slice(0,6)}
}
function wrlPayload(record){
  const id=requireIdentity(record)
  const freq=Number(record.FREQ),band=String(record.BAND||''),mode=String(record.SUBMODE||record.MODE||'')
  if(!Number.isFinite(freq)||!band||!mode)throw new Error('WRL requer FREQ, BAND e MODE')
  const payload={programId:'PU2BRU-QSO-Manager',call:id.call,timestamp:{qsoDate:id.date,timeOn:id.time},freq,band,mode}
  const map={RST_SENT:'rstSent',RST_RCVD:'rstRcvd',COMMENT:'notes',STATION_CALLSIGN:'stationCallsign',MY_GRIDSQUARE:'myGridsquare',NAME:'name',GRIDSQUARE:'gridsquare',QTH:'qth',STATE:'state',OPERATOR:'operator'}
  for(const [src,dst] of Object.entries(map))if(record[src]!=null&&record[src]!=='')payload[dst]=String(record[src])
  return payload
}
function wrlHeaders(c){if(!c?.api_key)throw new Error('WRL Developer API Key não configurada');return {Authorization:'Bearer '+c.api_key,'Content-Type':'application/json','User-Agent':'PU2BRU-QSO-Manager/9.0'}}
async function jsonRequest(method,url,headers,data){
  const r=await CapacitorHttp.request({method,url,headers,data,responseType:'json'})
  const payload=typeof r.data==='string'?(()=>{try{return JSON.parse(r.data)}catch{return {error:{message:r.data}}}})():r.data
  if(r.status<200||r.status>=300||payload?.error)throw new Error(payload?.error?.message||payload?.message||('HTTP '+r.status))
  return payload
}
async function qrzInsert(c,record){
  const key=normalizeQRZKey(c?.api_key);if(!key)throw new Error('QRZ Logbook API Key não configurada')
  const r=await postForm('https://logbook.qrz.com/api',{KEY:key,ACTION:'INSERT',ADIF:recordToAdif(record)},{'User-Agent':'PU2BRU-QSO-Manager/9.0 (PU2BRU)'})
  const data=parsedQuery(r.text);qrzError(data,'INSERT')
  if(String(data.RESULT||'').toUpperCase()!=='OK')throw new Error(data.REASON||'QRZ não confirmou a inclusão')
  return {ok:true,externalId:data.LOGID||null}
}
async function wrlInsert(c,record){
  const payload=wrlPayload(record)
  if(c.logbook_id)payload.logbookId=c.logbook_id
  const out=await jsonRequest('POST','https://api.worldradioleague.com/v1/contacts',wrlHeaders(c),payload)
  return {ok:true,externalId:out?.data?.id||null}
}
async function wrlUpdate(c,record,changes){
  const id=record?.APP_WRL_ID
  if(!id)throw new Error('QSO do WRL sem ID remoto')
  const map={CALL:'call',FREQ:'freq',BAND:'band',MODE:'mode',SUBMODE:'mode',RST_SENT:'rstSent',RST_RCVD:'rstRcvd',COMMENT:'notes',STATION_CALLSIGN:'stationCallsign',MY_GRIDSQUARE:'myGridsquare',NAME:'name',GRIDSQUARE:'gridsquare',QTH:'qth',STATE:'state',OPERATOR:'operator'}
  const payload={}
  for(const [k,v] of Object.entries(changes||{}))if(map[k]&&v!==''&&v!=null)payload[map[k]]=k==='FREQ'?Number(v):v
  if(!Object.keys(payload).length)throw new Error('Nenhum campo editável informado')
  await jsonRequest('PATCH','https://api.worldradioleague.com/v1/contacts/'+encodeURIComponent(id),wrlHeaders(c),payload)
  return {ok:true}
}
async function wrlDelete(c,record){
  const id=record?.APP_WRL_ID;if(!id)throw new Error('QSO do WRL sem ID remoto')
  await jsonRequest('DELETE','https://api.worldradioleague.com/v1/contacts/'+encodeURIComponent(id),wrlHeaders(c))
  return {ok:true}
}
async function clubLogInsert(c,record){
  if(!c?.email||!c?.app_password||!c?.callsign||!c?.api_key)throw new Error('Club Log requer e-mail, Application Password, indicativo e API Key para escrita')
  const r=await postForm('https://clublog.org/realtime.php',{email:c.email,password:c.app_password,callsign:c.callsign,adif:recordToAdif(record),api:c.api_key})
  if(/error|failed/i.test(r.text))throw new Error(cleanHtml(r.text).slice(0,220))
  return {ok:true}
}
function clubBand(band){const t=String(band||'').toLowerCase().trim();if(t==='70cm')return'70';if(t==='23cm')return'23';if(t==='13cm')return'13';if(t.endsWith('m'))return t.slice(0,-1);throw new Error('Banda não suportada pelo delete do Club Log: '+band)}
async function clubLogDelete(c,record){
  if(!c?.email||!c?.app_password||!c?.callsign||!c?.api_key)throw new Error('Club Log requer credenciais completas e API Key para exclusão')
  const id=requireIdentity(record)
  const stamp=id.date.slice(0,4)+'-'+id.date.slice(4,6)+'-'+id.date.slice(6,8)+' '+id.time.slice(0,2)+':'+id.time.slice(2,4)+':'+id.time.slice(4,6)
  const r=await postForm('https://clublog.org/delete.php',{email:c.email,password:c.app_password,callsign:c.callsign,dxcall:id.call,datetime:stamp,bandid:clubBand(record.BAND),api:c.api_key})
  if(/not deleted|error|failed/i.test(r.text))throw new Error(cleanHtml(r.text).slice(0,220))
  return {ok:true}
}
async function eqslInsert(c,record){
  if(!c?.username||!c?.password)throw new Error('eQSL não configurado')
  const payload={...record,EQSL_USER:c.username,EQSL_PSWD:c.password}
  if(c.qth_nickname)payload.APP_EQSL_QTH_NICKNAME=c.qth_nickname
  const r=await postForm('https://www.eqsl.cc/qslcard/ImportADIF.cfm',{ADIFData:recordToAdif(payload)})
  const clean=cleanHtml(r.text);if(/0 out of|error/i.test(clean))throw new Error(clean.slice(0,300))
  return {ok:true}
}

export async function addRemote(provider,c,record){
  const p=String(provider||'').toUpperCase()
  if(p==='QRZ')return qrzInsert(c,record)
  if(p==='WRL')return wrlInsert(c,record)
  if(p==='CLUBLOG')return clubLogInsert(c,record)
  if(p==='EQSL')return eqslInsert(c,record)
  if(p==='HRDLOG')return pushHRDLog(c,record)
  throw new Error(p+' não oferece inclusão remota')
}
export async function updateRemote(provider,c,record,changes){
  const p=String(provider||'').toUpperCase()
  if(p==='WRL')return wrlUpdate(c,record,changes)
  throw new Error(p+' não oferece edição remota segura')
}
export async function deleteRemote(provider,c,record){
  const p=String(provider||'').toUpperCase()
  if(p==='WRL')return wrlDelete(c,record)
  if(p==='CLUBLOG')return clubLogDelete(c,record)
  throw new Error(p+' não oferece exclusão remota segura')
}

export async function testProvider(provider,c){
  if(provider==='QRZ'){
    const d=await qrzPost(c,'STATUS')
    return 'QRZ conectado'+(d.DATA?' · '+String(d.DATA).slice(0,120):'')
  }
  if(provider==='WRL'){const r=await request({method:'GET',url:'https://api.worldradioleague.com/v1/me',headers:{Authorization:'Bearer '+c.api_key}});return JSON.parse(r.text)?.data?'WRL conectado':'WRL respondeu'}
  if(provider==='CLUBLOG'){const x=await fetchClubLog(c);return 'Club Log conectado · '+x.records.length+' QSOs'}
  if(provider==='EQSL'){const x=await fetchEQSL(c);return 'eQSL conectado · '+x.records.length+' QSOs'}
  if(provider==='LOTW'){const x=await fetchLoTW(c);return 'LoTW conectado · '+x.records.length+' confirmações'}
  if(provider==='HRDLOG'){if(!c?.callsign||!c?.upload_code)throw new Error('Informe Indicativo e Upload Code');return 'HRDLog configurado. O código é validado no primeiro envio, sem criar QSO de teste.'}
  throw new Error('Fonte não suportada')
}
