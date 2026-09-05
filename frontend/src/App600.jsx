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

const PROVIDER_FIELDS = {
  QRZ: [['api_key','QRZ Logbook API Key','password','Chave do logbook em QRZ → Logbook → Settings → API']],
  WRL: [['api_key','Developer API Key','password','Gerada em Integrations → Developer API'],['logbook_id','Logbook ID (opcional)','text','Deixe vazio para o logbook padrão']],
  CLUBLOG: [['email','E-mail','email','Conta do Club Log'],['app_password','Application Password','password','Prefira uma Application Password'],['callsign','Indicativo','text','Ex.: PU2BRU'],['api_key','API Key','password','Necessária para enviar/excluir']],
  EQSL: [['username','Username / Indicativo','text','Ex.: PU2BRU'],['password','Senha eQSL','password','Fica somente no backend local'],['qth_nickname','QTH Nickname (opcional)','text','Use se sua conta tiver mais de um QTH']],
}

const NAV = [
  ['home','Central','⌂'],
  ['manager','QSO Manager','▦'],
  ['review','Revisar','≠'],
  ['manual','Comparar ADI','⇄'],
  ['sources','Fontes & dados','◉'],
  ['activity','Atividade','◷'],
  ['security','Segurança','⌾'],
]

const DEFAULT_COLUMNS = ['date','call','band','mode','freq','country','grid','sources','status']
const COLUMN_LABELS = {
  date:'Data / hora', call:'Indicativo', band:'Banda', mode:'Modo', freq:'Frequência', country:'País', state:'Estado', county:'County', grid:'Grid', name:'Nome', qth:'QTH', rst:'RST', comment:'Comentário', qsl:'QSL', sources:'Fontes', missing:'Ausente em', differences:'Diferenças', duplicate:'Duplicidade', status:'Status'
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const cls = (...x) => x.filter(Boolean).join(' ')
const fmt = n => Number(n || 0).toLocaleString('pt-BR')
const dateFmt = v => v ? new Date(v).toLocaleString('pt-BR') : 'Nunca'
const qsoTitle = q => `${q?.call || '—'} · ${q?.date || '—'} ${q?.time || ''} · ${q?.band || '—'} · ${q?.mode || '—'}`

function Button({ children, kind='primary', small=false, ...props }) { return <button className={cls('btn',`btn-${kind}`,small&&'btn-small')} {...props}>{children}</button> }
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

async function pollBulk(jobId, onProgress) {
  let job = await api(`/api/qso-manager/bulk/jobs/${jobId}`)
  onProgress?.(job)
  while (!['succeeded','failed'].includes(job.status)) {
    await sleep(500)
    job = await api(`/api/qso-manager/bulk/jobs/${jobId}`)
    onProgress?.(job)
  }
  if (job.status === 'failed') throw new Error(job.errors?.[0]?.error || job.message || 'Falha na ação em lote')
  return job
}

function Progress({ job, compact=false }) {
  if (!job) return null
  const pct = Math.max(0, Math.min(100, Number(job.progress || 0)))
  const active = ['queued','running'].includes(job.status)
  return <div className={cls('progress-card',compact&&'compact',job.status==='failed'&&'failed',job.status==='succeeded'&&'done')}>
    <div><span>{job.message || 'Processando…'}</span><b>{job.status==='failed'?'erro':`${pct}%`}</b></div>
    <div className={cls('progress-track',active&&job.phase==='downloading'&&'indeterminate')}><i style={{width:`${pct}%`}} /></div>
    {job.errors?.length>0&&<small>{job.errors[0]?.error}</small>}
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
        const result = await api(`/api/cloud/connections/${provider.provider}/test`, { method:'POST', body:'{}' })
        setMsg(`Conexão validada${result.records ? ` · ${fmt(result.records)} QSOs acessíveis` : ''}.`)
      } else setMsg('Configuração salva no computador.')
      await onSaved()
    } catch(e) { setMsg(`Erro: ${e.message}`) } finally { setBusy(false) }
  }
  async function disconnect() {
    if (!window.confirm(`Desconectar ${provider.label}? Os dados locais serão preservados.`)) return
    setBusy(true)
    try { await api(`/api/cloud/connections/${provider.provider}`, {method:'DELETE'}); await onSaved(); onClose() }
    catch(e){setMsg(`Erro: ${e.message}`)} finally {setBusy(false)}
  }
  return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div className="modal">
    <div className="modal-title"><div><span className="eyebrow">CONEXÃO SEGURA</span><h2>{provider.label}</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <p className="muted">As credenciais ficam no backend local. O navegador recebe somente versões mascaradas.</p>
    <div className="fields">{(PROVIDER_FIELDS[provider.provider]||[]).map(([key,label,type,help])=><label key={key}><span>{label}</span><input type={type} value={values[key]||''} onChange={e=>setValues({...values,[key]:e.target.value})} placeholder={provider.credentials?.[key]||''}/><small>{help}</small></label>)}</div>
    {msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}
    <div className="modal-actions"><div>{provider.configured&&<Button kind="danger" disabled={busy} onClick={disconnect}>Desconectar</Button>}</div><div className="button-row"><Button kind="secondary" disabled={busy} onClick={()=>save(false)}>Salvar</Button><Button disabled={busy} onClick={()=>save(true)}>{busy?'Validando…':'Salvar e testar'}</Button></div></div>
  </div></div>
}

