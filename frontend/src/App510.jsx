import React, { useEffect, useMemo, useState } from 'react'

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
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
  QRZ: [['api_key', 'QRZ Logbook API Key', 'password', 'Chave do logbook em QRZ → Logbook → Settings → API']],
  WRL: [
    ['api_key', 'Developer API Key', 'password', 'Gerada em Integrations → Developer API'],
    ['logbook_id', 'Logbook ID (opcional)', 'text', 'Deixe vazio para usar o logbook padrão da conta'],
  ],
  CLUBLOG: [
    ['email', 'E-mail', 'email', 'Conta do Club Log'],
    ['app_password', 'Application Password', 'password', 'Prefira uma Application Password'],
    ['callsign', 'Indicativo do log', 'text', 'Ex.: PU2BRU'],
    ['api_key', 'API Key', 'password', 'Necessária para enviar/excluir QSOs'],
  ],
  EQSL: [
    ['username', 'Username / Indicativo', 'text', 'Ex.: PU2BRU'],
    ['password', 'Senha eQSL', 'password', 'Armazenada apenas no backend local'],
    ['qth_nickname', 'QTH Nickname (opcional)', 'text', 'Use se sua conta tiver mais de um perfil/QTH'],
  ],
}

const NAV = [
  ['home', 'Visão geral', '⌂'],
  ['differences', 'Diferenças', '≠'],
  ['qsos', 'QSOs', '◎'],
  ['manual', 'Comparar ADI', '⇄'],
  ['sources', 'Fontes', '◉'],
  ['security', 'Segurança', '⌾'],
]

function fmtDate(value) {
  if (!value) return 'Nunca'
  try { return new Date(value).toLocaleString('pt-BR') } catch { return value }
}
function qsoTitle(q) { return `${q?.call || '—'} · ${q?.date || '—'} ${q?.time || ''} · ${q?.band || '—'} · ${q?.mode || '—'}` }
function classNames(...xs) { return xs.filter(Boolean).join(' ') }
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)) }
function Pill({ children, tone = 'neutral' }) { return <span className={`pill tone-${tone}`}>{children}</span> }
function Button({ children, kind = 'primary', small = false, ...props }) { return <button className={classNames('btn', `btn-${kind}`, small && 'btn-small')} {...props}>{children}</button> }
function Panel({ title, subtitle, action, children, className = '' }) {
  return <section className={`panel ${className}`}>
    {(title || action) && <div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>}
    {children}
  </section>
}
function Empty({ children }) { return <div className="empty">{children || 'Nada para mostrar.'}</div> }
function Notice({ children, tone = 'info' }) { return <div className={`notice notice-${tone}`}>{children}</div> }

async function runSyncJob(provider, onProgress = () => {}) {
  let job = await api(`/api/cloud/sync-jobs/${provider}`, { method: 'POST', body: '{}' })
  onProgress(job)
  while (!['succeeded', 'failed'].includes(job.status)) {
    await sleep(450)
    job = await api(`/api/cloud/sync-jobs/${job.job_id}`)
    onProgress(job)
  }
  if (job.status === 'failed') throw new Error(job.error || job.message || `Falha ao atualizar ${provider}`)
  return job
}

function SyncProgress({ job, compact = false }) {
  if (!job) return null
  const active = ['queued', 'running'].includes(job.status)
  const failed = job.status === 'failed'
  const pct = Math.max(0, Math.min(100, Number(job.progress || 0)))
  return <div className={classNames('sync-progress', compact && 'compact', failed && 'failed', job.status === 'succeeded' && 'done')}>
    <div className="sync-progress-head">
      <span>{job.message || 'Sincronizando…'}</span>
      <b>{failed ? 'erro' : `${pct}%`}</b>
    </div>
    <div className={classNames('sync-progress-track', active && job.phase === 'downloading' && 'indeterminate')}>
      <span style={{ width: `${pct}%` }} />
    </div>
    {active && <small>{job.phase === 'downloading' ? 'Download em andamento; a barra anima enquanto a plataforma responde.' : job.phase}</small>}
    {failed && <small>{job.error}</small>}
  </div>
}

function SourceBadge({ p }) {
  const records = p?.snapshot?.records || 0
  return <div className="source-badge"><span className={classNames('dot', p?.configured ? 'dot-on' : 'dot-off')} /><b>{p?.label || p?.provider}</b><span>{p?.configured ? `${records.toLocaleString('pt-BR')} QSOs` : 'não conectado'}</span></div>
}

