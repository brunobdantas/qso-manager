import React, { useMemo, useState } from 'react'
import App600 from './App600.jsx'

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

const fmt = n => Number(n || 0).toLocaleString('pt-BR')
const cls = (...values) => values.filter(Boolean).join(' ')
const uid = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`

function Button({ children, kind = 'primary', small = false, ...props }) {
  return <button className={cls('btn', `btn-${kind}`, small && 'btn-small')} {...props}>{children}</button>
}
function Pill({ children, tone = 'neutral' }) { return <span className={`pill tone-${tone}`}>{children}</span> }
function Notice({ children, tone = 'info' }) { return <div className={`notice notice-${tone}`}>{children}</div> }
function Panel({ title, subtitle, action, children, className = '' }) {
  return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>
}
function Empty({ children }) { return <div className="empty">{children || 'Nada para mostrar.'}</div> }
function qsoTitle(q) { return `${q?.call || '—'} · ${q?.date || '—'} ${q?.time || ''} · ${q?.band || '—'} · ${q?.mode || '—'}` }

function csvValue(value) {
  const text = value == null ? '' : (typeof value === 'object' ? JSON.stringify(value) : String(value))
  return `"${text.replaceAll('"', '""')}"`
}
function downloadCsv(filename, rows) {
  if (!rows.length) return
  const columns = [...new Set(rows.flatMap(row => Object.keys(row)))]
  const body = [columns.map(csvValue).join(';'), ...rows.map(row => columns.map(col => csvValue(row[col])).join(';'))].join('\r\n')
  downloadBlob(filename, `\ufeff${body}`, 'text/csv;charset=utf-8')
}
function downloadJson(filename, data) { downloadBlob(filename, JSON.stringify(data, null, 2), 'application/json;charset=utf-8') }
function downloadBlob(filename, content, type) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function ToolShell({ title, eyebrow, onBack, children }) {
  return <div className="v7-shell">
    <header className="v7-topbar">
      <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1></div>
      <div className="button-row"><Pill tone="ok">v7.0</Pill><Button kind="secondary" onClick={onBack}>← Voltar ao QSO Manager</Button></div>
    </header>
    <main className="v7-content">{children}</main>
  </div>
}

function sourceSeed(name) {
  return { id: uid(), name, file: null, coverage: 'FULL_EXPORT' }
}