function LocalDataModal({ provider, onClose, onCleared }) {
  const [busy,setBusy] = useState(false)
  const [msg,setMsg] = useState('')
  const count = provider?.snapshot?.records || 0
  const isLocal = provider?.source_kind === 'local_adif'
  if (!provider) return null
  async function importADIF(file) {
    if (!file) return
    setBusy(true); setMsg('Lendo e validando o arquivo…')
    try {
      const result = await api(`/api/cloud/snapshots/${provider.provider}/adif`, { method:'PUT', body:JSON.stringify({content:await file.text(),filename:file.name}) })
      setMsg(`${fmt(result.records)} QSOs importados de ${file.name}.`)
      await onCleared()
    } catch(e){setMsg(`Erro: ${e.message}`)} finally {setBusy(false)}
  }
  async function clear() {
    if (!window.confirm(`Apagar ${fmt(count)} QSOs do snapshot local de ${provider.label}?\n\n${isLocal?'O arquivo ADIF original não será alterado.':'Nada será apagado na plataforma remota. As credenciais serão mantidas.'}`)) return
    setBusy(true); setMsg('')
    try {
      const result = await api(`/api/cloud/snapshots/${provider.provider}`, { method:'DELETE' })
      setMsg(`${fmt(result.records_removed)} QSOs removidos somente deste computador.`)
      await onCleared()
    } catch(e){setMsg(`Erro: ${e.message}`)} finally {setBusy(false)}
  }
  return <div className="modal-backdrop"><div className="modal">
    <div className="modal-title"><div><span className="eyebrow">DADOS LOCAIS</span><h2>{provider.label}</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <div className="local-data-summary"><strong>{fmt(count)}</strong><span>QSOs no snapshot ativo</span><small>Atualizado: {dateFmt(provider.snapshot?.downloaded_at)}</small></div>
    <Notice>{isLocal?'Importe o export ADIF completo do Ham Radio Deluxe. Ele será preservado como uma fonte e comparado com os logbooks online. Uma nova importação substitui o snapshot anterior com backup automático.':'Esta ação remove somente a cópia local usada nas comparações. Conta remota, credenciais e backups não são apagados.'}</Notice>
    {msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}
    <div className="modal-actions"><Button kind="secondary" onClick={onClose}>Fechar</Button><div className="button-row">{isLocal&&<label className="btn btn-primary"><input style={{display:'none'}} type="file" accept=".adi,.adif,.txt" disabled={busy} onChange={e=>{const file=e.target.files?.[0];importADIF(file);e.target.value=''}}/>{busy?'Importando…':count?'Substituir ADIF':'Importar ADIF'}</label>}<Button kind="danger" disabled={busy||count===0} onClick={clear}>{busy?'Processando…':'Apagar dados locais'}</Button></div></div>
  </div></div>
}

function SourceCard({ p, job, onConfigure, onData, onSync }) {
  const busy = ['queued','running'].includes(job?.status)
  const isLocal = p.source_kind === 'local_adif'
  return <article className={cls('source-card',p.provider==='QRZ'&&'source-card-truth')}>
    <div className="source-card-top"><div className="provider-logo">{p.provider==='CLUBLOG'?'CL':p.provider}</div><div className="source-title"><div><b>{p.label}</b>{p.provider==='QRZ'&&<Pill tone="truth">referência</Pill>}{isLocal&&<Pill>ADIF local</Pill>}</div><span>{isLocal?(p.configured?'Snapshot carregado':'Aguardando ADIF'):(p.configured?'Conectado':'Não configurado')}</span></div><span className={cls('status-light',p.configured&&'online')}/></div>
    <div className="source-stat"><strong>{fmt(p.snapshot?.records)}</strong><span>QSOs locais</span></div>
    <div className="source-meta">Atualizado: <b>{dateFmt(p.snapshot?.downloaded_at)}</b>{isLocal&&p.snapshot?.metadata?.filename&&<><br/>Arquivo: <b>{p.snapshot.metadata.filename}</b></>}</div>
    <Progress job={job} compact/>
    {isLocal?<div className="source-actions"><Button small onClick={()=>onData(p)}>{p.configured?'Substituir ADIF':'Importar ADIF'}</Button>{p.configured&&<Button kind="secondary" small onClick={()=>onData(p)}>Dados locais</Button>}</div>:<div className="source-actions triple"><Button kind="secondary" small onClick={()=>onConfigure(p)}>Conexão</Button><Button kind="secondary" small onClick={()=>onData(p)}>Dados locais</Button><Button small disabled={!p.configured||busy} onClick={()=>onSync(p.provider)}>{busy?'Atualizando…':'Atualizar'}</Button></div>}
  </article>
}

function Dashboard({ status, analysis, workspace, refresh, navigate, onConfigure, onData }) {
  const [jobs,setJobs] = useState({})
  const [msg,setMsg] = useState('')
  const [busy,setBusy] = useState(false)
  const providers = status?.providers || []
  const summary = workspace?.summary || {}
  const remoteProviders = providers.filter(p=>p.source_kind!=='local_adif')
  const connected = remoteProviders.filter(p=>p.configured).length
  async function syncOne(provider) {
    setMsg('')
    try { const job=await runSync(provider,x=>setJobs(v=>({...v,[provider]:x}))); setMsg(`${provider}: ${fmt(job.records)} QSOs atualizados.`); await refresh() }
    catch(e){setMsg(`Erro em ${provider}: ${e.message}`)}
  }
  async function syncAll() {
    setBusy(true); setMsg('Atualizando fontes conectadas…')
    const errors=[]
    for(const p of remoteProviders.filter(x=>x.configured)){try{await runSync(p.provider,x=>setJobs(v=>({...v,[p.provider]:x})))}catch(e){errors.push(`${p.provider}: ${e.message}`)}}
    await refresh(); setBusy(false); setMsg(errors.length?`Concluído com ${errors.length} erro(s): ${errors.join(' | ')}`:'Todas as fontes foram atualizadas.')
  }
  return <>
    <div className="page-hero"><div><span className="eyebrow">CENTRAL DE OPERAÇÃO</span><h1>Um cockpit para todo o seu log.</h1><p>Compare as plataformas online com o log local do Ham Radio Deluxe, pesquise e execute ações seguras sem alternar entre sistemas.</p></div><Button onClick={syncAll} disabled={busy||connected===0}>{busy?'Atualizando…':'Atualizar tudo'}</Button></div>
    {msg&&<Notice tone={msg.startsWith('Erro')||msg.includes('erro(s)')?'error':'info'}>{msg}</Notice>}
    <div className="journey-grid">
      <button onClick={()=>navigate('manager')}><span>01</span><b>Abrir QSO Manager</b><small>{fmt(summary.logical_qsos)} QSOs lógicos</small></button>
      <button onClick={()=>navigate('review')}><span>02</span><b>Revisar inconsistências</b><small>{fmt(summary.qrz_missing)} fora do QRZ</small></button>
      <button onClick={()=>navigate('sources')}><span>03</span><b>Atualizar fontes</b><small>{connected}/{remoteProviders.length} online</small></button>
      <button onClick={()=>navigate('manual')}><span>04</span><b>Comparar ADI</b><small>auditoria manual</small></button>
    </div>
    <div className="metric-grid"><div className="metric"><span>QSOs lógicos</span><strong>{fmt(summary.logical_qsos)}</strong><small>visão consolidada</small></div><div className="metric metric-warn"><span>Fora do QRZ</span><strong>{fmt(summary.qrz_missing)}</strong><small>revisar antes de agir</small></div><div className="metric"><span>Multifonte</span><strong>{fmt(summary.multi_source)}</strong><small>presentes em 2+ fontes</small></div><div className="metric"><span>Com diferenças</span><strong>{fmt(summary.with_differences)}</strong><small>campos divergentes</small></div><div className="metric"><span>Duplicidades</span><strong>{fmt(summary.duplicates)}</strong><small>prováveis</small></div></div>
    <Panel title="Saúde das fontes" subtitle="Conexão, snapshot local e progresso de atualização."><div className="source-grid">{providers.map(p=><SourceCard key={p.provider} p={p} job={jobs[p.provider]} onConfigure={onConfigure} onData={onData} onSync={syncOne}/>)}</div></Panel>
    {analysis?.ignored_sources?.length>0&&<Notice tone="warn">Fonte ignorada temporariamente na reconciliação: {analysis.ignored_sources.join(', ')}.</Notice>}
  </>
}