function SourceCard({ provider, onConfigure, onSync, job }) {
  const caps = provider.capabilities || {}
  const busy = ['queued', 'running'].includes(job?.status)
  const legacyEqsl = provider.provider === 'EQSL' && (provider.snapshot?.records || 0) > 0 && !provider.snapshot?.metadata?.download_strategy
  return <article className={classNames('source-card', provider.provider === 'QRZ' && 'source-card-truth')}>
    <div className="source-card-top">
      <div className="provider-logo">{provider.provider === 'CLUBLOG' ? 'CL' : provider.provider}</div>
      <div className="source-title"><div><b>{provider.label}</b>{provider.provider === 'QRZ' && <Pill tone="truth">base preferencial</Pill>}{legacyEqsl && <Pill tone="warn">re-sincronizar</Pill>}</div><span>{provider.configured ? 'Conectado' : 'Não configurado'}</span></div>
      <span className={classNames('status-light', provider.configured ? 'online' : '')} />
    </div>
    <div className="source-stat"><strong>{(provider.snapshot?.records || 0).toLocaleString('pt-BR')}</strong><span>QSOs no último snapshot</span></div>
    <div className="source-meta">Última atualização: <b>{fmtDate(provider.snapshot?.downloaded_at)}</b></div>
    <div className="cap-row">{caps.read && <Pill tone="ok">ler</Pill>}{caps.add && <Pill tone="ok">adicionar</Pill>}{caps.update && <Pill>editar</Pill>}{caps.delete && <Pill tone="warn">excluir</Pill>}</div>
    <p className="source-note">{legacyEqsl ? 'Snapshot eQSL criado pela rotina anterior. Atualize novamente para baixar o arquivo ADIF real do OutBox.' : provider.note}</p>
    <SyncProgress job={job} compact />
    <div className="source-actions"><Button kind="secondary" small onClick={() => onConfigure(provider)}>Configurar</Button><Button small disabled={!provider.configured || busy} onClick={() => onSync(provider.provider)}>{busy ? 'Atualizando…' : 'Atualizar agora'}</Button></div>
  </article>
}

function ConfigureModal({ provider, onClose, onSaved }) {
  const [values, setValues] = useState(provider?.credentials || {})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  if (!provider) return null
  const fields = PROVIDER_FIELDS[provider.provider] || []
  async function save(test = false) {
    setBusy(true); setMsg('')
    try {
      await api(`/api/cloud/connections/${provider.provider}`, { method: 'PUT', body: JSON.stringify({ values }) })
      if (test) {
        const result = await api(`/api/cloud/connections/${provider.provider}/test`, { method: 'POST', body: '{}' })
        setMsg(`Conexão validada${result.records ? ` · ${result.records.toLocaleString('pt-BR')} QSOs acessíveis` : ''}.`)
      } else setMsg('Configuração salva no computador.')
      await onSaved()
    } catch (e) { setMsg(`Erro: ${e.message}`) } finally { setBusy(false) }
  }
  async function disconnect() {
    if (!window.confirm(`Desconectar ${provider.label}? Os snapshots baixados serão preservados.`)) return
    setBusy(true)
    try { await api(`/api/cloud/connections/${provider.provider}`, { method: 'DELETE' }); await onSaved(); onClose() }
    catch (e) { setMsg(`Erro: ${e.message}`) } finally { setBusy(false) }
  }
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
    <div className="modal">
      <div className="modal-title"><div><span className="eyebrow">CONEXÃO SEGURA</span><h2>{provider.label}</h2></div><button className="icon-button" onClick={onClose}>×</button></div>
      <p className="muted">As credenciais ficam no backend local do QSO Manager. A interface nunca devolve a chave ou senha completa depois de salva.</p>
      <div className="fields">{fields.map(([key, label, type, help]) => <label key={key}><span>{label}</span><input type={type} value={values[key] || ''} onChange={e => setValues({ ...values, [key]: e.target.value })} placeholder={provider.credentials?.[key] || ''}/><small>{help}</small></label>)}</div>
      {msg && <Notice tone={msg.startsWith('Erro') ? 'error' : 'ok'}>{msg}</Notice>}
      <div className="modal-actions"><div>{provider.configured && <Button kind="danger" onClick={disconnect} disabled={busy}>Desconectar</Button>}</div><div className="button-row"><Button kind="secondary" onClick={() => save(false)} disabled={busy}>Salvar</Button><Button onClick={() => save(true)} disabled={busy}>{busy ? 'Validando…' : 'Salvar e testar'}</Button></div></div>
    </div>
  </div>
}

