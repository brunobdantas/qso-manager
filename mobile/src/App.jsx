import React, { useEffect, useMemo, useState } from 'react'
import { loadAllDatasets, loadConnections, saveDataset, saveProviderCredentials } from './storage.js'
import { parseAdif, consolidate, buildQsl, buildIssues, hrdlogPlan } from './core.js'
import { fetchQRZ, fetchWRL, fetchClubLog, fetchEQSL, fetchEQSLInbox, fetchLoTW, pushHRDLog, testProvider } from './providers.js'

const KEYS=['QRZ','WRL','CLUBLOG','EQSL','EQSL_INBOX','LOTW','HRDLOG']
const LOGS=['QRZ','WRL','CLUBLOG','EQSL','HRDLOG']
const LABELS={QRZ:'QRZ',WRL:'World Radio League',CLUBLOG:'Club Log',EQSL:'eQSL OutBox',EQSL_INBOX:'eQSL Inbox',LOTW:'LoTW',HRDLOG:'HRDLog.net'}
const SHORT={QRZ:'QRZ',WRL:'WRL',CLUBLOG:'CL',EQSL:'eQ',EQSL_INBOX:'eQ+',LOTW:'LoTW',HRDLOG:'HL'}
const FIELDS={
 QRZ:[['api_key','QRZ Logbook API Key','password']],
 WRL:[['api_key','Developer API Key','password'],['logbook_id','Logbook ID (opcional)','text']],
 CLUBLOG:[['email','E-mail','email'],['app_password','Application Password','password'],['callsign','Indicativo','text'],['api_key','API Key de escrita (opcional)','password']],
 EQSL:[['username','Indicativo / Username','text'],['password','Senha','password'],['qth_nickname','QTH Nickname (opcional)','text']],
 LOTW:[['login','Login LoTW','text'],['password','Senha LoTW','password']],
 HRDLOG:[['callsign','Indicativo','text'],['upload_code','Upload Code','password']],
}
const fmt=n=>Number(n||0).toLocaleString('pt-BR')
const when=v=>v?new Date(v).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'Nunca'
const sleep=ms=>new Promise(r=>setTimeout(r,ms))
function configured(p,c){if(p==='EQSL_INBOX')p='EQSL';const x=c[p]||{};if(p==='QRZ'||p==='WRL')return !!x.api_key;if(p==='CLUBLOG')return !!(x.email&&x.app_password&&x.callsign);if(p==='EQSL')return !!(x.username&&x.password);if(p==='LOTW')return !!(x.login&&x.password);if(p==='HRDLOG')return !!(x.callsign&&x.upload_code);return false}
function Badge({children,tone=''}){return <span className={'m-badge '+tone}>{children}</span>}
function Icon({type}){return <span className={'m-issue-icon '+type.toLowerCase()}>{type==='QSL'?'✓':type==='MISSING'?'−':'!'}</span>}

function SourceSheet({provider,connections,onClose,onSaved}){
 const key=provider==='EQSL_INBOX'?'EQSL':provider
 const [values,setValues]=useState(connections[key]||{}),[busy,setBusy]=useState(false),[msg,setMsg]=useState('')
 async function save(test){
   setBusy(true);setMsg('')
   try{const all=await saveProviderCredentials(key,values);if(test)setMsg(await testProvider(provider==='EQSL_INBOX'?'EQSL':provider,all[key]));else setMsg('Salvo com segurança.');await onSaved(all)}
   catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}
 }
 return <div className="m-sheet-bg" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><section className="m-sheet">
   <div className="m-grabber"/><header><div><small>CONEXÃO</small><h2>{LABELS[provider]}</h2></div><button onClick={onClose}>×</button></header>
   {provider==='EQSL_INBOX'&&<p className="m-hint">O Inbox usa a mesma conta configurada no eQSL OutBox.</p>}
   <div className="m-fields">{(FIELDS[key]||[]).map(f=><label key={f[0]}><span>{f[1]}</span><input type={f[2]} value={values[f[0]]||''} onChange={e=>setValues({...values,[f[0]]:e.target.value})}/></label>)}</div>
   {msg&&<div className={'m-message '+(msg.startsWith('Erro')?'error':'')}>{msg}</div>}
   <div className="m-sheet-actions"><button className="secondary" disabled={busy} onClick={()=>save(true)}>Testar</button><button disabled={busy} onClick={()=>save(false)}>Salvar</button></div>
 </section></div>
}