function ColumnPicker({ columns, setColumns, available, onClose }) {
  return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div className="modal compact-modal">
    <div className="modal-title"><div><span className="eyebrow">COLUNAS</span><h2>Personalizar tabela</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <p className="muted">Escolha os dados que quer enxergar no QSO Manager. A preferência fica salva neste navegador.</p>
    <div className="column-picker">{available.map(key=><label key={key}><input type="checkbox" checked={columns.includes(key)} onChange={e=>{const next=e.target.checked?[...columns,key]:columns.filter(x=>x!==key);setColumns(next)}}/><span>{COLUMN_LABELS[key]||key}</span></label>)}</div>
    <div className="modal-actions"><Button kind="secondary" onClick={()=>setColumns(DEFAULT_COLUMNS)}>Restaurar padrão</Button><Button onClick={onClose}>Concluir</Button></div>
  </div></div>
}

function BulkModal({ selectedIds, status, preset, onClose, onDone }) {
  const [action,setAction] = useState(preset?.action || 'PUBLISH')
  const [target,setTarget] = useState(preset?.target || 'WRL')
  const [source,setSource] = useState(preset?.source || 'WRL')
  const [deleteSource,setDeleteSource] = useState(Boolean(preset?.delete_source))
  const [changes,setChanges] = useState(preset?.changes || {})
  const [plan,setPlan] = useState(null)
  const [job,setJob] = useState(null)
  const [msg,setMsg] = useState('')
  const [busy,setBusy] = useState(false)
  const providers = status?.providers || []
  const byName = Object.fromEntries(providers.map(p=>[p.provider,p]))
  const addTargets = providers.filter(p=>p.configured&&p.capabilities?.add)
  const updateTargets = providers.filter(p=>p.configured&&p.capabilities?.update)
  const deleteTargets = providers.filter(p=>p.configured&&p.capabilities?.delete)
  const moveSources = providers.filter(p=>p.configured)
  const moveTargets = addTargets
  const editable = ['FREQ','BAND','MODE','RST_SENT','RST_RCVD','GRIDSQUARE','STATE','COMMENT','NAME','QTH']

  function requestBody(){return{action,logical_ids:selectedIds,target:target||null,source:source||null,delete_source:deleteSource,changes:Object.fromEntries(Object.entries(changes).filter(([,v])=>v!==''&&v!=null))}}
  async function preview(){setBusy(true);setMsg('');setPlan(null);try{const p=await api('/api/qso-manager/bulk/preview',{method:'POST',body:JSON.stringify(requestBody())});setPlan(p)}catch(e){setMsg(`Erro: ${e.message}`)}finally{setBusy(false)}}
  async function execute(){if(!plan)return;if(!window.confirm(`Executar ${plan.action} em ${fmt(plan.actionable)} QSO(s)?\n\nAções remotas usarão as regras de segurança de cada plataforma.`))return;setBusy(true);setMsg('');try{const started=await api('/api/qso-manager/bulk/jobs',{method:'POST',body:JSON.stringify(requestBody())});setJob(started);const done=await pollBulk(started.job_id,setJob);setMsg(`${done.succeeded} concluído(s), ${done.failed} erro(s).`);await onDone()}catch(e){setMsg(`Erro: ${e.message}`)}finally{setBusy(false)}}

  useEffect(()=>{setPlan(null)},[action,target,source,deleteSource,changes])
  return <div className="modal-backdrop"><div className="modal bulk-modal">
    <div className="modal-title"><div><span className="eyebrow">AÇÃO EM LOTE</span><h2>{fmt(selectedIds.length)} QSO(s) selecionado(s)</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
    <div className="bulk-action-tabs">{[['PUBLISH','Enviar'],['UPDATE','Editar'],['DELETE','Excluir'],['MOVE','Mover']].map(([k,l])=><button key={k} className={action===k?'active':''} onClick={()=>setAction(k)}>{l}</button>)}</div>
    {action==='PUBLISH'&&<div className="fields single"><label><span>Enviar para</span><select value={target} onChange={e=>setTarget(e.target.value)}>{addTargets.map(p=><option key={p.provider} value={p.provider}>{p.label}</option>)}</select><small>QSOs já existentes no destino são ignorados.</small></label></div>}
    {action==='UPDATE'&&<><div className="fields single"><label><span>Editar na plataforma</span><select value={target} onChange={e=>setTarget(e.target.value)}>{updateTargets.map(p=><option key={p.provider} value={p.provider}>{p.label}</option>)}</select><small>Hoje a edição remota segura está disponível onde a API oferece UPDATE estável — atualmente WRL.</small></label></div><div className="bulk-fields">{editable.map(field=><label key={field}><span>{field}</span><input value={changes[field]||''} onChange={e=>setChanges({...changes,[field]:e.target.value})} placeholder="deixar vazio = não alterar"/></label>)}</div></>}
    {action==='DELETE'&&<div className="fields single"><label><span>Excluir da plataforma</span><select value={target} onChange={e=>setTarget(e.target.value)}>{deleteTargets.map(p=><option key={p.provider} value={p.provider}>{p.label}</option>)}</select><small>QRZ e eQSL não aparecem porque DELETE remoto permanece bloqueado.</small></label></div>}
    {action==='MOVE'&&<><div className="fields"><label><span>Origem</span><select value={source} onChange={e=>setSource(e.target.value)}>{moveSources.map(p=><option key={p.provider} value={p.provider}>{p.label}</option>)}</select></label><label><span>Destino</span><select value={target} onChange={e=>setTarget(e.target.value)}>{moveTargets.map(p=><option key={p.provider} value={p.provider}>{p.label}</option>)}</select></label></div><label className="toggle-line"><input type="checkbox" checked={deleteSource} onChange={e=>setDeleteSource(e.target.checked)}/><span>Excluir da origem depois de copiar com sucesso</span></label>{deleteSource&&!byName[source]?.capabilities?.delete&&<Notice tone="warn">{source} não oferece exclusão remota segura; desative a exclusão da origem ou escolha WRL/Club Log.</Notice>}</>}
    {plan&&<div className="plan-card"><div><span>Selecionados</span><b>{fmt(plan.selected)}</b></div><div><span>Executáveis</span><b>{fmt(plan.actionable)}</b></div><div><span>Ignorados</span><b>{fmt(plan.skipped)}</b></div><div><span>Não suportados</span><b>{fmt(plan.unsupported)}</b></div></div>}
    {job&&<Progress job={job}/>} {msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}
    <div className="modal-actions"><Button kind="secondary" onClick={onClose}>Fechar</Button><div className="button-row"><Button kind="secondary" disabled={busy} onClick={preview}>{busy&&!job?'Analisando…':'Pré-visualizar'}</Button><Button disabled={busy||!plan||plan.actionable===0} onClick={execute}>{busy&&job?'Executando…':'Executar ação'}</Button></div></div>
  </div></div>
}

