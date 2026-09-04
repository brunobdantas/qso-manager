import React, { useEffect, useMemo, useState } from 'react'

const API = ''

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const text = await response.text()
  let payload = null
  if (text) {
    try { payload = JSON.parse(text) } catch { payload = text }
  }
  if (!response.ok) {
    const detail = payload?.detail || payload?.message || payload || `${response.status} ${response.statusText}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return payload
}

function useLoad(path, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const reload = async () => {
    setLoading(true); setError('')
    try { setData(await api(path)) } catch (e) { setError(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { reload() }, deps)
  return { data, loading, error, reload }
}

const nav = [
  ['dashboard', 'Visão geral'],
  ['imports', 'Importar ADIF'],
  ['qsos', 'QSOs reconciliados'],
  ['divergences', 'Divergências'],
  ['backups', 'Backups'],
  ['audit', 'Auditoria'],
  ['system', 'Sistema'],
]

function StatusPill({ value }) {
  const normalized = String(value || 'unknown').toLowerCase()
  return <span className={`pill pill-${normalized.replace(/[^a-z0-9_-]/g, '-')}`}>{value || '—'}</span>
}

function Panel({ title, actions, children }) {
  return <section className="panel">
    <div className="panel-head"><h2>{title}</h2><div>{actions}</div></div>
    {children}
  </section>
}

function Empty({ children = 'Nenhum registro encontrado.' }) {
  return <div className="empty">{children}</div>
}

function Dashboard() {
  const { data: health } = useLoad('/api/health', [])
  const { data: qsos } = useLoad('/api/qsos?limit=100', [])
  const { data: divs } = useLoad('/api/qsos/divergences', [])
  const { data: imports } = useLoad('/api/imports', [])
  const unresolved = (divs || []).filter(d => d.status !== 'resolved').length
  const reviews = (qsos || []).filter(q => q.status === 'needs_review').length
  return <>
    <div className="hero">
      <div><div className="eyebrow">PU2BRU</div><h1>QSO Manager</h1><p>Reconciliação segura de logs, rastreabilidade de decisões e operação local.</p></div>
      <StatusPill value={health?.status || 'loading'} />
    </div>
    <div className="cards">
      <article className="metric"><span>QSOs reconciliados</span><strong>{qsos?.length ?? '—'}</strong></article>
      <article className="metric"><span>Para revisão</span><strong>{reviews}</strong></article>
      <article className="metric"><span>Divergências abertas</span><strong>{unresolved}</strong></article>
      <article className="metric"><span>Importações</span><strong>{imports?.length ?? '—'}</strong></article>
    </div>
    <Panel title="Estado do núcleo">
      <div className="status-grid">
        <div><span>API</span><b>{health?.status || 'verificando'}</b></div>
        <div><span>Banco</span><b>{health?.database || 'verificando'}</b></div>
        <div><span>Ambiente</span><b>{health?.environment || '—'}</b></div>
        <div><span>QRZ real</span><b>{health?.qrz_enabled ? 'configurado' : 'desabilitado'}</b></div>
      </div>
      <p className="hint">O sistema não executa escrita real no QRZ automaticamente. Integrações externas exigem modo explícito e seguro.</p>
    </Panel>
  </>
}

function Imports() {
  const [file, setFile] = useState(null)
  const [source, setSource] = useState('QRZ')
  const [coverage, setCoverage] = useState('PARTIAL_EXPORT')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const { data: history, reload } = useLoad('/api/imports', [])

  async function submit(e) {
    e.preventDefault()
    if (!file) return setMessage('Selecione um arquivo ADIF.')
    setBusy(true); setMessage('')
    try {
      const content = await file.text()
      const result = await api('/api/imports/adif', {
        method: 'POST',
        body: JSON.stringify({
          content,
          source_name: source.trim() || 'MANUAL',
          filename: file.name,
          source_type: 'LOGBOOK',
          coverage_type: coverage,
          reliability_score: 0.5,
        }),
      })
      setMessage(`Importação concluída: ${result.processed_records}/${result.total_records} registros.`)
      await reload()
    } catch (err) { setMessage(`Erro: ${err.message}`) } finally { setBusy(false) }
  }

  async function reconcile() {
    setBusy(true); setMessage('')
    try {
      const result = await api('/api/reconciliation', { method: 'POST', body: '{}' })
      setMessage(`Reconciliação concluída. QSOs lógicos: ${result.total_logical_qsos ?? result.logical_qsos ?? 'ok'}.`)
    } catch (err) { setMessage(`Erro: ${err.message}`) } finally { setBusy(false) }
  }

  return <>
    <Panel title="Importar arquivo ADIF" actions={<button className="secondary" onClick={reconcile} disabled={busy}>Reconciliar agora</button>}>
      <form className="form-grid" onSubmit={submit}>
        <label>Fonte<input value={source} onChange={e => setSource(e.target.value.toUpperCase())} placeholder="QRZ, WRL, MSHV..." /></label>
        <label>Cobertura<select value={coverage} onChange={e => setCoverage(e.target.value)}>
          <option>PARTIAL_EXPORT</option><option>FULL_EXPORT</option><option>FILTERED_EXPORT</option><option>DATE_RANGE</option><option>API_FULL_SYNC</option><option>API_INCREMENTAL</option>
        </select></label>
        <label className="wide">Arquivo<input type="file" accept=".adi,.adif,text/plain" onChange={e => setFile(e.target.files?.[0] || null)} /></label>
        <div className="wide form-actions"><button disabled={busy}>{busy ? 'Processando…' : 'Importar'}</button></div>
      </form>
      {message && <div className="notice">{message}</div>}
      <p className="hint"><b>Regra segura:</b> upload manual inicia como PARTIAL_EXPORT. Ausência em arquivo parcial não prova QSO faltante.</p>
    </Panel>
    <Panel title="Histórico de importações">
      {!history?.length ? <Empty /> : <div className="table-wrap"><table><thead><tr><th>ID</th><th>Fonte</th><th>Cobertura</th><th>Status</th><th>Registros</th><th>Data</th></tr></thead><tbody>
        {history.map(row => <tr key={row.id}><td>{row.id}</td><td>#{row.source_id}</td><td><StatusPill value={row.coverage_type} /></td><td>{row.status}</td><td>{row.processed_records}/{row.total_records}</td><td>{row.started_at ? new Date(row.started_at).toLocaleString() : '—'}</td></tr>)}
      </tbody></table></div>}
    </Panel>
  </>
}

function Qsos() {
  const [filters, setFilters] = useState({ callsign: '', band: '', mode: '' })
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)
  const [edit, setEdit] = useState({ county: '', grid: '', comment: '' })
  const [message, setMessage] = useState('')
  const { data: rows, loading, error, reload } = useLoad(`/api/qsos?limit=500${query}`, [query])

  function search(e) {
    e.preventDefault()
    const p = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => { if (v.trim()) p.set(k, v.trim()) })
    setQuery(p.toString() ? `&${p}` : '')
  }
  function choose(q) {
    setSelected(q)
    setEdit({ county: q.county || '', grid: q.grid || '', comment: q.comment || '' })
    setMessage('')
  }
  async function save(e) {
    e.preventDefault()
    try {
      await api(`/api/qsos/uuid/${selected.uuid}`, {
        method: 'PATCH',
        body: JSON.stringify({ changes: edit, reason: 'Edição manual pela interface local' }),
      })
      setMessage('Alteração persistida como override manual.')
      await reload()
    } catch (err) { setMessage(`Erro: ${err.message}`) }
  }
  return <>
    <Panel title="QSOs reconciliados">
      <form className="filterbar" onSubmit={search}>
        <input placeholder="Indicativo" value={filters.callsign} onChange={e => setFilters({...filters, callsign:e.target.value.toUpperCase()})} />
        <input placeholder="Banda (ex. 20M)" value={filters.band} onChange={e => setFilters({...filters, band:e.target.value.toUpperCase()})} />
        <input placeholder="Modo (FT8/FT4/SSB)" value={filters.mode} onChange={e => setFilters({...filters, mode:e.target.value.toUpperCase()})} />
        <button>Filtrar</button>
      </form>
      {error && <div className="notice error">{error}</div>}
      {loading ? <Empty>Carregando…</Empty> : !rows?.length ? <Empty /> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>UTC</th><th>Call</th><th>Banda</th><th>Modo</th><th>Freq.</th><th>Grid</th><th>Status</th><th></th></tr></thead><tbody>
        {rows.map(q => <tr key={q.uuid}><td>{q.qso_date}</td><td>{q.time_on || '—'}</td><td><b>{q.callsign}</b></td><td>{q.band || '—'}</td><td>{q.operating_mode || q.submode || q.mode || '—'}</td><td>{q.freq_hz ? `${(q.freq_hz/1e6).toFixed(6)} MHz` : '—'}</td><td>{q.grid || '—'}</td><td><StatusPill value={q.status} /></td><td><button className="link" onClick={() => choose(q)}>Editar</button></td></tr>)}
      </tbody></table></div>}
    </Panel>
    {selected && <Panel title={`Editar ${selected.callsign} — ${selected.qso_date} ${selected.time_on || ''}`} actions={<button className="ghost" onClick={() => setSelected(null)}>Fechar</button>}>
      <form className="form-grid" onSubmit={save}>
        <label>County<input value={edit.county} onChange={e => setEdit({...edit, county:e.target.value})} /></label>
        <label>Grid<input value={edit.grid} onChange={e => setEdit({...edit, grid:e.target.value.toUpperCase()})} /></label>
        <label className="wide">Comentário<textarea rows="3" value={edit.comment} onChange={e => setEdit({...edit, comment:e.target.value})} /></label>
        <div className="wide form-actions"><button>Salvar override</button></div>
      </form>
      {message && <div className="notice">{message}</div>}
    </Panel>}
  </>
}

function Divergences() {
  const { data: rows, loading, error, reload } = useLoad('/api/qsos/divergences', [])
  const [values, setValues] = useState({})
  const [message, setMessage] = useState('')
  async function resolve(d) {
    const resolved = values[d.id] ?? d.source_1_value ?? ''
    if (resolved === '') return setMessage('Informe o valor resolvido.')
    try {
      await api(`/api/qsos/divergences/${d.id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ resolved_value: String(resolved), reason: 'Resolução manual pela interface local', status: 'resolved' }),
      })
      setMessage(`Divergência #${d.id} resolvida e persistida.`)
      await reload()
    } catch (err) { setMessage(`Erro: ${err.message}`) }
  }
  return <Panel title="Divergências entre fontes">
    {message && <div className="notice">{message}</div>}{error && <div className="notice error">{error}</div>}
    {loading ? <Empty>Carregando…</Empty> : !rows?.length ? <Empty>Nenhuma divergência.</Empty> : <div className="table-wrap"><table><thead><tr><th>Campo</th><th>Fonte 1</th><th>Fonte 2</th><th>Status</th><th>Resolução</th></tr></thead><tbody>
      {rows.map(d => <tr key={d.id}><td><b>{d.field_name}</b></td><td>{d.source_1_name}: <code>{d.source_1_value ?? '∅'}</code></td><td>{d.source_2_name}: <code>{d.source_2_value ?? '∅'}</code></td><td><StatusPill value={d.status} /></td><td>{d.status === 'resolved' ? <span>{d.resolution || 'resolvido'}</span> : <div className="resolve"><input value={values[d.id] ?? ''} placeholder="valor correto" onChange={e => setValues({...values,[d.id]:e.target.value})}/><button onClick={() => resolve(d)}>Resolver</button></div>}</td></tr>)}
    </tbody></table></div>}
  </Panel>
}

