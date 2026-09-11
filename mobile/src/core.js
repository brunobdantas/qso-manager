const yes=v=>['Y','YES','TRUE','1','C'].includes(String(v||'').trim().toUpperCase())
const txt=v=>String(v??'').trim()
const upper=v=>txt(v).toUpperCase()
const dateKey=v=>{const t=txt(v).replace(/[-/]/g,'');return /^\d{8}$/.test(t)?t:txt(v)}
const timeKey=v=>{const t=txt(v).replace(/:/g,'');return (t+'000000').slice(0,6)}
const seconds=v=>{const t=timeKey(v);return /^\d{6}$/.test(t)?Number(t.slice(0,2))*3600+Number(t.slice(2,4))*60+Number(t.slice(4,6)):null}
const mode=r=>upper(r.SUBMODE||r.MODE)
const num=v=>{const n=Number(v);return Number.isFinite(n)?n:null}

export function parseAdif(input){
  const text=String(input||'')
  const records=[]
  let current={}, pos=0
  const tag=/<([^>]+)>/g
  while(true){
    tag.lastIndex=pos
    const m=tag.exec(text)
    if(!m)break
    const raw=m[1].trim(), up=raw.toUpperCase()
    pos=tag.lastIndex
    if(up==='EOH'){current={};continue}
    if(up==='EOR'){if(Object.keys(current).length)records.push(current);current={};continue}
    const parts=raw.split(':')
    if(parts.length<2)continue
    const name=parts[0].toUpperCase(), len=Number(parts[1])
    if(!Number.isFinite(len)||len<0)continue
    const value=text.slice(pos,pos+len)
    current[name]=value.trim()
    pos+=len
  }
  if(Object.keys(current).length)records.push(current)
  return records
}

function adifField(name,value){
  if(value==null||value==='')return ''
  let v=String(value)
  if(['QSO_DATE','QSLRDATE','QSLSDATE','EQSL_QSLRDATE','LOTW_QSLRDATE'].includes(name))v=v.replace(/[-/]/g,'')
  if(['TIME_ON','TIME_OFF'].includes(name))v=v.replace(/:/g,'')
  return '<'+name+':'+v.length+'>'+v
}
export function recordToAdif(record){
  const order=['CALL','QSO_DATE','TIME_ON','TIME_OFF','BAND','FREQ','MODE','SUBMODE','RST_SENT','RST_RCVD','GRIDSQUARE','STATE','CNTY','COUNTRY','COMMENT','STATION_CALLSIGN','MY_GRIDSQUARE']
  const seen=new Set(), out=[]
  for(const k of order){if(record[k]!=null&&record[k]!==''){out.push(adifField(k,record[k]));seen.add(k)}}
  for(const [k0,v] of Object.entries(record||{})){const k=k0.toUpperCase();if(seen.has(k)||k.startsWith('_')||v==null||typeof v==='object')continue;out.push(adifField(k,v))}
  return out.join('')+'<EOR>'
}