function QsoDetail({ logicalId, status, onClose, onBulk }) {
  const [data,setData]=useState(null),[error,setError]=useState('')
  useEffect(()=>{let alive=true;api(`/api/qso-manager/rows/${logicalId}`).then(x=>{if(alive)setData(x)}).catch(e=>setError(e.message));return()=>{alive=false}},[logicalId])
  if(!logicalId)return null
  const providers=status?.providers||[]
  const byName=Object.fromEntries(providers.map(p=>[p.provider,p]))
  return <div className="drawer-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><aside className="qso-drawer">
    <div className="drawer-head"><div><span className="eyebrow">DETALHE DO QSO</span><h2>{data?data.call:'Carregando…'}</h2>{data&&<p>{data.date} {data.time} · {data.band} · {data.mode}</p>}</div><button className="icon-button" onClick={onClose}>×</button></div>
    {error&&<Notice tone="error">{error}</Notice>}
    {data&&<><div className="drawer-summary"><div><span>Fontes</span><strong>{data.providers.map(p=><Pill key={p} tone={p==='QRZ'?'truth':'ok'}>{p}</Pill>)}</strong></div><div><span>Ausente em</span><strong>{data.missing_in.length?data.missing_in.join(', '):'Nenhuma fonte carregada'}</strong></div><div><span>Diferenças</span><strong>{data.difference_fields.length?data.difference_fields.join(', '):'Nenhuma relevante'}</strong></div></div>
      <div className="drawer-actions"><Button small onClick={()=>onBulk({action:'PUBLISH',target:data.missing_in?.[0]||'WRL'},[data.logical_id])} disabled={!data.missing_in?.length}>Enviar para fonte ausente</Button>{data.providers.filter(p=>byName[p]?.capabilities?.update).map(p=><Button key={`u-${p}`} small kind="secondary" onClick={()=>onBulk({action:'UPDATE',target:p},[data.logical_id])}>Editar no {p}</Button>)}{data.providers.filter(p=>byName[p]?.capabilities?.delete).map(p=><Button key={`d-${p}`} small kind="danger" onClick={()=>onBulk({action:'DELETE',target:p},[data.logical_id])}>Excluir do {p}</Button>)}</div>
      <div className="source-record-stack">{Object.entries(data.source_records||{}).map(([provider,payload])=><section key={provider} className="source-record"><div className="source-record-head"><div><Pill tone={provider==='QRZ'?'truth':'neutral'}>{provider}</Pill><b>{payload.external_id||'sem ID remoto exposto'}</b></div><span>{Object.keys(payload.record||{}).length} campos</span></div><div className="record-grid">{Object.entries(payload.record||{}).sort(([a],[b])=>a.localeCompare(b)).map(([key,value])=><div key={key}><span>{key}</span><code>{String(value)}</code></div>)}</div></section>)}</div>
    </>}
  </aside></div>
}