function Backups() {
  const { data: rows, reload } = useLoad('/api/backups', [])
  const [message, setMessage] = useState('')
  async function create(type) {
    try { const r = await api(`/api/backups?backup_type=${type}&description=Backup%20manual`, {method:'POST', body:'{}'}); setMessage(`Backup criado: ${r.file_path}`); await reload() }
    catch (e) { setMessage(`Erro: ${e.message}`) }
  }
  return <Panel title="Backups" actions={<div className="button-row"><button onClick={() => create('full')}>JSON</button><button className="secondary" onClick={() => create('adif')}>ADIF</button></div>}>
    {message && <div className="notice">{message}</div>}
    {!rows?.length ? <Empty /> : <div className="table-wrap"><table><thead><tr><th>Tipo</th><th>Arquivo</th><th>QSOs</th><th>Tamanho</th><th>Criado</th></tr></thead><tbody>{rows.map(b => <tr key={b.id}><td>{b.backup_type}</td><td><code>{b.file_path}</code></td><td>{b.record_count}</td><td>{b.file_size} B</td><td>{b.created_at ? new Date(b.created_at).toLocaleString() : '—'}</td></tr>)}</tbody></table></div>}
  </Panel>
}

function Audit() {
  const { data: rows, loading } = useLoad('/api/audit?limit=200', [])
  return <Panel title="Auditoria append-only">{loading ? <Empty>Carregando…</Empty> : !rows?.length ? <Empty /> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>Operação</th><th>Entidade</th><th>Origem</th><th>Motivo</th><th>Resultado</th></tr></thead><tbody>{rows.map(e => <tr key={e.id}><td>{new Date(e.timestamp).toLocaleString()}</td><td>{e.operation}</td><td>{e.entity_type} #{e.entity_id ?? ''}</td><td>{e.source || '—'}</td><td>{e.reason || '—'}</td><td><StatusPill value={e.result} /></td></tr>)}</tbody></table></div>}</Panel>
}

function System() {
  const { data: health, error, reload } = useLoad('/api/health', [])
  return <>
    <Panel title="Diagnóstico" actions={<button className="secondary" onClick={reload}>Atualizar</button>}>
      {error && <div className="notice error">{error}</div>}
      <pre className="json">{JSON.stringify(health, null, 2)}</pre>
    </Panel>
    <Panel title="Integrações">
      <div className="integration-grid">
        <article><b>QRZ</b><StatusPill value="DRY_RUN" /><p>Escrita real bloqueada por padrão.</p></article>
        <article><b>WRL / UDP</b><StatusPill value="LOCAL_ONLY" /><p>Destino restrito a loopback.</p></article>
        <article><b>ClubLog / eQSL / LoTW</b><StatusPill value="IMPORT" /><p>Importação ADIF disponível; conectores reais pertencem ao Release 3.</p></article>
      </div>
    </Panel>
  </>
}

export default function App() {
  const [page, setPage] = useState('dashboard')
  const title = useMemo(() => nav.find(([key]) => key === page)?.[1] || 'QSO Manager', [page])
  return <div className="app-shell">
    <aside>
      <div className="brand"><span className="brand-mark">PU</span><div><b>PU2BRU</b><small>QSO Manager</small></div></div>
      <nav>{nav.map(([key,label]) => <button key={key} className={page===key?'active':''} onClick={() => setPage(key)}>{label}</button>)}</nav>
      <div className="side-foot">Local-first<br/><small>Release 2</small></div>
    </aside>
    <main>
      <header><div><small>PU2BRU QSO MANAGER</small><h3>{title}</h3></div><a href="/docs" target="_blank" rel="noreferrer">API Docs</a></header>
      <div className="content">
        {page==='dashboard' && <Dashboard/>}
        {page==='imports' && <Imports/>}
        {page==='qsos' && <Qsos/>}
        {page==='divergences' && <Divergences/>}
        {page==='backups' && <Backups/>}
        {page==='audit' && <Audit/>}
        {page==='system' && <System/>}
      </div>
    </main>
  </div>
}