export function AdvancedCompare() {
  const [sources, setSources] = useState([sourceSeed('QRZ'), sourceSeed('WRL')])
  const [referenceId, setReferenceId] = useState(() => null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [tab, setTab] = useState('presence')
  const refId = referenceId || sources[0]?.id

  function patch(id, changes) { setSources(rows => rows.map(row => row.id === id ? { ...row, ...changes } : row)) }
  function remove(id) {
    setSources(rows => rows.filter(row => row.id !== id))
    if (refId === id) setReferenceId(null)
  }
  async function compare() {
    setMessage(''); setResult(null)
    if (sources.length < 2) return setMessage('Adicione ao menos duas fontes.')
    if (sources.some(row => !row.file)) return setMessage('Selecione um arquivo ADIF para cada fonte.')
    if (sources.some(row => !row.name.trim())) return setMessage('Todas as fontes precisam de um nome.')
    const names = sources.map(row => row.name.trim().toUpperCase())
    if (new Set(names).size !== names.length) return setMessage('Os nomes das fontes precisam ser exclusivos. Use nomes como HRD_ATUAL e HRD_ANTERIOR para históricos.')
    setBusy(true)
    try {
      const payloadSources = await Promise.all(sources.map(async row => ({
        content: await row.file.text(), source: row.name.trim().toUpperCase(), filename: row.file.name, coverage: row.coverage,
      })))
      const referenceIndex = Math.max(0, sources.findIndex(row => row.id === refId))
      setResult(await api('/api/advanced/compare', { method: 'POST', body: JSON.stringify({ sources: payloadSources, reference_index: referenceIndex }) }))
    } catch (e) { setMessage(`Erro: ${e.message}`) } finally { setBusy(false) }
  }

  function exportFindings() {
    if (!result) return
    const rows = []
    for (const x of result.presence_differences || []) rows.push({ tipo: 'PRESENCA', par: x.pair, categoria: x.category, call: x.call, data: x.date, hora: x.time, banda: x.band, modo: x.mode, presente_em: x.present_in, ausente_em: x.missing_in, confianca: x.confidence, motivo: x.reason })
    for (const x of result.field_differences || []) rows.push({ tipo: 'CAMPO', par: x.pair, call: x.call, data: x.date, hora: x.time, banda: x.band, campo: x.field, valor_referencia: x.value_a, valor_comparado: x.value_b, fonte_comparada: x.compared_source, severidade: x.severity, motivo: x.reason })
    for (const x of result.tolerated_differences || []) rows.push({ tipo: 'TOLERADO', par: x.pair, call: x.call, data: x.date, hora: x.time, banda: x.band, campo: x.field, valor_referencia: x.value_a, valor_comparado: x.value_b, fonte_comparada: x.compared_source, motivo: x.reason })
    for (const x of result.matches || []) rows.push({ tipo: 'MATCH', par: x.pair, call: x.reference?.call, data: x.reference?.date, hora_referencia: x.reference?.time, hora_comparada: x.compared?.time, banda: x.reference?.band, modo_referencia: x.reference?.mode, modo_comparado: x.compared?.mode, delta_tempo_s: x.evidence?.time_diff_seconds, delta_freq_hz: x.evidence?.freq_diff_hz, score: x.evidence?.score, motivo: x.reason })
    for (const x of result.review_candidates || []) rows.push({ tipo: 'REVISAR_MATCH', par: x.pair, call: x.reference?.call, data: x.reference?.date, hora_referencia: x.reference?.time, hora_comparada: x.compared?.time, banda: x.reference?.band, delta_tempo_s: x.evidence?.time_diff_seconds, motivo: x.reason })
    for (const x of result.probable_duplicates || []) rows.push({ tipo: 'DUPLICIDADE', par: x.pair, fonte: x.source, call: x.call, data: x.date, banda: x.band, modo: x.mode, registros: x.records?.map(r => r.index).join(','), motivo: x.reason })
    downloadCsv('qso-manager-comparacao-avancada.csv', rows)
  }

  const tabs = [
    ['presence', `Presença (${fmt(result?.summary?.presence_differences)})`],
    ['fields', `Campos (${fmt(result?.summary?.field_differences)})`],
    ['matches', `Pareamentos (${fmt(result?.summary?.matched_pairs)})`],
    ['review', `Revisar (${fmt(result?.summary?.review_candidates)})`],
    ['dupes', `Duplicidades (${fmt(result?.summary?.probable_duplicates)})`],
  ]

  return <>
    <div className="page-hero compact"><div><span className="eyebrow">ITEM 1 · COMPARAÇÃO AVANÇADA</span><h1>Compare quantos ADIFs precisar.</h1><p>Escolha uma fonte de referência, adicione exports atuais ou históricos e inspecione presença, campos, tolerâncias, duplicidades e a evidência de cada pareamento.</p></div><div className="button-row"><Button kind="secondary" disabled={!result} onClick={exportFindings}>Exportar achados CSV</Button><Button kind="secondary" disabled={!result} onClick={() => downloadJson('qso-manager-comparacao-avancada.json', result)}>Exportar JSON</Button></div></div>
    {message && <Notice tone={message.startsWith('Erro') ? 'error' : 'warn'}>{message}</Notice>}
    <Panel title="Fontes ADIF" subtitle="A referência é comparada individualmente com todas as demais fontes. Cobertura parcial evita afirmar ausência quando o arquivo não representa o log completo." action={<Button small onClick={() => setSources(rows => [...rows, sourceSeed(`FONTE_${rows.length + 1}`)])}>+ Adicionar fonte</Button>}>
      <div className="v7-source-list">{sources.map((row, index) => <article className={cls('v7-source-row', row.id === refId && 'reference')} key={row.id}>
        <label className="v7-ref-radio"><input type="radio" name="reference" checked={row.id === refId} onChange={() => setReferenceId(row.id)}/><span>{row.id === refId ? 'Referência' : `Fonte ${index + 1}`}</span></label>
        <label><span>Nome da fonte</span><input value={row.name} onChange={e => patch(row.id, { name: e.target.value.toUpperCase() })} placeholder="Ex.: QRZ, HRD_ATUAL, HRD_ANTERIOR"/></label>
        <label><span>Cobertura</span><select value={row.coverage} onChange={e => patch(row.id, { coverage: e.target.value })}><option value="FULL_EXPORT">Export completo</option><option value="PARTIAL_EXPORT">Parcial</option><option value="FILTERED_EXPORT">Filtrado</option></select></label>
        <label className="v7-file"><span>Arquivo ADIF</span><input type="file" accept=".adi,.adif,.txt" onChange={e => patch(row.id, { file: e.target.files?.[0] || null })}/><small>{row.file?.name || 'Nenhum arquivo selecionado'}</small></label>
        <Button kind="danger" small disabled={sources.length <= 2} onClick={() => remove(row.id)}>Remover</Button>
      </article>)}</div>
    </Panel>
    <div className="center-action"><Button disabled={busy} onClick={compare}>{busy ? 'Comparando fontes…' : `Comparar ${sources.length} fontes`}</Button></div>

    {result && <>
      <div className="manager-kpis v7-kpis"><div><span>Fontes</span><b>{fmt(result.summary?.source_count)}</b></div><div><span>Pareamentos</span><b>{fmt(result.summary?.matched_pairs)}</b></div><div><span>Diferenças de presença</span><b>{fmt(result.summary?.presence_differences)}</b></div><div><span>Campos divergentes</span><b>{fmt(result.summary?.field_differences)}</b></div><div><span>Revisar</span><b>{fmt(result.summary?.review_candidates)}</b></div></div>
      <div className="tabs v7-tabs">{tabs.map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
      {tab === 'presence' && <Panel title="Diferenças de presença" subtitle="A confiança HIGH só aparece quando a fonte ausente foi declarada como export completo.">{!(result.presence_differences || []).length ? <Empty>Nenhuma diferença de presença.</Empty> : <div className="table-wrap"><table><thead><tr><th>QSO</th><th>Par</th><th>Presente</th><th>Ausente</th><th>Confiança</th><th>Motivo</th></tr></thead><tbody>{result.presence_differences.map((x, i) => <tr key={i}><td><b>{qsoTitle(x)}</b></td><td>{x.pair}</td><td><Pill tone="ok">{x.present_in}</Pill></td><td><Pill tone="warn">{x.missing_in}</Pill></td><td>{x.confidence}</td><td>{x.reason}</td></tr>)}</tbody></table></div>}</Panel>}
      {tab === 'fields' && <Panel title="Campos divergentes">{!(result.field_differences || []).length ? <Empty>Nenhum campo relevante divergente.</Empty> : <div className="table-wrap"><table><thead><tr><th>QSO</th><th>Campo</th><th>Referência</th><th>Comparado</th><th>Fonte</th><th>Motivo</th></tr></thead><tbody>{result.field_differences.map((x, i) => <tr key={i}><td><b>{x.call}</b><small>{x.date} {x.time} · {x.band}</small></td><td><Pill tone="warn">{x.field}</Pill></td><td className="preferred">{String(x.value_a ?? '∅')}</td><td>{String(x.value_b ?? '∅')}</td><td>{x.compared_source}</td><td>{x.reason}</td></tr>)}</tbody></table></div>}</Panel>}
      {tab === 'matches' && <Panel title="Evidência dos pareamentos" subtitle="Mostra por que dois registros foram tratados como o mesmo QSO.">{!(result.matches || []).length ? <Empty>Nenhum pareamento.</Empty> : <div className="table-wrap"><table><thead><tr><th>QSO referência</th><th>Fonte comparada</th><th>Hora comparada</th><th>Δ tempo</th><th>Δ frequência</th><th>Score</th><th>Explicação</th></tr></thead><tbody>{result.matches.slice(0, 5000).map((x, i) => <tr key={i}><td><b>{qsoTitle(x.reference)}</b></td><td>{x.compared_source}</td><td>{x.compared?.time || '—'}</td><td>{x.evidence?.time_diff_seconds == null ? '—' : `${x.evidence.time_diff_seconds}s`}</td><td>{x.evidence?.freq_diff_hz == null ? '—' : `${x.evidence.freq_diff_hz} Hz`}</td><td>{x.evidence?.score ?? '—'}</td><td>{x.reason}</td></tr>)}</tbody></table></div>}</Panel>}
      {tab === 'review' && <Panel title="Pareamentos que exigem revisão">{!(result.review_candidates || []).length ? <Empty>Nenhum candidato fora da janela automática.</Empty> : <div className="case-list">{result.review_candidates.map((x, i) => <div className="case-row" key={i}><div><b>{qsoTitle(x.reference)}</b><p>{x.compared_source}: {x.compared?.time} · Δ {x.evidence?.time_diff_seconds}s. {x.reason}</p></div><Pill tone="warn">revisar</Pill></div>)}</div>}</Panel>}
      {tab === 'dupes' && <Panel title="Duplicidades prováveis">{!(result.probable_duplicates || []).length ? <Empty>Nenhuma duplicidade provável.</Empty> : <div className="case-list">{result.probable_duplicates.map((x, i) => <div className="case-row" key={i}><div><b>{x.call} · {x.date} · {x.band} · {x.mode}</b><p>{x.source}: {x.reason}</p></div><Pill>{x.records?.length || 0} registros</Pill></div>)}</div>}</Panel>}
    </>}
  </>
}

function evidenceSeed(kind, name) {
  return { id: uid(), kind, name, file: null, assumeReceived: true }
}

export function QSLHub() {
  const [reference, setReference] = useState({ name: 'QRZ', file: null })
  const [evidence, setEvidence] = useState([evidenceSeed('EQSL', 'EQSL_INBOX'), evidenceSeed('LOTW', 'LOTW_REPORT')])
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [tab, setTab] = useState('proposals')

  function patchEvidence(id, changes) { setEvidence(rows => rows.map(row => row.id === id ? { ...row, ...changes } : row)) }
  async function analyze() {
    setMessage(''); setResult(null)
    const active = evidence.filter(row => row.file)
    if (!reference.file) return setMessage('Selecione o export ADIF do QRZ que será usado como referência.')
    if (!active.length) return setMessage('Selecione ao menos uma fonte de evidência recebida, como eQSL Inbox ou LoTW report.')
    setBusy(true)
    try {
      const ref = { content: await reference.file.text(), source: reference.name.trim().toUpperCase() || 'QRZ', filename: reference.file.name, coverage: 'FULL_EXPORT' }
      const evidenceSources = await Promise.all(active.map(async row => ({ content: await row.file.text(), source: row.name.trim().toUpperCase(), filename: row.file.name, coverage: 'FULL_EXPORT', kind: row.kind, assume_received: row.assumeReceived })))
      setResult(await api('/api/advanced/qsl', { method: 'POST', body: JSON.stringify({ reference: ref, evidence_sources: evidenceSources }) }))
    } catch (e) { setMessage(`Erro: ${e.message}`) } finally { setBusy(false) }
  }

  function exportCorrections() {
    if (!result) return
    const rows = (result.proposals || []).map(p => ({
      CALL: p.qso?.call, QSO_DATE: p.qso?.date, TIME_ON: p.qso?.time, BAND: p.qso?.band, MODE: p.qso?.mode,
      SERVICO: p.service, FONTES_EVIDENCIA: p.sources?.join(', '), RECEBIDO_ATUAL: p.current_received ? 'Y' : 'N', DATA_ATUAL: p.current_date,
      CAMPO_RECEBIDO: p.received_field, NOVO_RECEBIDO: p.changes?.[p.received_field] || '', CAMPO_DATA: p.date_field, NOVA_DATA: p.changes?.[p.date_field] || '',
      DATA_EVIDENCIA: p.evidence_date || '', ACAO: p.actionable ? 'REVISAR/APLICAR' : 'SEM ALTERACAO', JUSTIFICATIVA: p.reason,
    }))
    downloadCsv('qso-manager-propostas-qsl.csv', rows)
  }

  const tabs = [
    ['proposals', `Propostas (${fmt(result?.summary?.actionable_proposals)})`],
    ['matrix', `Matriz (${fmt(result?.summary?.matched_confirmation_groups)})`],
    ['conflicts', `Conflitos (${fmt(result?.summary?.date_conflicts)})`],
    ['unmatched', `Sem par (${fmt(result?.summary?.unmatched_evidence)})`],
    ['review', `Revisar match (${fmt(result?.summary?.review_candidates)})`],
  ]

  return <>
    <div className="page-hero compact"><div><span className="eyebrow">ITEM 2 · CENTRAL DE QSLs</span><h1>Consolide eQSL e LoTW sem inventar datas.</h1><p>O QRZ funciona como referência. Arquivos de recebidos viram evidências independentes, agrupadas por QSO, com propostas auditáveis de campos a preencher.</p></div><div className="button-row"><Button kind="secondary" disabled={!result} onClick={exportCorrections}>Exportar propostas CSV</Button><Button kind="secondary" disabled={!result} onClick={() => downloadJson('qso-manager-evidencias-qsl.json', result)}>Exportar evidências JSON</Button></div></div>
    <Notice tone="warn"><b>Regra de segurança:</b> a data do contato (<code>QSO_DATE</code>) nunca é usada como data de recebimento. Se eQSL/LoTW não fornecer uma data explícita, a proposta marca apenas o recebido e deixa a data em branco para revisão.</Notice>
    {message && <Notice tone={message.startsWith('Erro') ? 'error' : 'warn'}>{message}</Notice>}

    <div className="v7-qsl-layout">
      <Panel title="1. Referência" subtitle="Use o export completo e mais recente do QRZ.">
        <label className="v7-field"><span>Nome</span><input value={reference.name} onChange={e => setReference(v => ({ ...v, name: e.target.value.toUpperCase() }))}/></label>
        <label className="v7-file-card"><input type="file" accept=".adi,.adif,.txt" onChange={e => setReference(v => ({ ...v, file: e.target.files?.[0] || null }))}/><strong>{reference.file?.name || 'Selecionar ADIF do QRZ'}</strong><span>{reference.file ? `${(reference.file.size / 1024 / 1024).toFixed(1)} MB` : 'base para localizar cada QSO'}</span></label>
      </Panel>
      <Panel title="2. Evidências recebidas" subtitle="eQSL Inbox/recebidos, LoTW report ou uma fonte de QSL em papel." action={<Button small onClick={() => setEvidence(rows => [...rows, evidenceSeed('PAPER', `QSL_${rows.length + 1}`)])}>+ Adicionar evidência</Button>}>
        <div className="v7-evidence-list">{evidence.map(row => <article className="v7-evidence-row" key={row.id}>
          <label><span>Tipo</span><select value={row.kind} onChange={e => patchEvidence(row.id, { kind: e.target.value })}><option value="EQSL">eQSL recebido</option><option value="LOTW">LoTW</option><option value="PAPER">QSL papel</option><option value="GENERIC">Genérica</option></select></label>
          <label><span>Nome</span><input value={row.name} onChange={e => patchEvidence(row.id, { name: e.target.value.toUpperCase() })}/></label>
          <label className="v7-file"><span>Arquivo</span><input type="file" accept=".adi,.adif,.txt" onChange={e => patchEvidence(row.id, { file: e.target.files?.[0] || null })}/><small>{row.file?.name || 'opcional'}</small></label>
          <label className="v7-check"><input type="checkbox" checked={row.assumeReceived} onChange={e => patchEvidence(row.id, { assumeReceived: e.target.checked })}/><span>Presença no arquivo comprova recebimento</span></label>
          <Button kind="danger" small disabled={evidence.length <= 1} onClick={() => setEvidence(rows => rows.filter(x => x.id !== row.id))}>Remover</Button>
        </article>)}</div>
      </Panel>
    </div>
    <div className="center-action"><Button disabled={busy} onClick={analyze}>{busy ? 'Cruzando confirmações…' : 'Analisar QSLs recebidos'}</Button></div>

    {result && <>
      <div className="manager-kpis v7-kpis"><div><span>Grupos confirmados</span><b>{fmt(result.summary?.matched_confirmation_groups)}</b></div><div><span>Propostas</span><b>{fmt(result.summary?.actionable_proposals)}</b></div><div><span>Sem par no QRZ</span><b>{fmt(result.summary?.unmatched_evidence)}</b></div><div><span>Conflitos de data</span><b>{fmt(result.summary?.date_conflicts)}</b></div><div><span>Sem data explícita</span><b>{fmt(result.summary?.missing_explicit_confirmation_date)}</b></div></div>
      <div className="tabs v7-tabs">{tabs.map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
      {tab === 'proposals' && <Panel title="Propostas de correção" subtitle="Nenhuma alteração é enviada ao QRZ automaticamente.">{!(result.proposals || []).length ? <Empty>Nenhuma confirmação nova precisa ser registrada.</Empty> : <div className="table-wrap"><table><thead><tr><th>QSO</th><th>Serviço</th><th>Evidência</th><th>Situação atual</th><th>Alterações propostas</th><th>Justificativa</th></tr></thead><tbody>{result.proposals.map((p, i) => <tr key={i}><td><b>{qsoTitle(p.qso)}</b></td><td><Pill tone="ok">{p.service}</Pill></td><td>{p.sources?.join(', ')}<small>Data: {p.evidence_date || 'não informada'}</small></td><td>{p.current_received ? 'recebido' : 'não recebido'}<small>{p.current_date || 'sem data'}</small></td><td><code>{Object.entries(p.changes || {}).map(([k, v]) => `${k}=${v}`).join(' · ')}</code></td><td>{p.reason}</td></tr>)}</tbody></table></div>}</Panel>}
      {tab === 'matrix' && <Panel title="Matriz de confirmação por QSO">{!(result.confirmation_matrix || []).length ? <Empty/> : <div className="table-wrap"><table><thead><tr><th>QSO</th><th>QRZ papel</th><th>QRZ eQSL</th><th>QRZ LoTW</th><th>Evidências encontradas</th></tr></thead><tbody>{result.confirmation_matrix.map((m, i) => <tr key={i}><td><b>{qsoTitle(m.qso)}</b></td>{['PAPER','EQSL','LOTW'].map(k => <td key={k}>{m.reference_confirmations?.[k]?.received ? <Pill tone="ok">recebido</Pill> : <Pill>não</Pill>}<small>{m.reference_confirmations?.[k]?.date || ''}</small></td>)}<td>{Object.entries(m.evidence || {}).map(([k, v]) => <span className="v7-matrix-evidence" key={k}><Pill tone="ok">{k}</Pill>{v.sources?.join(', ')} {v.evidence_date || 'sem data explícita'}</span>)}</td></tr>)}</tbody></table></div>}</Panel>}
      {tab === 'conflicts' && <Panel title="Conflitos preservados para revisão">{!(result.conflicts || []).length ? <Empty>Nenhum conflito de data.</Empty> : <div className="case-list">{result.conflicts.map((c, i) => <div className="case-row" key={i}><div><b>{qsoTitle(c.qso)} · {c.service}</b><p>{c.field}: atual {String(c.current_value || '∅')} × evidência {Array.isArray(c.evidence_value) ? c.evidence_value.join(', ') : String(c.evidence_value || '∅')}. {c.reason}</p></div><Pill tone="warn">não sobrescrito</Pill></div>)}</div>}</Panel>}
      {tab === 'unmatched' && <Panel title="Evidências sem correspondência na referência" subtitle="Podem indicar QSO ausente no QRZ, horário muito diferente ou arquivo de referência incompleto.">{!(result.unmatched_evidence || []).length ? <Empty>Nenhuma evidência ficou sem par.</Empty> : <div className="case-list">{result.unmatched_evidence.map((x, i) => <div className="case-row" key={i}><div><b>{qsoTitle(x)}</b><p>{x.reason}</p></div><Pill tone="warn">{x.source}</Pill></div>)}</div>}</Panel>}
      {tab === 'review' && <Panel title="Candidatos de pareamento manual">{!(result.review_candidates || []).length ? <Empty>Nenhum candidato duvidoso.</Empty> : <div className="case-list">{result.review_candidates.map((x, i) => <div className="case-row" key={i}><div><b>{qsoTitle(x.reference)}</b><p>{x.source}: evidência às {x.evidence_qso?.time || '—'} · Δ {x.evidence?.time_diff_seconds ?? '—'}s. {x.reason}</p></div><Pill tone="warn">revisar</Pill></div>)}</div>}</Panel>}
    </>}
  </>
}

export default function App700() {
  const [tool, setTool] = useState(null)
  const launcher = useMemo(() => <div className="v7-launcher"><div><b>Análises v7</b><span>novos módulos</span></div><button onClick={() => setTool('compare')}>⇄ Comparação avançada</button><button onClick={() => setTool('qsl')}>✓ Central de QSLs</button></div>, [])
  if (tool === 'compare') return <ToolShell eyebrow="PU2BRU · QSO MANAGER" title="Comparação avançada de ADIF" onBack={() => setTool(null)}><AdvancedCompare/></ToolShell>
  if (tool === 'qsl') return <ToolShell eyebrow="PU2BRU · QSO MANAGER" title="Central de QSLs recebidos" onBack={() => setTool(null)}><QSLHub/></ToolShell>
  return <div className="v7-host"><App600/>{launcher}</div>
}