function QSOManagerPage({ status, workspace, refresh }) {
  const [options,setOptions]=useState(workspace||null)
  const [data,setData]=useState({items:[],total:0,page:1,pages:1,page_size:100})
  const [filters,setFilters]=useState({q:'',call:'',band:'',mode:'',country:'',date_from:'',date_to:'',provider:'',missing_in:'',qrz:'',duplicate:'',differences:'',confirmed:''})
  const [advanced,setAdvanced]=useState(false)
  const [page,setPage]=useState(1),[pageSize,setPageSize]=useState(100),[sort,setSort]=useState('date'),[direction,setDirection]=useState('desc')
  const [selected,setSelected]=useState(new Set())
  const [loading,setLoading]=useState(false),[msg,setMsg]=useState('')
  const [columns,setColumnsState]=useState(()=>{try{return JSON.parse(localStorage.getItem('qso-manager-columns-v6'))||DEFAULT_COLUMNS}catch{return DEFAULT_COLUMNS}})
  const [columnPicker,setColumnPicker]=useState(false),[detail,setDetail]=useState(null),[bulk,setBulk]=useState(null)

  function setColumns(next){setColumnsState(next);localStorage.setItem('qso-manager-columns-v6',JSON.stringify(next))}
  function queryString(extra={}){const params=new URLSearchParams();Object.entries({...filters,...extra}).forEach(([k,v])=>{if(v!==''&&v!=null)params.set(k,v)});return params.toString()}
  async function load(){setLoading(true);setMsg('');try{const result=await api(`/api/qso-manager/rows?${queryString({page,page_size:pageSize,sort,direction})}`);setData(result)}catch(e){setMsg(`Erro: ${e.message}`)}finally{setLoading(false)}}
  async function loadOptions(){try{const result=await api('/api/qso-manager/options');setOptions(result)}catch(e){setMsg(`Erro: ${e.message}`)}}
  useEffect(()=>{const t=setTimeout(()=>{load()},180);return()=>clearTimeout(t)},[filters,page,pageSize,sort,direction])
  useEffect(()=>{loadOptions()},[])
  useEffect(()=>{setPage(1)},[filters])

  function toggle(id){setSelected(prev=>{const next=new Set(prev);next.has(id)?next.delete(id):next.add(id);return next})}
  const pageIds=data.items.map(x=>x.logical_id)
  const allPageSelected=pageIds.length>0&&pageIds.every(id=>selected.has(id))
  function togglePage(){setSelected(prev=>{const next=new Set(prev);if(allPageSelected)pageIds.forEach(id=>next.delete(id));else pageIds.forEach(id=>next.add(id));return next})}
  async function selectAllFiltered(){setLoading(true);try{const result=await api(`/api/qso-manager/ids?${queryString({limit:50000})}`);setSelected(new Set(result.ids||[]));setMsg(result.truncated?`Selecionados os primeiros ${fmt(result.ids.length)} de ${fmt(result.total)} resultados.`:`${fmt(result.total)} resultados selecionados.`)}catch(e){setMsg(`Erro: ${e.message}`)}finally{setLoading(false)}}
  async function exportSelected(){if(!selected.size)return;setLoading(true);setMsg('');try{const response=await fetch('/api/qso-manager/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({logical_ids:[...selected]})});if(!response.ok){const p=await response.json();throw new Error(p.detail||'Falha no export')};const blob=await response.blob();const disposition=response.headers.get('Content-Disposition')||'';const match=disposition.match(/filename="?([^";]+)"?/);const name=match?.[1]||'qso-manager-export.adi';const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);setMsg(`${fmt(selected.size)} QSO(s) exportados para ADIF.`)}catch(e){setMsg(`Erro: ${e.message}`)}finally{setLoading(false)}}
  async function bulkDone(){await refresh();await loadOptions();await load();setSelected(new Set())}
  function openBulk(preset,ids=[...selected]){setBulk({preset,ids})}
  function changeSort(key){if(sort===key)setDirection(direction==='asc'?'desc':'asc');else{setSort(key);setDirection(key==='call'?'asc':'desc')}}
  function th(key,label){return <button className="sort-head" onClick={()=>changeSort(key)}>{label}{sort===key?<span>{direction==='asc'?'↑':'↓'}</span>:null}</button>}
  function hasCol(key){return columns.includes(key)}
  function resetFilters(){setFilters({q:'',call:'',band:'',mode:'',country:'',date_from:'',date_to:'',provider:'',missing_in:'',qrz:'',duplicate:'',differences:'',confirmed:''})}

  return <>
    <div className="page-hero manager-hero"><div><span className="eyebrow">QSO MANAGER · VISÃO CONSOLIDADA</span><h1>Todos os contatos. Uma única fila de trabalho.</h1><p>Uma linha representa um QSO lógico; as badges mostram em quais plataformas ele existe. Selecione, filtre, exporte, sincronize, edite ou exclua em lote conforme a capacidade segura de cada API.</p></div><div className="button-row"><Button kind="secondary" onClick={()=>setColumnPicker(true)}>Colunas</Button><Button onClick={selectAllFiltered} disabled={loading||data.total===0}>Selecionar todos {fmt(data.total)}</Button></div></div>
    {msg&&<Notice tone={msg.startsWith('Erro')?'error':'info'}>{msg}</Notice>}
    <div className="manager-kpis"><div><span>Resultados</span><b>{fmt(data.total)}</b></div><div><span>Selecionados</span><b>{fmt(selected.size)}</b></div><div><span>Fora do QRZ</span><b>{fmt(options?.summary?.qrz_missing)}</b></div><div><span>Com diferenças</span><b>{fmt(options?.summary?.with_differences)}</b></div><div><span>Confirmados</span><b>{fmt(options?.summary?.confirmed)}</b></div></div>
    <section className="manager-toolbar">
      <div className="manager-search"><span>⌕</span><input value={filters.q} onChange={e=>setFilters({...filters,q:e.target.value.toUpperCase()})} placeholder="Indicativo, nome, QTH, país, grid, comentário…"/><button onClick={()=>setAdvanced(!advanced)}>{advanced?'Menos filtros':'Filtros avançados'}</button><button onClick={resetFilters}>Limpar</button></div>
      {advanced&&<div className="advanced-filters">
        <label><span>Indicativo</span><input value={filters.call} onChange={e=>setFilters({...filters,call:e.target.value.toUpperCase()})}/></label>
        <label><span>Banda</span><select value={filters.band} onChange={e=>setFilters({...filters,band:e.target.value})}><option value="">Todas</option>{(options?.bands||[]).map(x=><option key={x}>{x}</option>)}</select></label>
        <label><span>Modo</span><select value={filters.mode} onChange={e=>setFilters({...filters,mode:e.target.value})}><option value="">Todos</option>{(options?.modes||[]).map(x=><option key={x}>{x}</option>)}</select></label>
        <label><span>País</span><select value={filters.country} onChange={e=>setFilters({...filters,country:e.target.value})}><option value="">Todos</option>{(options?.countries||[]).map(x=><option key={x}>{x}</option>)}</select></label>
        <label><span>Presente em</span><select value={filters.provider} onChange={e=>setFilters({...filters,provider:e.target.value})}><option value="">Qualquer fonte</option>{(options?.providers||[]).map(x=><option key={x}>{x}</option>)}</select></label>
        <label><span>Ausente em</span><select value={filters.missing_in} onChange={e=>setFilters({...filters,missing_in:e.target.value})}><option value="">Qualquer</option>{(options?.available_providers||[]).map(x=><option key={x}>{x}</option>)}</select></label>
        <label><span>QRZ</span><select value={filters.qrz} onChange={e=>setFilters({...filters,qrz:e.target.value})}><option value="">Todos</option><option value="present">Presente</option><option value="missing">Ausente</option></select></label>
        <label><span>Duplicidade</span><select value={filters.duplicate} onChange={e=>setFilters({...filters,duplicate:e.target.value})}><option value="">Todos</option><option value="true">Somente prováveis</option><option value="false">Sem duplicidade</option></select></label>
        <label><span>Diferenças</span><select value={filters.differences} onChange={e=>setFilters({...filters,differences:e.target.value})}><option value="">Todos</option><option value="true">Com divergências</option><option value="false">Sem divergências</option></select></label>
        <label><span>Confirmação</span><select value={filters.confirmed} onChange={e=>setFilters({...filters,confirmed:e.target.value})}><option value="">Todos</option><option value="true">Confirmado</option><option value="false">Sem confirmação detectada</option></select></label>
        <label><span>De</span><input type="date" value={filters.date_from} onChange={e=>setFilters({...filters,date_from:e.target.value})}/></label>
        <label><span>Até</span><input type="date" value={filters.date_to} onChange={e=>setFilters({...filters,date_to:e.target.value})}/></label>
      </div>}
    </section>
    {selected.size>0&&<div className="selection-bar"><div><b>{fmt(selected.size)} selecionado(s)</b><span>As ações respeitam as capacidades de cada plataforma.</span></div><div className="button-row"><Button small kind="secondary" onClick={exportSelected}>Exportar ADIF</Button><Button small onClick={()=>openBulk({action:'PUBLISH',target:'WRL'})}>Enviar para…</Button><Button small kind="secondary" onClick={()=>openBulk({action:'UPDATE',target:'WRL'})}>Editar em massa</Button><Button small kind="secondary" onClick={()=>openBulk({action:'MOVE',source:'WRL',target:'QRZ'})}>Mover</Button><Button small kind="danger" onClick={()=>openBulk({action:'DELETE',target:'WRL'})}>Excluir de…</Button><button className="selection-clear" onClick={()=>setSelected(new Set())}>Limpar seleção</button></div></div>}
    <div className="manager-table-wrap"><table className="manager-table"><thead><tr><th className="check-cell"><input type="checkbox" checked={allPageSelected} onChange={togglePage}/></th>{hasCol('date')&&<th>{th('date','Data / hora')}</th>}{hasCol('call')&&<th>{th('call','Indicativo')}</th>}{hasCol('band')&&<th>{th('band','Banda')}</th>}{hasCol('mode')&&<th>{th('mode','Modo')}</th>}{hasCol('freq')&&<th>Freq.</th>}{hasCol('country')&&<th>{th('country','País')}</th>}{hasCol('state')&&<th>Estado</th>}{hasCol('county')&&<th>County</th>}{hasCol('grid')&&<th>Grid</th>}{hasCol('name')&&<th>Nome</th>}{hasCol('qth')&&<th>QTH</th>}{hasCol('rst')&&<th>RST</th>}{hasCol('comment')&&<th>Comentário</th>}{hasCol('qsl')&&<th>QSL</th>}{hasCol('sources')&&<th>{th('sources','Fontes')}</th>}{hasCol('missing')&&<th>Ausente em</th>}{hasCol('differences')&&<th>{th('differences','Diferenças')}</th>}{hasCol('duplicate')&&<th>Dup.</th>}{hasCol('status')&&<th>Status</th>}<th></th></tr></thead><tbody>{loading&&!data.items.length?<tr><td colSpan="20"><div className="table-loading">Carregando QSOs…</div></td></tr>:data.items.map(row=><tr key={row.logical_id} className={selected.has(row.logical_id)?'selected-row':''}><td className="check-cell"><input type="checkbox" checked={selected.has(row.logical_id)} onChange={()=>toggle(row.logical_id)}/></td>{hasCol('date')&&<td><b>{row.date||'—'}</b><small>{row.time||'—'}</small></td>}{hasCol('call')&&<td><button className="call-link" onClick={()=>setDetail(row.logical_id)}>{row.call}</button></td>}{hasCol('band')&&<td>{row.band||'—'}</td>}{hasCol('mode')&&<td>{row.mode||'—'}</td>}{hasCol('freq')&&<td>{row.freq||'—'}</td>}{hasCol('country')&&<td>{row.country||'—'}</td>}{hasCol('state')&&<td>{row.state||'—'}</td>}{hasCol('county')&&<td>{row.county||'—'}</td>}{hasCol('grid')&&<td>{row.grid||'—'}</td>}{hasCol('name')&&<td>{row.name||'—'}</td>}{hasCol('qth')&&<td>{row.qth||'—'}</td>}{hasCol('rst')&&<td>{row.rst_sent||'—'} / {row.rst_rcvd||'—'}</td>}{hasCol('comment')&&<td className="truncate-cell" title={row.comment||''}>{row.comment||'—'}</td>}{hasCol('qsl')&&<td>{row.confirmed?<Pill tone="ok">confirmado</Pill>:<span className="muted">—</span>}</td>}{hasCol('sources')&&<td><div className="source-pills">{row.providers.map(p=><Pill key={p} tone={p==='QRZ'?'truth':'ok'}>{p}</Pill>)}</div></td>}{hasCol('missing')&&<td>{row.missing_in.length?<div className="source-pills">{row.missing_in.map(p=><Pill key={p} tone="warn">{p}</Pill>)}</div>:<span className="muted">—</span>}</td>}{hasCol('differences')&&<td>{row.difference_count?<Pill tone="warn">{row.difference_count}</Pill>:<span className="muted">—</span>}</td>}{hasCol('duplicate')&&<td>{row.duplicate?<Pill tone="warn">provável</Pill>:<span className="muted">—</span>}</td>}{hasCol('status')&&<td>{!row.providers.includes('QRZ')?<Pill tone="warn">QRZ ausente</Pill>:row.missing_in.length?<Pill>incompleto</Pill>:<Pill tone="ok">alinhado</Pill>}</td>}<td><button className="row-menu" onClick={()=>setDetail(row.logical_id)}>•••</button></td></tr>)}</tbody></table>{!loading&&data.items.length===0&&<Empty>Nenhum QSO corresponde aos filtros.</Empty>}</div>
    <div className="pagination"><div><span>Linhas por página</span><select value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1)}}>{[25,50,100,250,500].map(n=><option key={n}>{n}</option>)}</select></div><div><Button small kind="secondary" disabled={page<=1} onClick={()=>setPage(page-1)}>Anterior</Button><span>Página <b>{data.page}</b> de <b>{data.pages}</b></span><Button small kind="secondary" disabled={page>=data.pages} onClick={()=>setPage(page+1)}>Próxima</Button></div></div>
    {columnPicker&&<ColumnPicker columns={columns} setColumns={setColumns} available={options?.columns||Object.keys(COLUMN_LABELS)} onClose={()=>setColumnPicker(false)}/>} {detail&&<QsoDetail logicalId={detail} status={status} onClose={()=>setDetail(null)} onBulk={(preset,ids)=>{setDetail(null);openBulk(preset,ids)}}/>} {bulk&&<BulkModal selectedIds={bulk.ids} status={status} preset={bulk.preset} onClose={()=>setBulk(null)} onDone={bulkDone}/>} 
  </>
}

