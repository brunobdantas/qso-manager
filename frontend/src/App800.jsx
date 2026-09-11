import React, { useEffect, useState } from 'react'
import App700 from './App700.jsx'

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...(options.headers||{})}})
  const text = await response.text()
  let payload = null
  if (text) { try { payload=JSON.parse(text) } catch { payload=text } }
  if (!response.ok) throw new Error(payload?.detail || payload?.message || payload || response.statusText)
  return payload
}
const fmt = n => Number(n||0).toLocaleString('pt-BR')
const dateFmt = v => v ? new Date(v).toLocaleString('pt-BR') : 'Nunca'
const short = p => ({CLUBLOG:'CL',EQSL_INBOX:'eQ+',HRDLOG:'HL'}[p] || p)
const FIELDS = {
  QRZ:[['api_key','QRZ Logbook API Key','password']],
  WRL:[['api_key','WRL Developer API Key','password'],['logbook_id','Logbook ID (opcional)','text']],
  CLUBLOG:[['email','E-mail','email'],['app_password','Application Password','password'],['callsign','Indicativo','text'],['api_key','API Key','password']],
  EQSL:[['username','Indicativo / Username','text'],['password','Senha','password'],['qth_nickname','QTH Nickname (opcional)','text']],
  LOTW:[['login','Login LoTW','text'],['password','Senha LoTW','password']],
  HRDLOG:[['callsign','Indicativo','text'],['upload_code','Upload Code','password']],
}
function Btn({children,kind='primary',...props}){return <button className={'v8-btn v8-'+kind} {...props}>{children}</button>}
function Badge({children,tone='neutral'}){return <span className={'v8-badge '+tone}>{children}</span>}
function Card({title,subtitle,children,action}){return <section className="v8-card"><header><div><h3>{title}</h3>{subtitle&&<p>{subtitle}</p>}</div>{action}</header>{children}</section>}

function Config({source,onClose,onSaved}){
  const key=source.provider==='EQSL_INBOX'?'EQSL':source.provider
  const [values,setValues]=useState(source.credentials||{})
  const [msg,setMsg]=useState('')
  const [busy,setBusy]=useState(false)
  async function save(test){
    setBusy(true);setMsg('')
    try{
      await api('/api/v8/connections/'+key,{method:'PUT',body:JSON.stringify({values})})
      if(test){const r=await api('/api/v8/connections/'+source.provider+'/test',{method:'POST',body:'{}'});setMsg(r.message||'Conexão validada.')}
      else setMsg('Configuração salva.')
      await onSaved()
    }catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}
  }
  return <div className="v8-modal-bg"><div className="v8-modal">
    <div className="v8-modal-head"><div><small>FONTE ONLINE</small><h2>{source.label}</h2></div><button onClick={onClose}>×</button></div>
    {source.provider==='EQSL_INBOX'&&<div className="v8-note">O Inbox usa a mesma conexão do eQSL OutBox.</div>}
    <div className="v8-fields">{(FIELDS[key]||[]).map(f=><label key={f[0]}><span>{f[1]}</span><input type={f[2]} value={values[f[0]]||''} placeholder={source.credentials?.[f[0]]||''} onChange={e=>setValues({...values,[f[0]]:e.target.value})}/></label>)}</div>
    {msg&&<div className={'v8-message '+(msg.startsWith('Erro')?'error':'')}>{msg}</div>}
    <div className="v8-modal-actions"><Btn kind="ghost" onClick={onClose}>Fechar</Btn><Btn kind="ghost" disabled={busy} onClick={()=>save(true)}>Salvar e testar</Btn><Btn disabled={busy} onClick={()=>save(false)}>Salvar</Btn></div>
  </div></div>
}