export function normalize(record,index=0,source=''){
  const freq=num(record.FREQ)
  return {
    source,index,raw:record,call:upper(record.CALL),date:dateKey(record.QSO_DATE),time:timeKey(record.TIME_ON),
    seconds:seconds(record.TIME_ON),band:upper(record.BAND),mode:mode(record),freqMHz:freq,
    rstSent:txt(record.RST_SENT),rstRcvd:txt(record.RST_RCVD),grid:upper(record.GRIDSQUARE||record.GRID),
    state:upper(record.STATE),county:upper(record.CNTY||record.COUNTY),country:upper(record.COUNTRY),
  }
}
const modeCompatible=(a,b)=>!a.mode||!b.mode||a.mode===b.mode||(['FT8','FT4'].includes(a.mode)&&['FT8','FT4'].includes(b.mode))
const freqTol=(a,b)=>{const m=a.mode||b.mode;if(m==='CW')return 0.0005;if(['SSB','USB','LSB','FM'].includes(m))return 0.003;return 0.001}
export function evidence(a,b){
  if(!a.call||a.call!==b.call||!a.date||a.date!==b.date)return null
  if(a.band&&b.band&&a.band!==b.band)return null
  const td=a.seconds!=null&&b.seconds!=null?Math.abs(a.seconds-b.seconds):null
  const fd=a.freqMHz!=null&&b.freqMHz!=null?Math.abs(a.freqMHz-b.freqMHz):null
  const mc=modeCompatible(a,b)
  if(td!=null&&td>300)return null
  if(fd!=null&&fd>Math.max(freqTol(a,b)*3,.005))return null
  let score=100-(td??20)/3-(fd??0)*10000-(mc?0:25)
  const kind=td==null?(mc?'auto':'review'):(td<=60&&mc?'auto':'review')
  return {kind,timeDiffSeconds:td,freqDiffHz:fd==null?null:Math.round(fd*1e6),modeCompatible:mc,score:Math.round(score)}
}
export function matchRecords(leftRecords,rightRecords,leftName='A',rightName='B'){
  const a=leftRecords.map((r,i)=>normalize(r,i,leftName)), b=rightRecords.map((r,i)=>normalize(r,i,rightName))
  const candidates=[], reviews=[]
  for(const l of a)for(const r of b){const e=evidence(l,r);if(!e)continue;(e.kind==='auto'?candidates:reviews).push({l,r,e})}
  candidates.sort((x,y)=>(x.e.timeDiffSeconds??9999)-(y.e.timeDiffSeconds??9999)||y.e.score-x.e.score)
  const usedA=new Set(),usedB=new Set(),matches=[]
  for(const c of candidates){if(usedA.has(c.l.index)||usedB.has(c.r.index))continue;usedA.add(c.l.index);usedB.add(c.r.index);matches.push(c)}
  return {matches,unmatchedLeft:a.filter(x=>!usedA.has(x.index)),unmatchedRight:b.filter(x=>!usedB.has(x.index)),reviews}
}
const diffFields=[['RST_SENT','RST enviado'],['RST_RCVD','RST recebido'],['GRIDSQUARE','Grid'],['STATE','Estado'],['CNTY','County'],['COUNTRY','País']]
function differences(refs,datasets){
  const out=[]
  for(const [field,label] of diffFields){
    const values=new Map()
    for(const [source,index] of Object.entries(refs)){const v=upper(datasets[source]?.records?.[index]?.[field]);if(v)values.set(source,v)}
    if(new Set(values.values()).size>1)out.push({field,label,values:Object.fromEntries(values)})
  }
  return out
}
export function duplicateIndexes(records){
  const rows=records.map((r,i)=>normalize(r,i))
  const dup=new Set()
  for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++){
    const a=rows[i],b=rows[j]
    if(a.call===b.call&&a.date===b.date&&a.band===b.band&&modeCompatible(a,b)&&a.seconds!=null&&b.seconds!=null&&Math.abs(a.seconds-b.seconds)<=2){dup.add(a.index);dup.add(b.index)}
  }
  return dup
}