function Review({ status, analysis, navigateManager }) {
  const [tab,setTab]=useState('qrz'),[target,setTarget]=useState('ALL'),[field,setField]=useState('ALL'),[provider,setProvider]=useState('ALL')
  if(!analysis?.ready)return <Panel title="Revisar"><Empty>Sincronize o QRZ e ao menos uma segunda fonte.</Empty></Panel>
  const missing=(analysis.missing_elsewhere||[]).filter(x=>target==='ALL'||x.target===target)
  const fields=(analysis.field_differences||[]).filter(x=>(field==='ALL'||x.field===field)&&(provider==='ALL'||x.provider===provider))
  const fieldNames=[...new Set((analysis.field_differences||[]).map(x=>x.field))].sort()
  const tabs=[['qrz',`QRZ pode estar atrasado (${fmt(analysis.qrz_stale_candidates?.length)})`],['targets',`Faltando nas plataformas (${fmt(analysis.missing_elsewhere?.length)})`],['fields',`Campos (${fmt(analysis.field_differences?.length)})`],['dupes',`Duplicidades (${fmt(analysis.probable_duplicates?.length)})`]]
  return <><div className="page-hero compact"><div><span className="eyebrow">RECONCILIAÇÃO MULTIFONTE</span><h1>Revisar antes de alterar.</h1><p>Esta visão explica por que um QSO merece atenção. A manipulação em lote acontece no QSO Manager, onde você pode filtrar e selecionar os registros envolvidos.</p></div><Button onClick={()=>navigateManager({})}>Abrir QSO Manager</Button></div><div className="tabs">{tabs.map(([k,l])=><button key={k} className={tab===k?'active':''} onClick={()=>setTab(k)}>{l}</button>)}</div>
    {tab==='qrz'&&<Panel title="Ausentes no QRZ" subtitle="Evidência não é decisão automática.">{!(analysis.qrz_stale_candidates||[]).length?<Empty/>:<div className="case-list">{analysis.qrz_stale_candidates.map((q,i)=><div className="case-row" key={i}><div><b>{qsoTitle(q)}</b><p>{q.reason}</p><div className="evidence">{(q.sources||[]).map(s=><Pill key={s} tone="ok">{s}</Pill>)}</div></div><Button small onClick={()=>navigateManager({q:q.call,qrz:'missing'})}>Abrir no Manager</Button></div>)}</div>}</Panel>}
    {tab==='targets'&&<><div className="filter-bar"><label><span>Plataforma</span><select value={target} onChange={e=>setTarget(e.target.value)}><option value="ALL">Todas</option>{(status?.providers||[]).filter(p=>p.provider!=='QRZ').map(p=><option key={p.provider}>{p.provider}</option>)}</select></label><Pill>{fmt(missing.length)} itens</Pill></div><Panel title="Presentes no QRZ e ausentes em outras bases">{!missing.length?<Empty/>:<div className="case-list">{missing.slice(0,500).map((q,i)=><div className="case-row" key={i}><div><b>{qsoTitle(q)}</b><p>{q.reason}</p></div><Button small onClick={()=>navigateManager({q:q.call,missing_in:q.target})}>Abrir no Manager</Button></div>)}</div>}</Panel></>}
    {tab==='fields'&&<><div className="filter-bar"><label><span>Campo</span><select value={field} onChange={e=>setField(e.target.value)}><option value="ALL">Todos</option>{fieldNames.map(x=><option key={x}>{x}</option>)}</select></label><label><span>Fonte</span><select value={provider} onChange={e=>setProvider(e.target.value)}><option value="ALL">Todas</option>{(status?.providers||[]).filter(p=>p.provider!=='QRZ').map(p=><option key={p.provider}>{p.provider}</option>)}</select></label><Pill>{fmt(fields.length)} divergências</Pill></div><Panel title="Campos divergentes">{!fields.length?<Empty/>:<div className="table-wrap"><table><thead><tr><th>QSO</th><th>Campo</th><th>QRZ</th><th>Outra base</th><th>Fonte</th></tr></thead><tbody>{fields.slice(0,1000).map((d,i)=><tr key={i}><td><b>{d.call}</b><small>{d.date} {d.time} · {d.band}</small></td><td>{d.field}</td><td className="preferred">{String(d.value_a??'∅')}</td><td>{String(d.value_b??'∅')}</td><td><Pill>{d.provider}</Pill></td></tr>)}</tbody></table></div>}</Panel></>}
    {tab==='dupes'&&<Panel title="Duplicidades prováveis">{!(analysis.probable_duplicates||[]).length?<Empty/>:<div className="case-list">{analysis.probable_duplicates.map((d,i)=><div className="case-row" key={i}><div><b>{d.call} · {d.date} · {d.band} · {d.mode}</b><p>{d.reason}</p></div><Button small onClick={()=>navigateManager({q:d.call,duplicate:'true',provider:d.source})}>Abrir no Manager</Button></div>)}</div>}</Panel>}
  </>
}