export default function App(){
 const [tab,setTab]=useState('home'),[connections,setConnections]=useState({}),[datasets,setDatasets]=useState({})
 const [loading,setLoading]=useState(true),[syncing,setSyncing]=useState(false),[progress,setProgress]=useState(''),[message,setMessage]=useState('')
 const [sheet,setSheet]=useState(null),[search,setSearch]=useState(''),[issueFilter,setIssueFilter]=useState('ALL')
 useEffect(()=>{Promise.all([loadConnections(),loadAllDatasets(KEYS)]).then(r=>{setConnections(r[0]);setDatasets(r[1]);setLoading(false)}).catch(e=>{setMessage(e.message);setLoading(false)})},[])

 const model=useMemo(()=>{
   const rows=consolidate(datasets,LOGS)
   const qsls=buildQsl(datasets.QRZ?.records||[],datasets.EQSL_INBOX?.records||[],datasets.LOTW?.records||[])
   const issues=buildIssues(rows,qsls)
   return {rows,qsls,issues}
 },[datasets])
 const filteredLog=useMemo(()=>{const q=search.trim().toUpperCase();return !q?model.rows:model.rows.filter(x=>[x.call,x.country,x.grid,x.band,x.mode].join(' ').toUpperCase().includes(q))},[model.rows,search])
 const filteredIssues=useMemo(()=>issueFilter==='ALL'?model.issues:model.issues.filter(x=>x.type===issueFilter),[model.issues,issueFilter])
 const counts=useMemo(()=>Object.fromEntries(['MISSING','DIFFERENCE','DUPLICATE','QSL'].map(k=>[k,model.issues.filter(x=>x.type===k).length])),[model.issues])

 async function persist(provider,result,next){
   const payload={records:result.records||[],updatedAt:new Date().toISOString(),metadata:result.metadata||{}}
   await saveDataset(provider,payload);next[provider]=payload
 }
 async function syncHrd(next,max=100){
   if(!configured('HRDLOG',connections)||!next.HRDLOG?.updatedAt||!next.QRZ?.records?.length)return {sent:0,remaining:0}
   const candidates=hrdlogPlan(next.QRZ.records,next.HRDLOG.records||[])
   if(!candidates.length)return {sent:0,remaining:0}
   const known=[...(next.HRDLOG.records||[])], batch=candidates.slice(0,max);let sent=0
   for(let i=0;i<batch.length;i++){
     setProgress('HRDLog · '+(i+1)+'/'+batch.length)
     const q=batch[i]
     try{await pushHRDLog(connections.HRDLOG,next.QRZ.records[q.index]);known.push(next.QRZ.records[q.index]);sent++}catch(e){console.warn('HRDLog',e)}
     await sleep(120)
   }
   const payload={records:known,updatedAt:new Date().toISOString(),metadata:{...(next.HRDLOG.metadata||{}),source:'bootstrap_plus_online',onlineManaged:true}}
   await saveDataset('HRDLOG',payload);next.HRDLOG=payload
   return {sent,remaining:Math.max(0,candidates.length-batch.length)}
 }
 async function refreshAll(){
   if(syncing)return
   setSyncing(true);setMessage('');const next={...datasets},errors=[]
   const jobs=[
     ['QRZ',fetchQRZ,connections.QRZ],['WRL',fetchWRL,connections.WRL],['CLUBLOG',fetchClubLog,connections.CLUBLOG],
     ['EQSL',fetchEQSL,connections.EQSL],['EQSL_INBOX',fetchEQSLInbox,connections.EQSL],['LOTW',fetchLoTW,connections.LOTW],
   ]
   for(const [p,fn,c] of jobs){
     if(!configured(p,connections))continue
     setProgress('Atualizando '+LABELS[p]+'…')
     try{await persist(p,await fn(c),next)}catch(e){errors.push(LABELS[p]+': '+e.message)}
   }
   try{const h=await syncHrd(next,100);if(h.sent)setMessage('HRDLog atualizado com '+h.sent+' QSO(s).'+(h.remaining?' Restam '+h.remaining+' para o próximo ciclo.':''))}catch(e){errors.push('HRDLog: '+e.message)}
   setDatasets(next);setProgress('');setSyncing(false)
   if(errors.length)setMessage('Concluído com '+errors.length+' falha(s): '+errors.join(' | '))
   else if(!message)setMessage('Tudo atualizado.')
 }
 async function refreshOne(p){
   setSyncing(true);setProgress('Atualizando '+LABELS[p]+'…');setMessage('')
   try{
     const next={...datasets}, map={QRZ:fetchQRZ,WRL:fetchWRL,CLUBLOG:fetchClubLog,EQSL:fetchEQSL,EQSL_INBOX:fetchEQSLInbox,LOTW:fetchLoTW}
     const cred=p==='EQSL_INBOX'?connections.EQSL:connections[p]
     await persist(p,await map[p](cred),next);setDatasets(next);setMessage(LABELS[p]+' atualizado.')
   }catch(e){setMessage('Erro: '+e.message)}finally{setProgress('');setSyncing(false)}
 }
 async function importHrd(file){
   if(!file)return
   try{const records=parseAdif(await file.text());if(!records.length)throw new Error('Nenhum QSO válido no ADIF')
     const payload={records,updatedAt:new Date().toISOString(),metadata:{source:'bootstrap_adif',filename:file.name,managedAfterBootstrap:true}}
     await saveDataset('HRDLOG',payload);setDatasets({...datasets,HRDLOG:payload});setMessage('HRDLog reconciliado: '+fmt(records.length)+' QSOs conhecidos.')
   }catch(e){setMessage('Erro: '+e.message)}
 }
 async function updateHrd(){
   setSyncing(true);setMessage('')
   try{const next={...datasets},h=await syncHrd(next,500);setDatasets(next);setMessage(h.sent?('HRDLog: '+h.sent+' QSO(s) enviados/confirmados.'+(h.remaining?' Restam '+h.remaining+'.':'')):'Nenhum QSO seguro pendente no HRDLog.')}
   catch(e){setMessage('Erro: '+e.message)}finally{setProgress('');setSyncing(false)}
 }

 if(loading)return <div className="m-splash"><div className="m-logo">PU2<br/>BRU</div><h1>QSO Manager</h1><p>Preparando seu cockpit…</p></div>
 const nav=[['home','Início','⌂'],['log','Log','◎'],['issues','Pendências','!'],['qsl','QSL','✓'],['sources','Fontes','◉']]
 return <div className="m-app">
   <header className="m-top"><div><small>PU2BRU</small><h1>QSO Manager <span>v8</span></h1></div><button className={'m-sync '+(syncing?'spin':'')} disabled={syncing} onClick={refreshAll}>↻</button></header>
   {progress&&<div className="m-progress"><i/><span>{progress}</span></div>}
   {message&&<div className={'m-message top '+(message.startsWith('Erro')?'error':'')} onClick={()=>setMessage('')}>{message}<b>×</b></div>}
   <main>
   {tab==='home'&&<section className="m-page home">
     <div className="m-hero"><small>SEU LOG AGORA</small><h2>{fmt(model.rows.length)}</h2><p>QSOs consolidados</p><div className="m-hero-row"><span><b>{LOGS.filter(p=>datasets[p]?.updatedAt).length}</b> fontes de log</span><span><b>{model.qsls.length}</b> com QSL online</span></div></div>
     <h3 className="m-section-title">Precisa de atenção</h3>
     <div className="m-attention"><button onClick={()=>{setIssueFilter('MISSING');setTab('issues')}}><i className="warn">−</i><span><b>{fmt(counts.MISSING)}</b>Ausentes</span><em>›</em></button><button onClick={()=>{setIssueFilter('DIFFERENCE');setTab('issues')}}><i>≠</i><span><b>{fmt(counts.DIFFERENCE)}</b>Divergências</span><em>›</em></button><button onClick={()=>{setIssueFilter('DUPLICATE');setTab('issues')}}><i>!</i><span><b>{fmt(counts.DUPLICATE)}</b>Duplicidades</span><em>›</em></button><button onClick={()=>setTab('qsl')}><i className="ok">✓</i><span><b>{fmt(counts.QSL)}</b>Confirmações</span><em>›</em></button></div>
     <div className="m-card"><div className="m-card-head"><div><h3>Fontes</h3><p>Toque para configurar</p></div><button onClick={()=>setTab('sources')}>Ver todas</button></div><div className="m-source-dots">{KEYS.map(p=><button key={p} onClick={()=>{setSheet(p);setTab('sources')}} className={configured(p,connections)?'connected':''}><i>{SHORT[p]}</i><small>{datasets[p]?.records?.length?fmt(datasets[p].records.length):'—'}</small></button>)}</div></div>
     <button className="m-refresh-all" disabled={syncing} onClick={refreshAll}>↻ <span><b>Atualizar tudo</b><small>Buscar mudanças em todas as APIs</small></span></button>
   </section>}
   {tab==='log'&&<section className="m-page"><div className="m-page-title"><small>LOG CONSOLIDADO</small><h2>Seus QSOs</h2></div><div className="m-search">⌕<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Indicativo, país, grid, banda…"/>{search&&<button onClick={()=>setSearch('')}>×</button>}</div><div className="m-qso-list">{filteredLog.slice(0,1000).map(q=><article key={q.id}><div className="m-qso-main"><div><h3>{q.call}</h3><p>{q.date} · {q.time.slice(0,4)} UTC</p></div><div className="m-band"><b>{q.band}</b><small>{q.mode}</small></div></div><div className="m-qso-foot"><div>{q.providers.map(p=><Badge key={p} tone="ok">{SHORT[p]}</Badge>)}{q.missingIn.map(p=><Badge key={p} tone="warn">−{SHORT[p]}</Badge>)}</div>{q.differences.length>0&&<span className="m-alert-dot">!</span>}</div></article>)}</div>{!filteredLog.length&&<div className="m-empty">Nenhum QSO encontrado.</div>}</section>}
   {tab==='issues'&&<section className="m-page"><div className="m-page-title"><small>CAIXA DE ENTRADA</small><h2>Pendências</h2><p>Somente o que merece uma decisão.</p></div><div className="m-chips">{[['ALL','Tudo',model.issues.length],['MISSING','Ausentes',counts.MISSING],['DIFFERENCE','Diferenças',counts.DIFFERENCE],['DUPLICATE','Duplicados',counts.DUPLICATE],['QSL','QSL',counts.QSL]].map(x=><button key={x[0]} className={issueFilter===x[0]?'active':''} onClick={()=>setIssueFilter(x[0])}>{x[1]} <b>{fmt(x[2])}</b></button>)}</div><div className="m-issue-list">{filteredIssues.slice(0,1000).map((x,i)=><article key={i}><Icon type={x.type}/><div><h3>{x.call}<span>{x.band} · {x.mode}</span></h3><p>{x.date} {String(x.time||'').slice(0,4)} · {x.message}</p><div>{(x.sources||[]).map(p=><Badge key={p}>{SHORT[p]||p}</Badge>)}</div></div></article>)}</div>{!filteredIssues.length&&<div className="m-empty success">✓<b>Nada para revisar aqui.</b></div>}</section>}
   {tab==='qsl'&&<section className="m-page"><div className="m-page-title"><small>CENTRAL DE QSL</small><h2>Confirmações</h2><p>eQSL Inbox + LoTW, sempre online.</p></div><div className="m-qsl-summary"><div><b>{fmt(model.qsls.length)}</b><span>QSOs confirmados</span></div><div><b>{fmt(model.qsls.filter(x=>x.services.some(s=>s.kind==='LOTW')).length)}</b><span>LoTW</span></div><div><b>{fmt(model.qsls.filter(x=>x.services.some(s=>s.kind==='EQSL')).length)}</b><span>eQSL</span></div></div><div className="m-qso-list qsl">{model.qsls.slice(0,1000).map((q,i)=><article key={i}><div className="m-qso-main"><div><h3>{q.call}</h3><p>{q.date} · {q.band} · {q.mode}</p></div><div className="m-confirm">✓</div></div><div className="m-qsl-services">{q.services.map((s,j)=><div key={j}><Badge tone="ok">{s.source}</Badge><small>{s.date||'recebido · data não informada'}</small></div>)}</div></article>)}</div>{!model.qsls.length&&<div className="m-empty">Atualize eQSL Inbox e LoTW para ver confirmações.</div>}<div className="m-policy">QSO_DATE nunca é usado como data de recebimento da QSL.</div></section>}
   {tab==='sources'&&<section className="m-page"><div className="m-page-title"><small>FONTES ONLINE</small><h2>Conexões</h2><p>HRD local não participa do mobile.</p></div><div className="m-source-list">{KEYS.map(p=>{const on=configured(p,connections),snap=datasets[p]||{};return <article key={p}><button className="m-source-open" onClick={()=>setSheet(p)}><i className={on?'connected':''}>{SHORT[p]}</i><div><h3>{LABELS[p]}</h3><p>{on?'Conectado':'Não configurado'} · {fmt(snap.records?.length)} registros</p><small>Atualizado: {when(snap.updatedAt)}</small></div><em>›</em></button>{p==='HRDLOG'?<div className="m-source-actions"><label>Importar/Reconciliar ADIF<input type="file" accept=".adi,.adif,.txt" onChange={e=>importHrd(e.target.files?.[0])}/></label><button disabled={!on||!snap.updatedAt||syncing} onClick={updateHrd}>Atualizar online</button></div>:p!=='HRDLOG'&&<div className="m-source-actions"><button disabled={!on||syncing} onClick={()=>refreshOne(p)}>Atualizar agora</button></div>}{p==='HRDLOG'&&<p className="m-provider-note">Base inicial por ADIF. Depois, novos QSOs são enviados online pelo Upload Code. Alterações feitas direto no site exigem nova reconciliação.</p>}</article>})}</div></section>}
   </main>
   <nav className="m-bottom">{nav.map(x=><button key={x[0]} className={tab===x[0]?'active':''} onClick={()=>setTab(x[0])}><b>{x[2]}</b><span>{x[1]}</span>{x[0]==='issues'&&model.issues.length>0&&<i>{model.issues.length>99?'99+':model.issues.length}</i>}</button>)}</nav>
   {sheet&&<SourceSheet provider={sheet} connections={connections} onClose={()=>setSheet(null)} onSaved={async all=>{setConnections(all);setSheet(null)}}/>}
 </div>
}