function Home({ status, analysis, refresh, onConfigure }) {
  const [jobs, setJobs] = useState({})
  const [message, setMessage] = useState('')
  const [syncAllBusy, setSyncAllBusy] = useState(false)
  const summary = analysis?.summary || {}

  function setJob(provider, job) { setJobs(prev => ({ ...prev, [provider]: job })) }

  async function sync(provider) {
    setMessage('')
    try {
      const job = await runSyncJob(provider, current => setJob(provider, current))
      setMessage(`${provider} atualizado com ${(job.records || 0).toLocaleString('pt-BR')} QSOs.`)
      await refresh()
    } catch (e) { setMessage(`Erro ao atualizar ${provider}: ${e.message}`) }
  }

  async function syncAll() {
    const configured = (status?.providers || []).filter(p => p.configured)
    if (!configured.length) return
    setSyncAllBusy(true); setMessage('Iniciando atualização das fontes conectadas…')
    const errors = []
    for (let i = 0; i < configured.length; i += 1) {
      const provider = configured[i].provider
      setMessage(`Atualizando ${i + 1}/${configured.length}: ${configured[i].label}…`)
      try { await runSyncJob(provider, current => setJob(provider, current)) }
      catch (e) { errors.push(`${provider}: ${e.message}`) }
    }
    await refresh()
    setMessage(errors.length ? `Atualização concluída com ${errors.length} erro(s): ${errors.join(' | ')}` : 'Todas as fontes conectadas foram atualizadas e a análise foi refeita.')
    setSyncAllBusy(false)
  }

  return <>
    <div className="page-hero"><div><span className="eyebrow">CENTRAL DE LOGS · PU2BRU</span><h1>Seus QSOs, sem trocar de plataforma.</h1><p>QRZ como referência principal, com WRL, Club Log e eQSL usados como evidências independentes de sincronização e consistência.</p></div><Button onClick={syncAll} disabled={syncAllBusy || !(status?.providers || []).some(p => p.configured)}>{syncAllBusy ? 'Atualizando…' : 'Atualizar tudo e analisar'}</Button></div>
    {message && <Notice tone={message.startsWith('Erro') || message.includes('erro(s)') ? 'error' : 'info'}>{message}</Notice>}
    <div className="truth-banner"><div className="truth-icon">★</div><div><b>QRZ é a base preferencial — não uma verdade cega.</b><span>{status?.truth_policy}</span></div></div>
    <div className="metric-grid"><div className="metric"><span>QSOs no QRZ</span><strong>{(summary.qrz_records || 0).toLocaleString('pt-BR')}</strong><small>snapshot atual</small></div><div className="metric metric-warn"><span>QRZ pode estar desatualizado</span><strong>{summary.qrz_stale_candidates || 0}</strong><small>{summary.qrz_likely_stale || 0} com 2+ evidências</small></div><div className="metric"><span>Faltando em outras bases</span><strong>{(summary.missing_elsewhere || 0).toLocaleString('pt-BR')}</strong><small>candidatos para sincronizar</small></div><div className="metric"><span>Campos divergentes</span><strong>{(summary.field_differences || 0).toLocaleString('pt-BR')}</strong><small>requerem inspeção</small></div><div className="metric"><span>Duplicidades prováveis</span><strong>{summary.probable_duplicates || 0}</strong><small>não viram falso faltante</small></div></div>
    <div className="source-grid">{(status?.providers || []).map(p => <SourceCard key={p.provider} provider={p} onConfigure={onConfigure} onSync={sync} job={jobs[p.provider]}/>)}</div>
    {analysis?.ignored_sources?.length > 0 && <Notice tone="warn">Fonte ignorada temporariamente na reconciliação: {analysis.ignored_sources.join(', ')}. Faça uma nova sincronização para validar o snapshot.</Notice>}
    {!analysis?.ready && <Panel title="Primeiro passo"><Notice tone="warn">{analysis?.reason || 'Configure e sincronize o QRZ para iniciar a análise conectada.'}</Notice></Panel>}
  </>
}

function FilterBar({ children }) { return <div className="filter-bar">{children}</div> }
function SelectFilter({ label, value, onChange, children }) { return <label className="filter-control"><span>{label}</span><select value={value} onChange={e => onChange(e.target.value)}>{children}</select></label> }