function Online({onBack}){
  const [tab,setTab]=useState('home'),[status,setStatus]=useState(null),[dash,setDash]=useState(null)
  const [log,setLog]=useState(null),[issues,setIssues]=useState(null),[qsl,setQsl]=useState(null)
  const [query,setQuery]=useState(''),[config,setConfig]=useState(null),[busy,setBusy]=useState(false),[msg,setMsg]=useState('')
  async function load(){const r=await Promise.all([api('/api/v8/status'),api('/api/v8/dashboard')]);setStatus(r[0]);setDash(r[1])}
  useEffect(()=>{load().catch(e=>setMsg('Erro: '+e.message))},[])
  async function open(next){
    setTab(next);setMsg('')
    try{
      if(next==='log')setLog(await api('/api/v8/log?page_size=100&q='+encodeURIComponent(query)))
      if(next==='issues')setIssues(await api('/api/v8/issues?limit=250'))
      if(next==='qsl')setQsl(await api('/api/v8/qsl'))
      if(next==='sources')await load()
    }catch(e){setMsg('Erro: '+e.message)}
  }
  async function syncAll(){setBusy(true);setMsg('Atualizando fontes online…');try{const r=await api('/api/v8/sync-all',{method:'POST',body:'{}'});const fail=(r.results||[]).filter(x=>!x.ok&&!x.skipped);setMsg(fail.length?'Concluído com '+fail.length+' falha(s).':'Fontes atualizadas e comparação recalculada.');await load()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  async function syncOne(p){setBusy(true);try{await api('/api/v8/sync/'+p,{method:'POST',body:'{}'});setMsg(p+' atualizado.');await load()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  async function importHrd(file){if(!file)return;setBusy(true);try{const r=await api('/api/v8/hrdlog/bootstrap',{method:'PUT',body:JSON.stringify({content:await file.text(),filename:file.name})});setMsg('HRDLog: '+fmt(r.records)+' QSOs conhecidos.');await load()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  async function updateHrd(){setBusy(true);try{const plan=await api('/api/v8/hrdlog/plan?limit=500');if(!plan.safe_missing){setMsg('HRDLog alinhado com o estado conhecido do QRZ.');return}if(!window.confirm('Enviar '+plan.candidates.length+' QSO(s) seguros ao HRDLog.net?'))return;const r=await api('/api/v8/hrdlog/push',{method:'POST',body:JSON.stringify({confirm:true,limit:500})});setMsg('HRDLog: '+fmt(r.sent_or_already_remote)+' atualizados; '+fmt(r.errors?.length)+' erro(s).');await load()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  const sum=dash?.summary||{}, counts=dash?.issues?.counts||{}, sources=status?.providers||[]
  const nav=[['home','Início','⌂'],['log','Log','◎'],['issues','Pendências','!'],['qsl','QSL','✓'],['sources','Fontes','◉']]
  return <div className="v8-shell">
    <header className="v8-top"><div><small>PU2BRU · QSO MANAGER</small><h1>Central Online <span>v8.0</span></h1></div><div><Btn kind="ghost" onClick={onBack}>← Desktop clássico</Btn><Btn disabled={busy} onClick={syncAll}>{busy?'Atualizando…':'Atualizar tudo'}</Btn></div></header>
    <nav className="v8-nav">{nav.map(n=><button key={n[0]} className={tab===n[0]?'active':''} onClick={()=>open(n[0])}><b>{n[2]}</b><span>{n[1]}</span></button>)}</nav>
    <main className="v8-main">
      {msg&&<div className={'v8-message '+(msg.startsWith('Erro')?'error':'')}>{msg}</div>}
      {tab==='home'&&<><div className="v8-hero"><div><small>ESTADO DO LOG</small><h2>{fmt(sum.logical_qsos)} QSOs consolidados</h2><p>Comparação automática entre fontes online. O HRD local não participa desta visão.</p></div><Btn onClick={()=>open('issues')}>Revisar pendências</Btn></div>
      <div className="v8-metrics"><div><span>Multifonte</span><b>{fmt(sum.multi_source)}</b></div><div><span>Ausentes</span><b>{fmt(counts.missing)}</b></div><div><span>Divergências</span><b>{fmt(counts.differences)}</b></div><div><span>Duplicidades</span><b>{fmt(counts.duplicates)}</b></div><div><span>QSL novas</span><b>{fmt(counts.qsl)}</b></div></div>
      <Card title="Fontes online" subtitle="Estado da última sincronização."><div className="v8-source-strip">{sources.map(s=><button key={s.provider} onClick={()=>{setConfig(s);setTab('sources')}}><i className={s.configured?'ok':''}>{short(s.provider)}</i><span><b>{s.label}</b><small>{s.configured?fmt(s.snapshot?.records)+' registros':'não configurado'}</small></span></button>)}</div></Card></>}
      {tab==='log'&&<><div className="v8-pagehead"><div><small>LOG CONSOLIDADO</small><h2>Um QSO, todas as fontes.</h2></div><div className="v8-search"><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Indicativo, país, grid…"/><Btn onClick={()=>open('log')}>Buscar</Btn></div></div><div className="v8-qso-list">{(log?.items||[]).map(q=><article key={q.logical_id}><div><h3>{q.call}</h3><p>{q.date} · {q.time?.slice(0,5)} UTC · <b>{q.band}</b> · {q.mode}</p></div><div className="v8-source-badges">{q.providers?.map(p=><Badge key={p} tone="ok">{short(p)}</Badge>)}{q.missing_in?.map(p=><Badge key={p} tone="warn">− {short(p)}</Badge>)}</div>{q.difference_count>0&&<Badge tone="warn">{q.difference_count} diferenças</Badge>}</article>)}</div>{!log?.items?.length&&<div className="v8-empty">Sincronize as fontes ou faça uma busca.</div>}</>}
      {tab==='issues'&&<><div className="v8-pagehead"><div><small>CAIXA DE ENTRADA</small><h2>Pendências que merecem sua atenção.</h2></div><span>{fmt(issues?.total)} ocorrências</span></div><div className="v8-filter-pills"><Badge tone="warn">{fmt(issues?.counts?.missing)} ausências</Badge><Badge>{fmt(issues?.counts?.differences)} divergências</Badge><Badge>{fmt(issues?.counts?.duplicates)} duplicidades</Badge><Badge tone="ok">{fmt(issues?.counts?.qsl)} QSL</Badge></div><div className="v8-issue-list">{(issues?.items||[]).map((x,i)=><article key={i}><div className={'v8-issue-icon '+x.type.toLowerCase()}>{x.type==='QSL'?'✓':x.type==='MISSING'?'−':'!'}</div><div><h3>{x.call} <small>{x.band} · {x.mode}</small></h3><p>{x.date} {x.time?.slice(0,5)} · {x.message}</p></div></article>)}</div></>}
      {tab==='qsl'&&<><div className="v8-pagehead"><div><small>CENTRAL DE QSL</small><h2>Confirmações online consolidadas.</h2><p>eQSL Inbox + LoTW. QSO_DATE nunca substitui data de confirmação.</p></div></div>{!qsl?.ready?<div className="v8-empty">Sincronize QRZ, eQSL Inbox e/ou LoTW.</div>:<><div className="v8-metrics"><div><span>Confirmados</span><b>{fmt(qsl.summary?.matched_confirmation_groups)}</b></div><div><span>Propostas</span><b>{fmt(qsl.summary?.actionable_proposals)}</b></div><div><span>Sem par</span><b>{fmt(qsl.summary?.unmatched_evidence)}</b></div><div><span>Conflitos</span><b>{fmt(qsl.summary?.date_conflicts)}</b></div></div><div className="v8-qso-list">{(qsl.proposals||[]).slice(0,300).map((p,i)=><article key={i}><div><h3>{p.qso?.call}</h3><p>{p.qso?.date} · {p.qso?.band} · {p.qso?.mode}</p></div><Badge tone="ok">{p.service}</Badge><div className="v8-qsl-detail"><b>{Object.entries(p.changes||{}).map(v=>v[0]+'='+v[1]).join(' · ')}</b><small>{p.reason}</small></div></article>)}</div></>}</>}
      {tab==='sources'&&<><div className="v8-pagehead"><div><small>FONTES</small><h2>Tudo online, exceto o bootstrap do HRDLog.</h2><p>HRD local permanece apenas no desktop clássico.</p></div></div><div className="v8-source-grid">{sources.map(s=><Card key={s.provider} title={s.label} subtitle={s.note} action={<span className={'v8-dot '+(s.configured?'ok':'')}/>}><div className="v8-source-stat"><b>{fmt(s.snapshot?.records)}</b><span>registros conhecidos</span><small>Atualizado: {dateFmt(s.snapshot?.downloaded_at)}</small></div><div className="v8-card-actions"><Btn kind="ghost" onClick={()=>setConfig(s)}>{s.configured?'Conexão':'Configurar'}</Btn>{s.provider==='HRDLOG'?<><label className="v8-file-btn">Importar/Reconciliar ADIF<input type="file" accept=".adi,.adif,.txt" onChange={e=>importHrd(e.target.files?.[0])}/></label><Btn disabled={busy||!s.configured||!s.snapshot?.downloaded_at} onClick={updateHrd}>Atualizar online</Btn></>:s.capabilities?.read&&<Btn disabled={busy||!s.configured} onClick={()=>syncOne(s.provider)}>Atualizar</Btn>}</div></Card>)}</div></>}
    </main>
    {config&&<Config source={config} onClose={()=>setConfig(null)} onSaved={load}/>}
  </div>
}

export default function App800(){
  const [online,setOnline]=useState(false)
  if(online)return <Online onBack={()=>setOnline(false)}/>
  return <div className="v8-host"><App700/><button className="v8-launcher" onClick={()=>setOnline(true)}><span>v8</span><b>Central Online</b><small>Mobile-first · APIs</small></button></div>
}
