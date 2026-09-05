import React, { useEffect, useMemo, useState } from 'react'

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } })
  const text = await response.text()
  let payload = null
  if (text) { try { payload = JSON.parse(text) } catch { payload = text } }
  if (!response.ok) {
    const detail = payload?.detail || payload?.message || payload || `${response.status} ${response.statusText}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return payload
}

const FIELDS = {
  QRZ: [['api_key','QRZ Logbook API Key','password']],
  WRL: [['api_key','Developer API Key','password'],['logbook_id','Logbook ID (opcional)','text']],
  CLUBLOG: [['email','E-mail','email'],['app_password','Application Password','password'],['callsign','Indicativo','text'],['api_key','API Key','password']],
  EQSL: [['username','Username / Indicativo','text'],['password','Senha eQSL','password'],['qth_nickname','QTH Nickname (opcional)','text']],
}

const NAV = [
  ['home','Central','⌂'],
  ['review','Revisar','≠'],
  ['qsos','Consultar QSOs','◎'],
  ['manual','Comparar ADI','⇄'],
  ['sources','Fontes & dados','◉'],
  ['security','Segurança','⌾'],
]

const sleep = ms => new Promise(r => setTimeout(r, ms))
const cls = (...x) => x.filter(Boolean).join(' ')
const fmt = n => Number(n || 0).toLocaleString('pt-BR')
const dateFmt = v => v ? new Date(v).toLocaleString('pt-BR') : 'Nunca'
const titleQso = q => `${q?.call || '—'} · ${q?.date || '—'} ${q?.time || ''} · ${q?.band || '—'} · ${q?.mode || '—'}`

function Button({ children, kind='primary', small=false, ...p }) { return <button className={cls('btn',`btn-${kind}`,small&&'btn-small')} {...p}>{children}</button> }
function Pill({ children, tone='neutral' }) { return <span className={`pill tone-${tone}`}>{children}</span> }
function Notice({ children, tone='info' }) { return <div className={`notice notice-${tone}`}>{children}</div> }
function Panel({ title, subtitle, action, children, className='' }) { return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div>{action}</div>{children}</section> }
function Empty({ children }) { return <div className="empty">{children || 'Nada para mostrar.'}</div> }

async function runSync(provider, onProgress) {
  let job = await api(`/api/cloud/sync-jobs/${provider}`, { method:'POST', body:'{}' })
  onProgress?.(job)
  while (!['succeeded','failed'].includes(job.status)) {
    await sleep(450)
    job = await api(`/api/cloud/sync-jobs/${job.job_id}`)
    onProgress?.(job)
  }
  if (job.status === 'failed') throw new Error(job.error || job.message || `Falha ao atualizar ${provider}`)
  return job
}

function Progress({ job }) {
  if (!job) return null
  const pct = Math.max(0, Math.min(100, Number(job.progress || 0)))
  const active = ['queued','running'].includes(job.status)
  return <div className={cls('progress-card',job.status==='failed'&&'failed',job.status==='succeeded'&&'done')}>
    <div><span>{job.message || 'Sincronizando…'}</span><b>{job.status==='failed'?'erro':`${pct}%`}</b></div>
    <div className={cls('progress-track',active&&job.phase==='downloading'&&'indeterminate')}><i style={{width:`${pct}%`}} /></div>
    {job.error&&<small>{job.error}</small>}
  </div>
}

function ConfigureModal({ provider, onClose, onSaved }) {
  const [values,setValues] = useState(provider?.credentials || {})
  const [busy,setBusy] = useState(false)
  const [msg,setMsg] = useState('')
  if (!provider) return null
  async function save(test=false) {
    setBusy(true); setMsg('')
    try {
      await api(`/api/cloud/connections/${provider.provider}`, { method:'PUT', body:JSON.stringify({values}) })
      if (test) {
        const r = await api(`/api/cloud/connections/${provider.provider}/test`, { method:'POST', body:'{}' })
        setMsg(`Conexão validada${r.records ? ` · ${fmt(r.records)} QSOs acessíveis` : ''}.`)
      } else setMsg('Configuração salva.')
      await onSaved()
    } catch(e) { setMsg(`Erro: ${e.message}`) } finally { setBusy(false) }
  }
  return <div className="modal-backdrop"><div className="modal">
    <div className="modal-title"><div><span className="eyebrow">CONEXÃO</span><h2>{provider.label}</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <p className="muted">Credenciais permanecem no backend local. A interface só exibe valores mascarados depois de salvos.</p>
    <div className="fields">{(FIELDS[provider.provider]||[]).map(([key,label,type])=><label key={key}><span>{label}</span><input type={type} value={values[key]||''} onChange={e=>setValues({...values,[key]:e.target.value})}/></label>)}</div>
    {msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}
    <div className="modal-actions"><Button kind="secondary" onClick={onClose}>Fechar</Button><div className="button-row"><Button kind="secondary" disabled={busy} onClick={()=>save(false)}>Salvar</Button><Button disabled={busy} onClick={()=>save(true)}>{busy?'Validando…':'Salvar e testar'}</Button></div></div>
  </div></div>
}

function LocalDataModal({ provider, onClose, onCleared }) {
  const [busy,setBusy] = useState(false)
  const [msg,setMsg] = useState('')
  const count = provider?.snapshot?.records || 0
  if (!provider) return null
  async function clear() {
    if (!window.confirm(`Apagar ${fmt(count)} QSOs do snapshot local de ${provider.label}?\n\nIsto NÃO apaga nada na plataforma remota e NÃO remove suas credenciais.`)) return
    setBusy(true); setMsg('')
    try {
      const r = await api(`/api/cloud/snapshots/${provider.provider}`, { method:'DELETE' })
      setMsg(`${fmt(r.records_removed)} QSOs removidos apenas deste computador.`)
      await onCleared()
    } catch(e) { setMsg(`Erro: ${e.message}`) } finally { setBusy(false) }
  }
  return <div className="modal-backdrop"><div className="modal">
    <div className="modal-title"><div><span className="eyebrow">DADOS LOCAIS</span><h2>{provider.label}</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <div className="local-data-summary"><strong>{fmt(count)}</strong><span>QSOs carregados localmente</span><small>Última atualização: {dateFmt(provider.snapshot?.downloaded_at)}</small></div>
    <Notice tone="info">Apagar o snapshot local limpa apenas a cópia usada pelo QSO Manager. A conta remota e as credenciais ficam intactas; basta sincronizar novamente para reconstruir a base.</Notice>
    {msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}
    <div className="modal-actions"><Button kind="secondary" onClick={onClose}>Fechar</Button><Button kind="danger" disabled={busy||count===0} onClick={clear}>{busy?'Apagando…':'Apagar dados locais'}</Button></div>
  </div></div>
}

function SourceCard({ p, job, onConfigure, onData, onSync }) {
  const busy = ['queued','running'].includes(job?.status)
  const count = p.snapshot?.records || 0
  return <article className={cls('source-card',p.provider==='QRZ'&&'source-card-truth')}>
    <div className="source-card-top"><div className="provider-logo">{p.provider==='CLUBLOG'?'CL':p.provider}</div><div className="source-title"><div><b>{p.label}</b>{p.provider==='QRZ'&&<Pill tone="truth">referência</Pill>}</div><span>{p.configured?'Conectado':'Não configurado'}</span></div><span className={cls('status-light',p.configured&&'online')} /></div>
    <div className="source-stat"><strong>{fmt(count)}</strong><span>QSOs locais</span></div>
    <div className="source-meta">Atualizado: <b>{dateFmt(p.snapshot?.downloaded_at)}</b></div>
    <Progress job={job}/>
    <div className="source-actions triple"><Button kind="secondary" small onClick={()=>onConfigure(p)}>Conexão</Button><Button kind="secondary" small onClick={()=>onData(p)}>Dados locais</Button><Button small disabled={!p.configured||busy} onClick={()=>onSync(p.provider)}>{busy?'Atualizando…':'Atualizar'}</Button></div>
  </article>
}

function Home({ status, analysis, refresh, navigate, onConfigure, onData }) {
  const [jobs,setJobs] = useState({})
  const [msg,setMsg] = useState('')
  const [busy,setBusy] = useState(false)
  const providers = status?.providers || []
  const summary = analysis?.summary || {}
  const connected = providers.filter(p=>p.configured).length
  const reviewCount = (summary.qrz_stale_candidates||0)+(summary.missing_elsewhere||0)+(summary.field_differences||0)+(summary.probable_duplicates||0)
  async function syncOne(provider) {
    setMsg('')
    try { const j=await runSync(provider,x=>setJobs(v=>({...v,[provider]:x}))); setMsg(`${provider}: ${fmt(j.records)} QSOs atualizados.`); await refresh() }
    catch(e){setMsg(`Erro em ${provider}: ${e.message}`)}
  }
  async function syncAll() {
    setBusy(true); setMsg('Atualizando fontes conectadas…')
    const errs=[]
    for (const p of providers.filter(x=>x.configured)) { try { await runSync(p.provider,x=>setJobs(v=>({...v,[p.provider]:x}))) } catch(e){errs.push(`${p.provider}: ${e.message}`)} }
    await refresh(); setBusy(false); setMsg(errs.length?`Concluído com ${errs.length} erro(s): ${errs.join(' | ')}`:'Todas as fontes foram atualizadas.')
  }
  return <>
    <div className="page-hero"><div><span className="eyebrow">CENTRAL DE OPERAÇÃO</span><h1>Gerencie seus QSOs por tarefa, não por plataforma.</h1><p>O QRZ orienta a verdade canônica; WRL, Club Log e eQSL ajudam a validar, corrigir e manter o ecossistema alinhado.</p></div><Button onClick={syncAll} disabled={busy||connected===0}>{busy?'Atualizando…':'Atualizar tudo'}</Button></div>
    {msg&&<Notice tone={msg.startsWith('Erro')||msg.includes('erro(s)')?'error':'info'}>{msg}</Notice>}
    <div className="journey-grid">
      <button onClick={()=>navigate('sources')}><span>01</span><b>Atualizar fontes</b><small>{connected}/4 conectadas</small></button>
      <button onClick={()=>navigate('review')}><span>02</span><b>Revisar pendências</b><small>{fmt(reviewCount)} itens para decisão</small></button>
      <button onClick={()=>navigate('qsos')}><span>03</span><b>Encontrar um QSO</b><small>Pesquisar em todas as bases</small></button>
      <button onClick={()=>navigate('manual')}><span>04</span><b>Comparar arquivos</b><small>ADI manual quando precisar</small></button>
    </div>
    <div className="truth-banner"><div className="truth-icon">★</div><div><b>QRZ é a referência preferencial, mas pode estar desatualizado.</b><span>{status?.truth_policy}</span></div></div>
    <div className="metric-grid"><div className="metric"><span>QSOs no QRZ</span><strong>{fmt(summary.qrz_records)}</strong><small>base preferencial</small></div><div className="metric metric-warn"><span>QRZ pode estar atrasado</span><strong>{fmt(summary.qrz_stale_candidates)}</strong><small>{fmt(summary.qrz_likely_stale)} com evidência forte</small></div><div className="metric"><span>Faltando em outras bases</span><strong>{fmt(summary.missing_elsewhere)}</strong><small>candidatos a sincronização</small></div><div className="metric"><span>Campos divergentes</span><strong>{fmt(summary.field_differences)}</strong><small>filtráveis por campo e fonte</small></div><div className="metric"><span>Duplicidades</span><strong>{fmt(summary.probable_duplicates)}</strong><small>revisar antes de agir</small></div></div>
    <Panel title="Saúde das fontes" subtitle="Último snapshot local e estado de sincronização."><div className="source-grid">{providers.map(p=><SourceCard key={p.provider} p={p} job={jobs[p.provider]} onConfigure={onConfigure} onData={onData} onSync={syncOne}/>)}</div></Panel>
  </>
}

function Review({ status, analysis, refresh }) {
  const [tab,setTab] = useState('qrz')
  const [target,setTarget] = useState('ALL')
  const [field,setField] = useState('ALL')
  const [fieldProvider,setFieldProvider] = useState('ALL')
  const [msg,setMsg] = useState('')
  const [busy,setBusy] = useState('')
  const providers=status?.providers||[]
  const configured=new Set(providers.filter(p=>p.configured).map(p=>p.provider))
  const byProvider=Object.fromEntries(providers.map(p=>[p.provider,p]))
  if(!analysis?.ready) return <Panel title="Revisar"><Empty>Sincronize o QRZ e outra fonte primeiro.</Empty></Panel>
  const missing=(analysis.missing_elsewhere||[]).filter(x=>target==='ALL'||x.target===target)
  const fields=(analysis.field_differences||[]).filter(x=>(field==='ALL'||x.field===field)&&(fieldProvider==='ALL'||x.provider===fieldProvider))
  const fieldNames=[...new Set((analysis.field_differences||[]).map(x=>x.field))].sort()
  async function publish(source,index,targetProvider,label){setBusy(`${source}-${index}-${targetProvider}`);try{await api('/api/cloud/publish',{method:'POST',body:JSON.stringify({source,index,target:targetProvider,confirm:false})});if(!window.confirm(`${label}\n\nEnviar este QSO para ${targetProvider}?`))return;await api('/api/cloud/publish',{method:'POST',body:JSON.stringify({source,index,target:targetProvider,confirm:true})});setMsg(`QSO enviado para ${targetProvider}.`);await refresh()}catch(e){setMsg(`Erro: ${e.message}`)}finally{setBusy('')}}
  async function remove(provider,index,label){setBusy(`del-${provider}-${index}`);try{await api(`/api/cloud/remote/${provider}/delete`,{method:'POST',body:JSON.stringify({index,confirm:false})});if(!window.confirm(`${label}\n\nExcluir este QSO de ${provider}? O QRZ continuará sem este registro.`))return;await api(`/api/cloud/remote/${provider}/delete`,{method:'POST',body:JSON.stringify({index,confirm:true})});try{await runSync(provider)}catch{};setMsg(`QSO excluído de ${provider}.`);await refresh()}catch(e){setMsg(`Erro: ${e.message}`)}finally{setBusy('')}}
  return <>
    <div className="page-hero compact"><div><span className="eyebrow">FILA DE DECISÃO</span><h1>Revisar antes de sincronizar.</h1><p>Cada aba responde a uma pergunta: o QRZ está atrasado, outra plataforma está atrasada, ou os campos discordam?</p></div></div>
    {msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}
    <div className="tabs"><button className={tab==='qrz'?'active':''} onClick={()=>setTab('qrz')}>QRZ atrasado ({fmt(analysis.qrz_stale_candidates?.length)})</button><button className={tab==='targets'?'active':''} onClick={()=>setTab('targets')}>Faltando nas bases ({fmt(analysis.missing_elsewhere?.length)})</button><button className={tab==='fields'?'active':''} onClick={()=>setTab('fields')}>Campos ({fmt(analysis.field_differences?.length)})</button><button className={tab==='dupes'?'active':''} onClick={()=>setTab('dupes')}>Duplicidades ({fmt(analysis.probable_duplicates?.length)})</button></div>
    {tab==='qrz'&&<Panel title="Ausentes no QRZ" subtitle="Você pode adicionar ao QRZ ou manter o QRZ como correto e excluir das plataformas que possuem o registro.">{!(analysis.qrz_stale_candidates||[]).length?<Empty/>:<div className="case-list">{analysis.qrz_stale_candidates.map((q,i)=>{const source=q.sources?.find(s=>configured.has(s))||q.sources?.[0];const idx=q.source_indexes?.[source];return <div className="case-row" key={i}><div className="case-main"><div className="case-title"><b>{titleQso(q)}</b><Pill tone={q.evidence_count>=2?'warn':'neutral'}>{q.evidence_count>=2?'forte evidência':'revisar'}</Pill></div><p>{q.reason}</p><div className="evidence">{(q.sources||[]).map(s=><Pill key={s} tone="ok">{s}</Pill>)}</div></div><div className="case-actions">{configured.has('QRZ')&&idx!=null&&<Button small disabled={!!busy} onClick={()=>publish(source,idx,'QRZ',titleQso(q))}>Adicionar ao QRZ</Button>}{(q.sources||[]).map(s=>{const pi=byProvider[s];const si=q.source_indexes?.[s];return pi?.capabilities?.delete&&si!=null?<Button key={s} small kind="danger" disabled={!!busy} onClick={()=>remove(s,si,titleQso(q))}>Excluir do {s}</Button>:null})}</div></div>})}</div>}</Panel>}
    {tab==='targets'&&<><div className="filter-bar"><label><span>Plataforma</span><select value={target} onChange={e=>setTarget(e.target.value)}><option value="ALL">Todas</option>{providers.filter(p=>p.provider!=='QRZ').map(p=><option key={p.provider}>{p.provider}</option>)}</select></label><Pill>{fmt(missing.length)} itens</Pill></div><Panel title="Presentes no QRZ e ausentes em outras bases">{!missing.length?<Empty/>:<div className="case-list">{missing.map((q,i)=><div className="case-row" key={i}><div><b>{titleQso(q)}</b><p>{q.reason}</p></div><div className="case-actions"><Pill tone="warn">falta em {q.target}</Pill>{configured.has(q.target)&&<Button small onClick={()=>publish('QRZ',q.qrz_index,q.target,titleQso(q))}>Enviar para {q.target}</Button>}</div></div>)}</div>}</Panel></>}
    {tab==='fields'&&<><div className="filter-bar"><label><span>Campo</span><select value={field} onChange={e=>setField(e.target.value)}><option value="ALL">Todos</option>{fieldNames.map(x=><option key={x}>{x}</option>)}</select></label><label><span>Fonte</span><select value={fieldProvider} onChange={e=>setFieldProvider(e.target.value)}><option value="ALL">Todas</option>{providers.filter(p=>p.provider!=='QRZ').map(p=><option key={p.provider}>{p.provider}</option>)}</select></label><Pill>{fmt(fields.length)} divergências</Pill></div><Panel title="Campos divergentes">{!fields.length?<Empty/>:<div className="table-wrap"><table><thead><tr><th>QSO</th><th>Campo</th><th>QRZ</th><th>Outra base</th><th>Fonte</th></tr></thead><tbody>{fields.map((d,i)=><tr key={i}><td><b>{d.call}</b><small>{d.date} {d.time} · {d.band}</small></td><td>{d.field}</td><td className="preferred">{String(d.value_a??'∅')}</td><td>{String(d.value_b??'∅')}</td><td><Pill>{d.provider}</Pill></td></tr>)}</tbody></table></div>}</Panel></>}
    {tab==='dupes'&&<Panel title="Duplicidades prováveis">{!(analysis.probable_duplicates||[]).length?<Empty/>:<div className="case-list">{analysis.probable_duplicates.map((d,i)=><div className="case-row" key={i}><div><b>{d.call} · {d.date} · {d.band} · {d.mode}</b><p>{d.reason}</p></div><Pill tone="warn">{d.source}</Pill></div>)}</div>}</Panel>}
  </>
}

function QsoSearch({ status, refresh }) {
  const [call,setCall]=useState(''),[rows,setRows]=useState([]),[msg,setMsg]=useState(''),[loading,setLoading]=useState(false)
  async function search(e){e?.preventDefault();setLoading(true);try{const r=await api(`/api/cloud/search?call=${encodeURIComponent(call)}&limit=1000`);setRows(r.items||[]);setMsg(r.truncated?'Resultado limitado a 1.000 registros.':'')}catch(e){setMsg(`Erro: ${e.message}`)}finally{setLoading(false)}}
  return <><div className="page-hero compact"><div><span className="eyebrow">CONSULTA MULTIFONTE</span><h1>Encontre um QSO em segundos.</h1><p>Pesquise um indicativo e veja o que cada plataforma sabe sobre ele.</p></div></div><Panel title="Pesquisar"><form className="searchbar" onSubmit={search}><input value={call} onChange={e=>setCall(e.target.value.toUpperCase())} placeholder="Ex.: LU6YR"/><Button disabled={loading}>{loading?'Buscando…':'Buscar'}</Button></form>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'info'}>{msg}</Notice>}</Panel><Panel title={`Resultados (${fmt(rows.length)})`}>{!rows.length?<Empty>Digite um indicativo para pesquisar.</Empty>:<div className="table-wrap"><table><thead><tr><th>Fonte</th><th>QSO</th><th>Freq.</th><th>RST</th><th>Grid</th><th>ID remoto</th></tr></thead><tbody>{rows.map((r,i)=>{const x=r.record||{};return <tr key={i}><td><Pill tone={r.provider==='QRZ'?'truth':'neutral'}>{r.provider}</Pill></td><td><b>{x.CALL}</b><small>{x.QSO_DATE} {x.TIME_ON} · {x.BAND} · {x.SUBMODE||x.MODE}</small></td><td>{x.FREQ||'—'}</td><td>{x.RST_SENT||'—'} / {x.RST_RCVD||'—'}</td><td>{x.GRIDSQUARE||'—'}</td><td><code>{r.external_id||'—'}</code></td></tr>})}</tbody></table></div>}</Panel></>
}

function ManualCompare(){const[a,setA]=useState(null),[b,setB]=useState(null),[result,setResult]=useState(null),[msg,setMsg]=useState(''),[busy,setBusy]=useState(false);async function compare(){if(!a||!b)return setMsg('Selecione os dois arquivos ADIF.');setBusy(true);try{const[ca,cb]=await Promise.all([a.text(),b.text()]);setResult(await api('/api/comparisons/adif',{method:'POST',body:JSON.stringify({a:{content:ca,source:'LOG_A',filename:a.name,coverage:'FULL_EXPORT'},b:{content:cb,source:'LOG_B',filename:b.name,coverage:'FULL_EXPORT'}})}))}catch(e){setMsg(`Erro: ${e.message}`)}finally{setBusy(false)}}return <><div className="page-hero compact"><div><span className="eyebrow">COMPARAÇÃO MANUAL</span><h1>Compare dois ADIs quando quiser.</h1><p>Útil para qualquer fonte sem API ou para auditorias pontuais.</p></div></div><div className="two-col"><Panel title="Log A"><input type="file" accept=".adi,.adif,.txt" onChange={e=>setA(e.target.files?.[0])}/><p className="muted">{a?.name||'Nenhum arquivo'}</p></Panel><Panel title="Log B"><input type="file" accept=".adi,.adif,.txt" onChange={e=>setB(e.target.files?.[0])}/><p className="muted">{b?.name||'Nenhum arquivo'}</p></Panel></div><div className="center-action"><Button disabled={busy} onClick={compare}>{busy?'Comparando…':'Comparar ADIs'}</Button></div>{msg&&<Notice tone="error">{msg}</Notice>}{result&&<div className="metric-grid four"><div className="metric"><span>Pareados</span><strong>{fmt(result.summary?.matched)}</strong></div><div className="metric"><span>Presença</span><strong>{fmt((result.missing_in_a||[]).length+(result.missing_in_b||[]).length)}</strong></div><div className="metric"><span>Campos</span><strong>{fmt(result.summary?.field_differences)}</strong></div><div className="metric"><span>Duplicidades</span><strong>{fmt(result.summary?.probable_duplicates)}</strong></div></div>}</>}

function Sources({ status, refresh, onConfigure, onData }) {
  const [jobs,setJobs]=useState({}),[msg,setMsg]=useState('')
  async function sync(p){try{const j=await runSync(p,x=>setJobs(v=>({...v,[p]:x})));setMsg(`${p}: ${fmt(j.records)} QSOs carregados.`);await refresh()}catch(e){setMsg(`Erro: ${e.message}`)}}
  return <><div className="page-hero compact"><div><span className="eyebrow">FONTES & DADOS LOCAIS</span><h1>Conectar, atualizar e limpar sem confusão.</h1><p>Conexão e dados locais são coisas diferentes: você pode apagar um snapshot do computador sem tocar na plataforma remota.</p></div></div>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}<div className="journey-strip"><div><b>1. Conectar</b><span>Cadastre credenciais</span></div><i>→</i><div><b>2. Atualizar</b><span>Baixe o snapshot</span></div><i>→</i><div><b>3. Revisar</b><span>Compare e decida</span></div></div><div className="source-grid">{(status?.providers||[]).map(p=><SourceCard key={p.provider} p={p} job={jobs[p.provider]} onConfigure={onConfigure} onData={onData} onSync={sync}/>)}</div></>
}

function Security(){return <><div className="page-hero compact"><div><span className="eyebrow">SEGURANÇA</span><h1>Leitura ampla; escrita deliberada.</h1><p>O sistema nunca altera o QRZ automaticamente e separa claramente exclusão local de exclusão remota.</p></div></div><div className="security-grid"><Panel title="QRZ"><p>Adicionar exige confirmação. DELETE/REPLACE permanecem bloqueados.</p></Panel><Panel title="WRL"><p>Inclusão, edição e exclusão remota usam ID estável e confirmação.</p></Panel><Panel title="Club Log"><p>Inclusão e exclusão remota são suportadas com confirmação.</p></Panel><Panel title="eQSL"><p>Leitura e inclusão; exclusão remota não é oferecida.</p></Panel></div><Panel title="Dados locais"><p>“Apagar dados locais” remove somente o snapshot ativo do QSO Manager. Credenciais, backups e dados nas plataformas não são apagados.</p></Panel></>}

export default function App(){const[view,setView]=useState('home'),[status,setStatus]=useState(null),[analysis,setAnalysis]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[configure,setConfigure]=useState(null),[dataModal,setDataModal]=useState(null);async function refresh(){setError('');try{const[s,a]=await Promise.all([api('/api/cloud/status'),api('/api/cloud/analysis')]);setStatus(s);setAnalysis(a)}catch(e){setError(e.message)}finally{setLoading(false)}}useEffect(()=>{refresh()},[]);const pageTitle=useMemo(()=>NAV.find(n=>n[0]===view)?.[1]||'QSO Manager',[view]);return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark">PU</div><div><b>QSO Manager</b><span>PU2BRU · v5.2</span></div></div><nav>{NAV.map(([k,l,icon])=><button key={k} className={view===k?'active':''} onClick={()=>setView(k)}><span className="nav-icon">{icon}</span><span>{l}</span>{k==='review'&&(analysis?.summary?.qrz_stale_candidates||0)>0&&<em>{analysis.summary.qrz_stale_candidates}</em>}</button>)}</nav><div className="sidebar-bottom"><span className="dot dot-on"/><div><b>Modo local</b><small>dados no seu PC</small></div></div></aside><main><header className="topbar"><div><span className="eyebrow">PU2BRU QSO MANAGER</span><h3>{pageTitle}</h3></div><div className="top-sources">{(status?.providers||[]).map(p=><div className="source-badge" key={p.provider}><span className={cls('dot',p.configured?'dot-on':'dot-off')}/><b>{p.provider}</b><span>{p.configured?`${fmt(p.snapshot?.records)} QSOs`:'não conectado'}</span></div>)}</div></header><div className="content">{error&&<Notice tone="error">{error}</Notice>}{loading?<div className="loading">Carregando…</div>:<>{view==='home'&&<Home status={status} analysis={analysis} refresh={refresh} navigate={setView} onConfigure={setConfigure} onData={setDataModal}/>} {view==='review'&&<Review status={status} analysis={analysis} refresh={refresh}/>} {view==='qsos'&&<QsoSearch status={status} refresh={refresh}/>} {view==='manual'&&<ManualCompare/>} {view==='sources'&&<Sources status={status} refresh={refresh} onConfigure={setConfigure} onData={setDataModal}/>} {view==='security'&&<Security/>}</>}</div></main>{configure&&<ConfigureModal provider={configure} onClose={()=>setConfigure(null)} onSaved={refresh}/>} {dataModal&&<LocalDataModal provider={dataModal} onClose={()=>setDataModal(null)} onCleared={async()=>{await refresh();setDataModal(null)}}/>}</div>}