function ManualCompare(){const[a,setA]=useState(null),[b,setB]=useState(null),[result,setResult]=useState(null),[msg,setMsg]=useState(''),[busy,setBusy]=useState(false);async function compare(){if(!a||!b)return setMsg('Selecione os dois arquivos ADIF.');setBusy(true);try{const[ca,cb]=await Promise.all([a.text(),b.text()]);setResult(await api('/api/comparisons/adif',{method:'POST',body:JSON.stringify({a:{content:ca,source:'LOG_A',filename:a.name,coverage:'FULL_EXPORT'},b:{content:cb,source:'LOG_B',filename:b.name,coverage:'FULL_EXPORT'}})}))}catch(e){setMsg(`Erro: ${e.message}`)}finally{setBusy(false)}}return <><div className="page-hero compact"><div><span className="eyebrow">COMPARAÇÃO MANUAL</span><h1>Compare dois ADIs quando precisar.</h1><p>Auditoria pontual para qualquer fonte, mesmo sem API.</p></div></div><div className="two-col"><Panel title="Log A"><input type="file" accept=".adi,.adif,.txt" onChange={e=>setA(e.target.files?.[0])}/><p className="muted">{a?.name||'Nenhum arquivo'}</p></Panel><Panel title="Log B"><input type="file" accept=".adi,.adif,.txt" onChange={e=>setB(e.target.files?.[0])}/><p className="muted">{b?.name||'Nenhum arquivo'}</p></Panel></div><div className="center-action"><Button disabled={busy} onClick={compare}>{busy?'Comparando…':'Comparar ADIs'}</Button></div>{msg&&<Notice tone="error">{msg}</Notice>}{result&&<div className="metric-grid four"><div className="metric"><span>Pareados</span><strong>{fmt(result.summary?.matched)}</strong></div><div className="metric"><span>Presença</span><strong>{fmt((result.missing_in_a||[]).length+(result.missing_in_b||[]).length)}</strong></div><div className="metric"><span>Campos</span><strong>{fmt(result.summary?.field_differences)}</strong></div><div className="metric"><span>Duplicidades</span><strong>{fmt(result.summary?.probable_duplicates)}</strong></div></div>}</>}