export function consolidate(datasets,activeSources=['QRZ','WRL','CLUBLOG','EQSL','HRDLOG']){
  const available=activeSources.filter(s=>datasets[s]?.records?.length)
  const refs=[]
  const qrz=datasets.QRZ?.records||[]
  for(let i=0;i<qrz.length;i++)refs.push({QRZ:i})
  const orphans=[]
  for(const source of activeSources){
    if(source==='QRZ'||!datasets[source]?.records?.length)continue
    const right=datasets[source].records
    const m=matchRecords(qrz,right,'QRZ',source)
    for(const pair of m.matches){if(refs[pair.l.index])refs[pair.l.index][source]=pair.r.index}
    for(const r of m.unmatchedRight){
      let joined=false
      for(const node of orphans){
        const firstSource=Object.keys(node)[0], firstIndex=node[firstSource]
        const a=normalize(datasets[firstSource].records[firstIndex],firstIndex,firstSource), e=evidence(a,r)
        if(!node[source]&&e?.kind==='auto'){node[source]=r.index;joined=true;break}
      }
      if(!joined)orphans.push({[source]:r.index})
    }
  }
  const nodes=[...refs,...orphans], dupBySource={}
  for(const s of available)dupBySource[s]=duplicateIndexes(datasets[s].records)
  const rows=[]
  for(const refsNode of nodes){
    const provider=activeSources.find(s=>refsNode[s]!=null)
    if(!provider)continue
    const record=datasets[provider].records[refsNode[provider]]
    const q=normalize(record,refsNode[provider],provider)
    const diffs=differences(refsNode,datasets)
    const dup=Object.entries(refsNode).some(([s,i])=>dupBySource[s]?.has(i))
    rows.push({
      id:Object.entries(refsNode).map(x=>x.join(':')).join('|'),call:q.call,date:q.date,time:q.time,band:q.band,mode:q.mode,freq:record.FREQ,
      country:record.COUNTRY||'',grid:record.GRIDSQUARE||'',providers:activeSources.filter(s=>refsNode[s]!=null),
      missingIn:available.filter(s=>refsNode[s]==null),refs:refsNode,differences:diffs,duplicate:dup,canonical:record,
    })
  }
  rows.sort((a,b)=>(b.date+b.time).localeCompare(a.date+a.time))
  return rows
}
function matchEvidence(qrzRecords,evidenceRecords){
  const m=matchRecords(qrzRecords,evidenceRecords,'QRZ','QSL')
  return m.matches
}
export function buildQsl(qrzRecords,eqslInbox,lotw){
  const byIndex=new Map()
  function add(kind,records){
    for(const m of matchEvidence(qrzRecords,records||[])){
      const row=records[m.r.index], current=byIndex.get(m.l.index)||{services:[]}
      let confirmationDate=''
      if(kind==='LOTW')confirmationDate=txt(row.LOTW_QSLRDATE||row.QSLRDATE)
      else confirmationDate=txt(row.EQSL_QSLRDATE||row.QSLRDATE)
      current.services.push({kind,date:confirmationDate,source:kind==='LOTW'?'LoTW':'eQSL Inbox'})
      byIndex.set(m.l.index,current)
    }
  }
  add('EQSL',eqslInbox);add('LOTW',lotw)
  const items=[]
  for(const [index,info] of byIndex){const r=qrzRecords[index],q=normalize(r,index,'QRZ');items.push({index,call:q.call,date:q.date,time:q.time,band:q.band,mode:q.mode,services:info.services})}
  return items.sort((a,b)=>(b.date+b.time).localeCompare(a.date+a.time))
}
export function buildIssues(rows,qslItems){
  const issues=[]
  for(const q of rows){
    if(q.missingIn.length)issues.push({type:'MISSING',call:q.call,date:q.date,time:q.time,band:q.band,mode:q.mode,message:'Ausente em '+q.missingIn.join(', '),sources:q.providers})
    if(q.differences.length)issues.push({type:'DIFFERENCE',call:q.call,date:q.date,time:q.time,band:q.band,mode:q.mode,message:'Divergências: '+q.differences.map(x=>x.label).join(', '),sources:q.providers})
    if(q.duplicate)issues.push({type:'DUPLICATE',call:q.call,date:q.date,time:q.time,band:q.band,mode:q.mode,message:'Duplicidade provável',sources:q.providers})
  }
  for(const q of qslItems)issues.push({type:'QSL',call:q.call,date:q.date,time:q.time,band:q.band,mode:q.mode,message:'Confirmação em '+q.services.map(x=>x.source).join(' + '),sources:q.services.map(x=>x.kind)})
  return issues
}
export function hrdlogPlan(qrzRecords,hrdRecords){
  const m=matchRecords(qrzRecords,hrdRecords,'QRZ','HRDLOG')
  const review=new Set(m.reviews.map(x=>x.l.index)), dup=duplicateIndexes(qrzRecords)
  return m.unmatchedLeft.filter(q=>!review.has(q.index)&&!dup.has(q.index))
}
export const isConfirmedValue=yes