function Differences({ status, analysis, refresh }) {
  const [tab, setTab] = useState('qrz')
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [actionJob, setActionJob] = useState(null)
  const [targetFilter, setTargetFilter] = useState('ALL')
  const [fieldFilter, setFieldFilter] = useState('ALL')
  const [fieldProviderFilter, setFieldProviderFilter] = useState('ALL')

  const providers = status?.providers || []
  const configured = new Set(providers.filter(p => p.configured).map(p => p.provider))
  const byProvider = Object.fromEntries(providers.map(p => [p.provider, p]))
  const tabs = [['qrz', `QRZ pode estar atrasado (${analysis?.qrz_stale_candidates?.length || 0})`],['targets', `Faltando nas plataformas (${analysis?.missing_elsewhere?.length || 0})`],['fields', `Campos (${analysis?.field_differences?.length || 0})`],['dupes', `Duplicidades (${analysis?.probable_duplicates?.length || 0})`]]

  const targets = useMemo(() => [...new Set((analysis?.missing_elsewhere || []).map(q => q.target).filter(Boolean))].sort(), [analysis])
  const fieldNames = useMemo(() => [...new Set((analysis?.field_differences || []).map(d => d.field).filter(Boolean))].sort(), [analysis])
  const fieldProviders = useMemo(() => [...new Set((analysis?.field_differences || []).map(d => d.provider).filter(Boolean))].sort(), [analysis])
  const filteredTargets = useMemo(() => (analysis?.missing_elsewhere || []).filter(q => targetFilter === 'ALL' || q.target === targetFilter), [analysis, targetFilter])
  const filteredFields = useMemo(() => (analysis?.field_differences || []).filter(d => (fieldFilter === 'ALL' || d.field === fieldFilter) && (fieldProviderFilter === 'ALL' || d.provider === fieldProviderFilter)), [analysis, fieldFilter, fieldProviderFilter])

  function canDelete(provider) {
    const p = byProvider[provider]
    if (!p?.configured || !p?.capabilities?.delete) return false
    if (provider === 'CLUBLOG' && !p.credentials?.api_key) return false
    return true
  }

  async function publish(source, index, target, label) {
    setMessage(''); setBusy(`${source}-${index}-${target}`)
    try {
      await api('/api/cloud/publish', { method: 'POST', body: JSON.stringify({ source, index, target, confirm: false }) })
      if (!window.confirm(`${label}\n\nO QSO será enviado de ${source} para ${target}. O QSO Manager fará backup do snapshot antes da operação. Deseja continuar?`)) return
      const result = await api('/api/cloud/publish', { method: 'POST', body: JSON.stringify({ source, index, target, confirm: true }) })
      setMessage(`QSO enviado para ${target}${result.verification?.verified ? ' e verificado por re-FETCH.' : '.'}`)
      if (result.needs_resync && configured.has(target)) {
        setActionJob(null)
        try { await runSyncJob(target, setActionJob) } catch (e) { setMessage(`Operação concluída, mas a re-sincronização de ${target} falhou: ${e.message}`) }
      }
      await refresh()
    } catch (e) { setMessage(`Erro: ${e.message}`) } finally { setBusy('') }
  }

  async function removeFrom(provider, index, label) {
    setMessage(''); setBusy(`delete-${provider}-${index}`); setActionJob(null)
    try {
      const preview = await api(`/api/cloud/remote/${provider}/delete`, { method: 'POST', body: JSON.stringify({ index, confirm: false }) })
      const record = preview?.qso?.record || {}
      const detail = `${record.CALL || ''} ${record.QSO_DATE || ''} ${record.TIME_ON || ''} ${record.BAND || ''} ${record.SUBMODE || record.MODE || ''}`.trim()
      if (!window.confirm(`${label}\n\nO QRZ será mantido como está. Este QSO será EXCLUÍDO apenas do ${provider}.\n${detail}\n\nUm backup local do snapshot será criado antes. Continuar?`)) return
      await api(`/api/cloud/remote/${provider}/delete`, { method: 'POST', body: JSON.stringify({ index, confirm: true }) })
      setMessage(`QSO excluído do ${provider}. Re-sincronizando essa fonte…`)
      await runSyncJob(provider, setActionJob)
      await refresh()
      setMessage(`QSO excluído do ${provider} e snapshot atualizado.`)
    } catch (e) { setMessage(`Erro: ${e.message}`) } finally { setBusy('') }
  }

  if (!analysis?.ready) return <Panel title="Diferenças"><Empty>Sincronize o QRZ e ao menos uma segunda fonte.</Empty></Panel>
  return <>
    <div className="page-hero compact"><div><span className="eyebrow">RECONCILIAÇÃO MULTIFONTE</span><h1>Diferenças que merecem ação.</h1><p>O QRZ orienta a decisão, mas você pode tanto adicionar um QSO legítimo à base principal quanto remover um registro incorreto das plataformas que o contêm.</p></div></div>
    {message && <Notice tone={message.startsWith('Erro') ? 'error' : 'ok'}>{message}</Notice>}
    {actionJob && ['queued', 'running'].includes(actionJob.status) && <SyncProgress job={actionJob} />}
    <div className="tabs">{tabs.map(([k,l]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>

    {tab === 'qrz' && <Panel title="QSOs ausentes no QRZ" subtitle="Decida caso a caso: adicionar ao QRZ ou apagar a ocorrência incorreta das outras plataformas.">
      {!analysis.qrz_stale_candidates?.length ? <Empty>Nenhum candidato de desatualização do QRZ.</Empty> : <div className="case-list">{analysis.qrz_stale_candidates.map((q,i) => {
        const source = q.sources?.find(s => configured.has(s)) || q.sources?.[0]
        const idx = q.source_indexes?.[source]
        return <div className="case-row case-row-actions" key={`${q.call}-${q.date}-${q.time}-${i}`}>
          <div className="case-main"><div className="case-title"><b>{qsoTitle(q)}</b><Pill tone={q.assessment === 'QRZ_LIKELY_STALE' ? 'warn' : 'neutral'}>{q.assessment === 'QRZ_LIKELY_STALE' ? 'forte evidência' : 'revisar'}</Pill></div><p>{q.reason}</p><div className="evidence">Evidências: {(q.sources || []).map(s => <Pill key={s} tone="ok">{s}</Pill>)}</div></div>
          <div className="case-action-stack">
            {configured.has('QRZ') && source != null && idx != null ? <Button small disabled={!!busy} onClick={() => publish(source, idx, 'QRZ', qsoTitle(q))}>Adicionar ao QRZ</Button> : <Pill>QRZ não conectado</Pill>}
            {(q.sources || []).map(s => {
              const sIdx = q.source_indexes?.[s]
              return canDelete(s) && sIdx != null ? <Button key={s} small kind="danger" disabled={!!busy} onClick={() => removeFrom(s, sIdx, qsoTitle(q))}>Excluir do {s}</Button> : null
            })}
          </div>
        </div>
      })}</div>}
    </Panel>}

    {tab === 'targets' && <Panel title="QSOs do QRZ que faltam nas outras bases" subtitle="Filtre por destino para decidir e sincronizar uma plataforma de cada vez.">
      <FilterBar>
        <SelectFilter label="Plataforma" value={targetFilter} onChange={setTargetFilter}>
          <option value="ALL">Todas ({analysis.missing_elsewhere?.length || 0})</option>
          {targets.map(t => <option key={t} value={t}>{t} ({(analysis.missing_elsewhere || []).filter(q => q.target === t).length})</option>)}
        </SelectFilter>
        <div className="filter-summary"><b>{filteredTargets.length.toLocaleString('pt-BR')}</b><span>QSOs exibidos</span></div>
      </FilterBar>
      {!filteredTargets.length ? <Empty>Nenhum QSO faltante para este filtro.</Empty> : <div className="case-list">{filteredTargets.map((q,i) => <div className="case-row" key={`${q.target}-${q.call}-${q.date}-${q.time}-${i}`}><div className="case-main"><div className="case-title"><b>{qsoTitle(q)}</b><Pill tone="warn">faltando em {q.target}</Pill></div><p>{q.reason}</p></div><div className="case-action">{configured.has(q.target) ? <Button small disabled={!!busy} onClick={() => publish('QRZ', q.qrz_index, q.target, qsoTitle(q))}>Enviar para {q.target}</Button> : <Pill>{q.target} não conectado</Pill>}</div></div>)}</div>}
    </Panel>}

    {tab === 'fields' && <Panel title="Campos divergentes" subtitle="Filtre por campo e por fonte para concentrar a revisão no tipo de divergência que interessa.">
      <FilterBar>
        <SelectFilter label="Campo" value={fieldFilter} onChange={setFieldFilter}><option value="ALL">Todos os campos</option>{fieldNames.map(f => <option key={f} value={f}>{f} ({(analysis.field_differences || []).filter(d => d.field === f).length})</option>)}</SelectFilter>
        <SelectFilter label="Fonte" value={fieldProviderFilter} onChange={setFieldProviderFilter}><option value="ALL">Todas as fontes</option>{fieldProviders.map(p => <option key={p} value={p}>{p}</option>)}</SelectFilter>
        <div className="filter-summary"><b>{filteredFields.length.toLocaleString('pt-BR')}</b><span>divergências exibidas</span></div>
      </FilterBar>
      {!filteredFields.length ? <Empty>Nenhuma divergência para este filtro.</Empty> : <div className="table-wrap"><table><thead><tr><th>QSO</th><th>Campo</th><th>QRZ</th><th>Outra fonte</th><th>Origem</th></tr></thead><tbody>{filteredFields.map((d,i) => <tr key={`${d.provider}-${d.call}-${d.date}-${d.field}-${i}`}><td><b>{d.call}</b><small>{d.date} {d.time} · {d.band}</small></td><td><Pill>{d.field}</Pill></td><td className="preferred">{String(d.value_a ?? '∅')}</td><td>{String(d.value_b ?? '∅')}</td><td><Pill>{d.provider}</Pill></td></tr>)}</tbody></table></div>}
    </Panel>}

    {tab === 'dupes' && <Panel title="Duplicidades prováveis" subtitle="Registros praticamente idênticos na mesma fonte não são classificados como QSO faltante.">{!analysis.probable_duplicates?.length ? <Empty>Nenhuma duplicidade provável encontrada.</Empty> : <div className="case-list">{analysis.probable_duplicates.map((d,i) => <div className="case-row" key={i}><div className="case-main"><div className="case-title"><b>{d.call} · {d.date} · {d.band} · {d.mode}</b><Pill tone="warn">{d.source}</Pill></div><p>{d.reason}</p><div className="duplicate-times">{(d.records || []).map((r,j)=><code key={j}>{r.time} · {r.freq_mhz || '—'} MHz</code>)}</div></div></div>)}</div>}</Panel>}
  </>
}

function QsoSearch({ status, refresh }) {
  const [call, setCall] = useState('')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [syncJob, setSyncJob] = useState(null)
  async function search(e) { e?.preventDefault(); setLoading(true); setMessage(''); try { const r = await api(`/api/cloud/search?call=${encodeURIComponent(call)}&limit=1000`); setRows(r.items || []); if (r.truncated) setMessage('Resultado limitado aos primeiros 1.000 registros.') } catch (e) { setMessage(`Erro: ${e.message}`) } finally { setLoading(false) } }
  async function remove(row) {
    const p = (status?.providers || []).find(x => x.provider === row.provider)
    if (!p?.capabilities?.delete) return
    try {
      const preview = await api(`/api/cloud/remote/${row.provider}/delete`, { method: 'POST', body: JSON.stringify({ index: row.index, confirm: false }) })
      if (!window.confirm(`Excluir remotamente este QSO de ${row.provider}?\n\n${JSON.stringify(preview.qso.record, null, 2)}\n\nUm backup local do snapshot será feito antes.`)) return
      await api(`/api/cloud/remote/${row.provider}/delete`, { method: 'POST', body: JSON.stringify({ index: row.index, confirm: true }) })
      setMessage(`Exclusão enviada para ${row.provider}. Atualizando snapshot…`)
      setSyncJob(null); await runSyncJob(row.provider, setSyncJob)
      await refresh(); await search()
    } catch (e) { setMessage(`Erro: ${e.message}`) }
  }
  async function editWRL(row) {
    const field = window.prompt('Campo WRL a corrigir: RST_SENT, RST_RCVD, COMMENT, GRIDSQUARE, STATE, CALL, FREQ, BAND ou MODE')
    if (!field) return
    const key = field.trim().toUpperCase()
    const allowed = new Set(['RST_SENT','RST_RCVD','COMMENT','GRIDSQUARE','STATE','CALL','FREQ','BAND','MODE'])
    if (!allowed.has(key)) return setMessage('Campo não suportado para edição WRL por esta tela.')
    const value = window.prompt(`Novo valor para ${key}:`, String(row.record?.[key] ?? ''))
    if (value == null) return
    try {
      await api('/api/cloud/remote/WRL/update', { method: 'POST', body: JSON.stringify({ index: row.index, changes: { [key]: value }, confirm: false }) })
      if (!window.confirm(`Aplicar ${key}=${value} no WRL? Um backup local será feito antes.`)) return
      await api('/api/cloud/remote/WRL/update', { method: 'POST', body: JSON.stringify({ index: row.index, changes: { [key]: value }, confirm: true }) })
      setMessage('WRL atualizado. Sincronizando novamente…'); setSyncJob(null); await runSyncJob('WRL', setSyncJob); await refresh(); await search()
    } catch (e) { setMessage(`Erro: ${e.message}`) }
  }
  return <><div className="page-hero compact"><div><span className="eyebrow">GESTÃO LOCAL</span><h1>Consultar QSOs em todas as fontes.</h1><p>Pesquise por indicativo e veja o registro bruto de cada plataforma sem abrir QRZ, WRL, Club Log ou eQSL.</p></div></div><Panel title="Pesquisar" action={<Pill>{rows.length} registros</Pill>}><form className="searchbar" onSubmit={search}><input value={call} onChange={e=>setCall(e.target.value.toUpperCase())} placeholder="Indicativo, ex.: LU6YR"/><Button disabled={loading}>{loading ? 'Buscando…' : 'Buscar'}</Button></form>{message && <Notice tone={message.startsWith('Erro')?'error':'info'}>{message}</Notice>}{syncJob && ['queued','running'].includes(syncJob.status) && <SyncProgress job={syncJob}/>}</Panel><Panel title="Resultados">{!rows.length ? <Empty>Digite um indicativo para consultar os snapshots baixados.</Empty> : <div className="table-wrap"><table><thead><tr><th>Fonte</th><th>QSO</th><th>Freq.</th><th>RST</th><th>Grid</th><th>ID remoto</th><th>Ações</th></tr></thead><tbody>{rows.map((r,i)=>{const x=r.record||{}; const p=(status?.providers||[]).find(p=>p.provider===r.provider); return <tr key={`${r.provider}-${r.index}-${i}`}><td><Pill tone={r.provider==='QRZ'?'truth':'neutral'}>{r.provider}</Pill></td><td><b>{x.CALL}</b><small>{x.QSO_DATE} {x.TIME_ON} · {x.BAND} · {x.SUBMODE||x.MODE}</small></td><td>{x.FREQ || '—'}</td><td>{x.RST_SENT||'—'} / {x.RST_RCVD||'—'}</td><td>{x.GRIDSQUARE||x.GRID||'—'}</td><td><code>{r.external_id||'—'}</code></td><td><div className="button-row">{r.provider==='WRL'&&p?.capabilities?.update&&<Button small kind="secondary" onClick={()=>editWRL(r)}>Editar</Button>}{p?.capabilities?.delete&&<Button small kind="danger" onClick={()=>remove(r)}>Excluir</Button>}</div></td></tr>})}</tbody></table></div>}</Panel></>
}

function ManualCompare() {
  const [a, setA] = useState(null), [b, setB] = useState(null)
  const [sourceA, setSourceA] = useState('QRZ'), [sourceB, setSourceB] = useState('WRL')
  const [coverageA, setCoverageA] = useState('FULL_EXPORT'), [coverageB, setCoverageB] = useState('FULL_EXPORT')
  const [result, setResult] = useState(null), [busy, setBusy] = useState(false), [message, setMessage] = useState('')
  function detect(file, side) { if (!file) return; const n=file.name.toUpperCase(); let s=side==='a'?sourceA:sourceB; if(n.includes('QRZ'))s='QRZ'; else if(n.includes('WRL'))s='WRL'; else if(n.includes('CLUB'))s='CLUBLOG'; else if(n.includes('EQSL'))s='EQSL'; else if(n.includes('MSHV'))s='MSHV'; const c=n.includes('_ALL')||n.includes('FULL')?'FULL_EXPORT':'PARTIAL_EXPORT'; if(side==='a'){setA(file);setSourceA(s);setCoverageA(c)}else{setB(file);setSourceB(s);setCoverageB(c)} }
  async function compare() { if(!a||!b) return setMessage('Selecione os dois arquivos ADIF.'); setBusy(true);setMessage('');setResult(null); try{const [ca,cb]=await Promise.all([a.text(),b.text()]); const r=await api('/api/comparisons/adif',{method:'POST',body:JSON.stringify({a:{content:ca,source:sourceA,filename:a.name,coverage:coverageA},b:{content:cb,source:sourceB,filename:b.name,coverage:coverageB}})});setResult(r)}catch(e){setMessage(`Erro: ${e.message}`)}finally{setBusy(false)} }
  const missing=[...(result?.missing_in_a||[]),...(result?.missing_in_b||[])]
  return <><div className="page-hero compact"><div><span className="eyebrow">MODO MANUAL</span><h1>Comparar dois arquivos ADIF.</h1><p>O fluxo original continua disponível para qualquer serviço ou arquivo que não esteja conectado por API.</p></div></div><div className="two-col">{[['a',a,sourceA,setSourceA,coverageA,setCoverageA],['b',b,sourceB,setSourceB,coverageB,setCoverageB]].map(([side,file,source,setSource,coverage,setCoverage])=><Panel key={side} title={`Log ${side.toUpperCase()}`}><label className="dropzone"><input type="file" accept=".adi,.adif,.txt" onChange={e=>detect(e.target.files?.[0],side)}/><strong>{file?.name||'Selecionar arquivo ADIF'}</strong><span>{file?`${(file.size/1024/1024).toFixed(1)} MB`:'QRZ, WRL, Club Log, eQSL ou qualquer ADIF'}</span></label><div className="inline-fields"><label>Fonte<input value={source} onChange={e=>setSource(e.target.value.toUpperCase())}/></label><label>Cobertura<select value={coverage} onChange={e=>setCoverage(e.target.value)}><option>FULL_EXPORT</option><option>PARTIAL_EXPORT</option><option>FILTERED_EXPORT</option></select></label></div></Panel>)}</div><div className="center-action"><Button onClick={compare} disabled={busy}>{busy?'Comparando…':'Comparar ADIs'}</Button></div>{message&&<Notice tone="error">{message}</Notice>}{result&&<><div className="metric-grid four"><div className="metric"><span>Pareados</span><strong>{result.summary.matched}</strong></div><div className="metric metric-warn"><span>Diferenças de presença</span><strong>{missing.length}</strong></div><div className="metric"><span>Duplicidades</span><strong>{result.summary.probable_duplicates}</strong></div><div className="metric"><span>Campos</span><strong>{result.summary.field_differences}</strong></div></div><Panel title="Diferenças de presença">{!missing.length?<Empty>Nenhuma diferença de presença.</Empty>:<div className="case-list">{missing.map((q,i)=><div className="case-row" key={i}><div><b>{qsoTitle(q)}</b><p>{q.reason}</p></div><Pill tone="warn">{q.present_in} → falta em {q.missing_in}</Pill></div>)}</div>}</Panel><Panel title="Duplicidades prováveis">{!result.probable_duplicates?.length?<Empty>Nenhuma.</Empty>:<div className="case-list">{result.probable_duplicates.map((d,i)=><div className="case-row" key={i}><div><b>{d.call} · {d.date} · {d.band}</b><p>{d.reason}</p></div><Pill>{d.source}</Pill></div>)}</div>}</Panel></>}</>
}

function Sources({ status, refresh, onConfigure }) {
  const [jobs,setJobs]=useState({}),[msg,setMsg]=useState('')
  function setJob(p, job) { setJobs(prev => ({ ...prev, [p]: job })) }
  async function sync(p){setMsg('');try{const job=await runSyncJob(p,current=>setJob(p,current));setMsg(`${p} atualizado com ${(job.records||0).toLocaleString('pt-BR')} QSOs.`);await refresh()}catch(e){setMsg(`Erro: ${e.message}`)}}
  return <><div className="page-hero compact"><div><span className="eyebrow">CONEXÕES</span><h1>Fontes do seu log.</h1><p>As chaves ficam no backend local. Snapshots são preservados para análise, backup e comparação mesmo quando uma API estiver indisponível.</p></div></div>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}<div className="source-grid">{(status?.providers||[]).map(p=><SourceCard key={p.provider} provider={p} onConfigure={onConfigure} onSync={sync} job={jobs[p.provider]}/>)}</div></>
}

function Security({ status }) {
  return <><div className="page-hero compact"><div><span className="eyebrow">GUARDRAILS</span><h1>Gestão sem transformar sincronização em risco.</h1><p>Leitura e análise são amplas; escrita remota respeita o que cada plataforma documenta e exige confirmação explícita.</p></div></div><Panel title="Política de escrita remota"><div className="security-cards"><div><b>QRZ</b><p>Leitura completa e inclusão de QSO ausente. REPLACE, edição arbitrária e DELETE permanecem bloqueados porque o QRZ é sua base preferencial e confirmações não devem ser colocadas em risco.</p></div><div><b>WRL</b><p>CRUD disponível por ID remoto estável. Toda edição/exclusão parte de um snapshot e pede confirmação.</p></div><div><b>Club Log</b><p>Inclusão individual e exclusão por identidade exata. O QSO Manager não usa upload em lote para simular tempo real.</p></div><div><b>eQSL</b><p>Leitura do OutBox e inclusão de QSO. Edição/exclusão remota não é oferecida sem interface oficial documentada.</p></div></div></Panel><Panel title="Matriz de capacidades"><div className="table-wrap"><table><thead><tr><th>Fonte</th><th>Ler</th><th>Adicionar</th><th>Editar</th><th>Excluir</th><th>Credenciais</th></tr></thead><tbody>{(status?.providers||[]).map(p=><tr key={p.provider}><td><b>{p.label}</b></td>{['read','add','update','delete'].map(k=><td key={k}>{p.capabilities?.[k]?<Pill tone="ok">sim</Pill>:<Pill>bloqueado</Pill>}</td>)}<td>{p.configured?<Pill tone="ok">configuradas</Pill>:<Pill>não configuradas</Pill>}</td></tr>)}</tbody></table></div></Panel><Panel title="Backups e confirmação"><ul className="policy-list"><li>Snapshots baixados ficam no diretório local do QSO Manager e são a base da análise.</li><li>Antes de uma escrita/exclusão suportada, o snapshot do destino é copiado para backup.</li><li>Adicionar ao QRZ usa INSERT sem REPLACE e faz re-FETCH do LOGID retornado.</li><li>Nenhuma divergência de campo sobrescreve automaticamente o QRZ.</li></ul></Panel></>
}

export default function App510() {
  const [view,setView]=useState('home'),[status,setStatus]=useState(null),[analysis,setAnalysis]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[configure,setConfigure]=useState(null)
  async function refresh(){setError('');try{const [s,a]=await Promise.all([api('/api/cloud/status'),api('/api/cloud/analysis')]);setStatus(s);setAnalysis(a)}catch(e){setError(e.message)}finally{setLoading(false)}}
  useEffect(()=>{refresh()},[])
  const pageTitle=useMemo(()=>NAV.find(n=>n[0]===view)?.[1]||'QSO Manager',[view])
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark">PU</div><div><b>QSO Manager</b><span>PU2BRU · v5.1</span></div></div><nav>{NAV.map(([k,l,icon])=><button key={k} className={view===k?'active':''} onClick={()=>setView(k)}><span className="nav-icon">{icon}</span><span>{l}</span>{k==='differences'&&analysis?.summary?.qrz_stale_candidates>0&&<em>{analysis.summary.qrz_stale_candidates}</em>}</button>)}</nav><div className="sidebar-bottom"><span className={classNames('dot',status?.providers?.some(p=>p.configured)?'dot-on':'dot-off')}/><div><b>Modo local</b><small>127.0.0.1 · dados no PC</small></div></div></aside><main><header className="topbar"><div><span className="eyebrow">PU2BRU QSO MANAGER</span><h3>{pageTitle}</h3></div><div className="top-sources">{(status?.providers||[]).map(p=><SourceBadge key={p.provider} p={p}/>)}</div></header><div className="content">{error&&<Notice tone="error">{error}</Notice>}{loading?<div className="loading">Carregando central de logs…</div>:<>{view==='home'&&<Home status={status} analysis={analysis} refresh={refresh} onConfigure={setConfigure}/>} {view==='differences'&&<Differences status={status} analysis={analysis} refresh={refresh}/>} {view==='qsos'&&<QsoSearch status={status} refresh={refresh}/>} {view==='manual'&&<ManualCompare/>} {view==='sources'&&<Sources status={status} refresh={refresh} onConfigure={setConfigure}/>} {view==='security'&&<Security status={status}/>}</>}</div></main>{configure&&<ConfigureModal provider={configure} onClose={()=>setConfigure(null)} onSaved={async()=>{await refresh(); const fresh=(await api('/api/cloud/status')).providers.find(p=>p.provider===configure.provider); if(fresh)setConfigure(fresh)}}/>}</div>
}