function Sources({ status, refresh, onConfigure, onData }) {
  const[jobs,setJobs]=useState({}),[msg,setMsg]=useState('')
  async function sync(p){try{const j=await runSync(p,x=>setJobs(v=>({...v,[p]:x})));setMsg(`${p}: ${fmt(j.records)} QSOs carregados.`);await refresh()}catch(e){setMsg(`Erro: ${e.message}`)}}
  return <><div className="page-hero compact"><div><span className="eyebrow">FONTES & DADOS</span><h1>Fontes online e logs locais na mesma análise.</h1><p>Conecte os serviços online e importe o export ADIF completo do Ham Radio Deluxe para compará-lo continuamente com os demais snapshots.</p></div></div>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}<div className="journey-strip"><div><b>1. Conectar ou importar</b><span>API ou ADIF</span></div><i>→</i><div><b>2. Atualizar</b><span>Reconstruir snapshot</span></div><i>→</i><div><b>3. Comparar</b><span>QSO Manager</span></div></div><div className="source-grid">{(status?.providers||[]).map(p=><SourceCard key={p.provider} p={p} job={jobs[p.provider]} onConfigure={onConfigure} onData={onData} onSync={sync}/>)}</div></>
}

function ActivityPage(){const[rows,setRows]=useState([]),[loading,setLoading]=useState(true),[kind,setKind]=useState('');async function load(){setLoading(true);try{setRows(await api(`/api/qso-manager/activity?limit=500${kind?`&kind=${encodeURIComponent(kind)}`:''}`))}finally{setLoading(false)}}useEffect(()=>{load()},[kind]);const kinds=[...new Set(rows.map(x=>x.kind))];return <><div className="page-hero compact"><div><span className="eyebrow">HISTÓRICO DE AÇÕES</span><h1>Saiba o que foi feito e quando.</h1><p>Exports e operações em lote ficam registrados localmente para auditoria do fluxo.</p></div><Button kind="secondary" onClick={load}>Atualizar</Button></div><div className="filter-bar"><label><span>Tipo</span><select value={kind} onChange={e=>setKind(e.target.value)}><option value="">Todos</option>{kinds.map(x=><option key={x}>{x}</option>)}</select></label><Pill>{fmt(rows.length)} eventos</Pill></div><Panel title="Atividade recente">{loading?<div className="loading">Carregando…</div>:!rows.length?<Empty>Nenhuma ação registrada ainda.</Empty>:<div className="activity-list">{rows.map(x=><article key={x.id}><div><Pill tone={x.status==='ERROR'?'warn':x.status==='PARTIAL'?'warn':'ok'}>{x.kind}</Pill><b>{x.summary}</b><small>{dateFmt(x.timestamp)}</small></div><code>{x.details?.job_id||x.details?.filename||''}</code></article>)}</div>}</Panel></>}

function Security(){return <><div className="page-hero compact"><div><span className="eyebrow">SEGURANÇA OPERACIONAL</span><h1>Funcionalidade ampla, escrita controlada.</h1><p>O QSO Manager expõe ações equivalentes em uma única experiência, mas não finge que todas as APIs têm as mesmas capacidades.</p></div></div><div className="security-grid"><Panel title="QRZ"><p>Leitura e inclusão. UPDATE/DELETE/REPLACE permanecem bloqueados para evitar sobrescritas perigosas.</p></Panel><Panel title="WRL"><p>Leitura, inclusão, edição e exclusão por ID remoto estável.</p></Panel><Panel title="Club Log"><p>Leitura, inclusão e exclusão exata. UPDATE direto não é oferecido.</p></Panel><Panel title="eQSL"><p>Leitura do OutBox e inclusão. Edição/exclusão remota não são expostas.</p></Panel></div><Panel title="Ações em lote"><p>O fluxo sempre passa por seleção → pré-visualização → confirmação → execução em background → re-sincronização das plataformas alteradas. “Apagar dados locais” continua separado de qualquer exclusão remota.</p></Panel></>}

export default function App(){
  const[view,setView]=useState('home'),[status,setStatus]=useState(null),[analysis,setAnalysis]=useState(null),[workspace,setWorkspace]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[configure,setConfigure]=useState(null),[dataModal,setDataModal]=useState(null)
  const[managerSeed,setManagerSeed]=useState(0)
  async function refresh(){setError('');try{const[s,a,w]=await Promise.all([api('/api/cloud/status'),api('/api/cloud/analysis'),api('/api/qso-manager/options')]);setStatus(s);setAnalysis(a);setWorkspace(w);setManagerSeed(x=>x+1)}catch(e){setError(e.message)}finally{setLoading(false)}}
  useEffect(()=>{refresh()},[])
  const pageTitle=useMemo(()=>NAV.find(n=>n[0]===view)?.[1]||'QSO Manager',[view])
  function navigateManager(){setView('manager');setManagerSeed(x=>x+1)}
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark">PU</div><div><b>QSO Manager</b><span>PU2BRU · v6.1</span></div></div><nav>{NAV.map(([k,l,icon])=><button key={k} className={view===k?'active':''} onClick={()=>setView(k)}><span className="nav-icon">{icon}</span><span>{l}</span>{k==='review'&&(analysis?.summary?.qrz_stale_candidates||0)>0&&<em>{analysis.summary.qrz_stale_candidates}</em>}</button>)}</nav><div className="sidebar-bottom"><span className="dot dot-on"/><div><b>Modo local</b><small>dados no seu PC</small></div></div></aside><main><header className="topbar"><div><span className="eyebrow">PU2BRU QSO MANAGER</span><h3>{pageTitle}</h3></div><div className="top-sources">{(status?.providers||[]).map(p=><div className="source-badge" key={p.provider}><span className={cls('dot',p.configured?'dot-on':'dot-off')}/><b>{p.provider}</b><span>{p.snapshot?.downloaded_at?`${fmt(p.snapshot?.records)} QSOs`:p.source_kind==='local_adif'?'aguardando ADIF':p.configured?'sem snapshot':'não conectado'}</span></div>)}</div></header><div className="content">{error&&<Notice tone="error">{error}</Notice>}{loading?<div className="loading">Carregando…</div>:<>{view==='home'&&<Dashboard status={status} analysis={analysis} workspace={workspace} refresh={refresh} navigate={setView} onConfigure={setConfigure} onData={setDataModal}/>} {view==='manager'&&<QSOManagerPage key={managerSeed} status={status} workspace={workspace} refresh={refresh}/>} {view==='review'&&<Review status={status} analysis={analysis} navigateManager={navigateManager}/>} {view==='manual'&&<ManualCompare/>} {view==='sources'&&<Sources status={status} refresh={refresh} onConfigure={setConfigure} onData={setDataModal}/>} {view==='activity'&&<ActivityPage/>} {view==='security'&&<Security/>}</>}</div></main>{configure&&<ConfigureModal provider={configure} onClose={()=>setConfigure(null)} onSaved={refresh}/>} {dataModal&&<LocalDataModal provider={dataModal} onClose={()=>setDataModal(null)} onCleared={async()=>{await refresh();setDataModal(null)}}/>}</div>
}
