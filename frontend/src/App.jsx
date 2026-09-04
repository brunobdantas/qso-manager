import React, { useEffect, useMemo, useState } from 'react'

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  const text = await response.text()
  let payload = null
  if (text) { try { payload = JSON.parse(text) } catch { payload = text } }
  if (!response.ok) throw new Error(payload?.detail || payload || `${response.status} ${response.statusText}`)
  return payload
}

const COVERAGES = [
  ['FULL_EXPORT', 'Export completo'],
  ['PARTIAL_EXPORT', 'Export parcial'],
  ['FILTERED_EXPORT', 'Export filtrado'],
  ['DATE_RANGE', 'Intervalo de datas'],
]

function detectSource(filename = '') {
  const n = filename.toUpperCase()
  for (const source of ['QRZ', 'WRL', 'MSHV', 'HRDLOG', 'HAMRADIO', 'CLUBLOG', 'EQSL', 'LOTW']) {
    if (n.includes(source)) return source
  }
  if (n.includes('HRD')) return 'HRD'
  return ''
}

function detectCoverage(filename = '') {
  const n = filename.toUpperCase()
  return /(^|[_\- (])ALL([_\- ).(]|$)/.test(n) ? 'FULL_EXPORT' : 'PARTIAL_EXPORT'
}

const fmt = n => new Intl.NumberFormat('pt-BR').format(n ?? 0)

function FileCard({ label, side, onChange }) {
  const [drag, setDrag] = useState(false)
  function pick(file) {
    if (!file) return
    onChange({ file, source: detectSource(file.name) || side.source || '', coverage: detectCoverage(file.name) })
  }
  return <section className={`file-card ${drag ? 'drag' : ''}`}>
    <div className="file-card-head"><span className="file-letter">{label}</span><div><b>Log {label}</b><small>{side.file ? side.file.name : 'Selecione um arquivo ADIF'}</small></div></div>
    <label className="dropzone"
      onDragOver={e => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={e => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]) }}>
      <input type="file" accept=".adi,.adif,text/plain" onChange={e => pick(e.target.files?.[0])} />
      <div className="drop-icon">↥</div>
      <strong>{side.file ? 'Trocar arquivo' : 'Solte o .ADI aqui'}</strong>
      <span>{side.file ? `${(side.file.size / 1024 / 1024).toFixed(1)} MB` : 'ou clique para selecionar'}</span>
    </label>
    <div className="file-options">
      <label>Fonte<input value={side.source} placeholder="QRZ, WRL, MSHV…" onChange={e => onChange({ ...side, source: e.target.value.toUpperCase() })} /></label>
      <label>Cobertura<select value={side.coverage} onChange={e => onChange({ ...side, coverage: e.target.value })}>
        {COVERAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select></label>
    </div>
    {side.coverage === 'FULL_EXPORT' && <div className="coverage-note good">Export completo: ausência pode ser tratada como divergência de presença.</div>}
    {side.coverage !== 'FULL_EXPORT' && <div className="coverage-note">Cobertura limitada: ausência será marcada como inconclusiva.</div>}
  </section>
}

function Badge({ children, tone = 'neutral' }) { return <span className={`badge ${tone}`}>{children}</span> }

function Summary({ result }) {
  const s = result.summary
  const missing = s.missing_in_a + s.missing_in_b
  return <>
    <div className="result-title">
      <div><span className="kicker">COMPARAÇÃO CONCLUÍDA</span><h2>{result.source_a.name} × {result.source_b.name}</h2><p>{fmt(s.matched)} QSOs pareados com correspondência 1:1.</p></div>
      <Badge tone={missing ? 'warn' : 'ok'}>{missing ? `${fmt(missing)} diferenças de presença` : 'Presença alinhada'}</Badge>
    </div>
    <div className="metric-grid">
      <div className="metric"><span>{result.source_a.name}</span><strong>{fmt(s.records_a)}</strong><small>registros válidos</small></div>
      <div className="metric"><span>{result.source_b.name}</span><strong>{fmt(s.records_b)}</strong><small>registros válidos</small></div>
      <div className="metric accent"><span>Pareados</span><strong>{fmt(s.matched)}</strong><small>mesmo QSO</small></div>
      <div className="metric warn"><span>Presença</span><strong>{fmt(missing)}</strong><small>faltantes / extras</small></div>
      <div className="metric"><span>Duplicidades</span><strong>{fmt(s.probable_duplicates)}</strong><small>prováveis</small></div>
      <div className="metric"><span>Campos</span><strong>{fmt(s.field_differences)}</strong><small>diferenças relevantes</small></div>
    </div>
  </>
}

function QsoCore({ row }) {
  return <><td className="mono">{row.date}</td><td className="mono">{row.time || '—'}</td><td><strong>{row.call}</strong></td><td>{row.band || '—'}</td><td>{row.freq_mhz ? `${Number(row.freq_mhz).toFixed(6)} MHz` : '—'}</td><td>{row.mode || '—'}</td></>
}

function MissingTable({ rows }) {
  if (!rows.length) return <Empty text="Nenhuma divergência de presença nesta comparação." />
  return <div className="table-wrap"><table><thead><tr><th>Data</th><th>UTC</th><th>Call</th><th>Banda</th><th>Frequência</th><th>Modo</th><th>Presente</th><th>Ausente</th><th>Confiança</th><th>Análise</th></tr></thead><tbody>
    {rows.map((r, i) => <tr key={`${r.present_in}-${r.index}-${i}`}><QsoCore row={r}/><td><Badge>{r.present_in}</Badge></td><td><Badge tone="warn">{r.missing_in}</Badge></td><td><Badge tone={r.confidence === 'HIGH' ? 'danger' : 'neutral'}>{r.confidence === 'HIGH' ? 'ALTA' : 'INCONCLUSIVA'}</Badge></td><td className="analysis-cell"><span>{r.reason}</span>{r.nearby?.length > 0 && <details><summary>Ver registro próximo</summary>{r.nearby.map((n, x) => <div key={x} className="nearby">{n.time || 'sem hora'}{n.time_diff_seconds != null ? ` · Δ ${n.time_diff_seconds}s` : ''} · {n.note}</div>)}</details>}</td></tr>)}
  </tbody></table></div>
}

function DuplicateTable({ rows }) {
  if (!rows.length) return <Empty text="Nenhuma duplicidade provável encontrada." />
  return <div className="table-wrap"><table><thead><tr><th>Fonte</th><th>Data</th><th>Call</th><th>Banda</th><th>Modo</th><th>Registros</th><th>Análise</th></tr></thead><tbody>
    {rows.map((r, i) => <tr key={`${r.source}-${r.call}-${r.date}-${i}`}><td><Badge>{r.source}</Badge></td><td className="mono">{r.date}</td><td><strong>{r.call}</strong></td><td>{r.band || '—'}</td><td>{r.mode || '—'}</td><td>{r.records.map((q, x) => <div key={x} className="mono compact">{q.time} · {q.freq_mhz ?? '—'} MHz · {q.rst_sent ?? '—'}/{q.rst_rcvd ?? '—'} · {q.grid ?? '—'}</div>)}</td><td className="analysis-cell">{r.reason}</td></tr>)}
  </tbody></table></div>
}

function FieldsTable({ rows, soft = false }) {
  if (!rows.length) return <Empty text={soft ? 'Nenhuma diferença tolerada relevante.' : 'Nenhuma divergência de campo relevante.'} />
  return <div className="table-wrap"><table><thead><tr><th>Data</th><th>UTC</th><th>Call</th><th>Banda</th><th>Campo</th><th>Fonte A</th><th>Fonte B</th><th>Análise</th></tr></thead><tbody>
    {rows.map((r, i) => <tr key={`${r.call}-${r.date}-${r.field}-${i}`}><td className="mono">{r.date}</td><td className="mono">{r.time || '—'}</td><td><strong>{r.call}</strong></td><td>{r.band || '—'}</td><td><Badge tone={r.severity === 'IMPORTANT' ? 'danger' : 'neutral'}>{r.field}</Badge></td><td><span className="source-label">{r.source_a}</span><code>{String(r.value_a ?? '∅')}</code></td><td><span className="source-label">{r.source_b}</span><code>{String(r.value_b ?? '∅')}</code></td><td className="analysis-cell">{r.reason}</td></tr>)}
  </tbody></table></div>
}

function Empty({ text }) { return <div className="empty"><div>✓</div><strong>{text}</strong></div> }
function csvCell(value) { const s = String(value ?? ''); return `"${s.replaceAll('"', '""')}"` }
function downloadCsv(rows, filename) {
  const headers = ['date','time','call','band','freq_mhz','mode','present_in','missing_in','confidence','reason']
  const csv = [headers.join(';'), ...rows.map(r => headers.map(h => csvCell(r[h])).join(';'))].join('\r\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url)
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [a, setA] = useState({ file: null, source: '', coverage: 'PARTIAL_EXPORT' })
  const [b, setB] = useState({ file: null, source: '', coverage: 'PARTIAL_EXPORT' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [tab, setTab] = useState('presence')

  useEffect(() => { api('/api/health').then(setHealth).catch(() => setHealth({ status: 'offline' })) }, [])
  const missingRows = useMemo(() => result ? [...result.missing_in_a, ...result.missing_in_b].sort((x,y) => `${y.date}${y.time}`.localeCompare(`${x.date}${x.time}`)) : [], [result])
  const ready = a.file && b.file && a.source.trim() && b.source.trim() && a.source.trim().toUpperCase() !== b.source.trim().toUpperCase()

  async function compare() {
    if (!ready) return
    setBusy(true); setError(''); setResult(null)
    try {
      const [contentA, contentB] = await Promise.all([a.file.text(), b.file.text()])
      const data = await api('/api/comparisons/adif', { method: 'POST', body: JSON.stringify({
        a: { content: contentA, source: a.source, filename: a.file.name, coverage: a.coverage },
        b: { content: contentB, source: b.source, filename: b.file.name, coverage: b.coverage },
      }) })
      setResult(data); setTab('presence')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  function reset() { setA({file:null,source:'',coverage:'PARTIAL_EXPORT'}); setB({file:null,source:'',coverage:'PARTIAL_EXPORT'}); setResult(null); setError(''); setTab('presence') }

  return <div className="app">
    <header className="topbar"><div className="brand"><div className="brand-mark">P2</div><div><b>PU2BRU QSO Manager</b><small>Comparador ADIF</small></div></div><div className="health"><span className={`dot ${health?.status === 'healthy' ? 'online' : ''}`}></span>{health?.status === 'healthy' ? 'Local · pronto' : 'Verificando…'}</div></header>
    <main>
      <section className="intro"><div><span className="kicker">COMEÇANDO PELO ESSENCIAL</span><h1>Compare dois logs.<br/><em>Veja somente o que importa.</em></h1><p>Selecione dois arquivos ADIF. O sistema pareia os QSOs com tolerância de horário, frequência e equivalência de modo, e separa faltantes, duplicidades e divergências de campos.</p></div>{result && <button className="secondary" onClick={reset}>Nova comparação</button>}</section>
      {!result && <>
        <div className="file-grid"><FileCard label="A" side={a} onChange={setA}/><div className="vs">×</div><FileCard label="B" side={b} onChange={setB}/></div>
        {a.source && b.source && a.source === b.source && <div className="alert">As duas fontes estão identificadas como <b>{a.source}</b>. Ajuste uma delas antes de comparar.</div>}
        {error && <div className="alert error">{error}</div>}
        <div className="compare-bar"><div><strong>Os arquivos não são alterados.</strong><span>A comparação é somente leitura e não envia QSOs para QRZ, WRL ou qualquer serviço externo.</span></div><button className="primary big" disabled={!ready || busy} onClick={compare}>{busy ? <><span className="spinner"></span>Analisando arquivos…</> : 'Comparar ADIs'}</button></div>
      </>}
      {result && <section className="results">
        <Summary result={result}/>
        {(result.source_a.parse_errors?.length > 0 || result.source_b.parse_errors?.length > 0) && <div className="alert warn">Alguns trechos dos arquivos geraram avisos de leitura. Os registros válidos foram analisados normalmente.</div>}
        <div className="tabs">
          <button className={tab === 'presence' ? 'active' : ''} onClick={() => setTab('presence')}>Presença <span>{fmt(missingRows.length)}</span></button>
          <button className={tab === 'duplicates' ? 'active' : ''} onClick={() => setTab('duplicates')}>Duplicidades <span>{fmt(result.probable_duplicates.length)}</span></button>
          <button className={tab === 'fields' ? 'active' : ''} onClick={() => setTab('fields')}>Campos <span>{fmt(result.field_differences.length)}</span></button>
          <button className={tab === 'tolerated' ? 'active' : ''} onClick={() => setTab('tolerated')}>Toleradas <span>{fmt(result.tolerated_differences.length)}</span></button>
          {tab === 'presence' && missingRows.length > 0 && <button className="export" onClick={() => downloadCsv(missingRows, `divergencias_${result.source_a.name}_${result.source_b.name}.csv`)}>Exportar CSV</button>}
        </div>
        <div className="tab-help">{tab === 'presence' && <>QSOs presentes em uma fonte sem uma correspondência 1:1 na outra. <b>FULL_EXPORT</b> permite classificar ausência com alta confiança.</>}{tab === 'duplicates' && <>Registros praticamente idênticos dentro da mesma fonte, separados por até 2 segundos. Eles não são tratados automaticamente como faltantes.</>}{tab === 'fields' && <>QSOs pareados que discordam em campos relevantes como RST, grid conflitante, estado ou modo.</>}{tab === 'tolerated' && <>Diferenças de segundos, precisão de grid ou frequência que ficaram dentro das regras de pareamento e não criaram falso “faltante”.</>}</div>
        {tab === 'presence' && <MissingTable rows={missingRows}/>} 
        {tab === 'duplicates' && <DuplicateTable rows={result.probable_duplicates}/>} 
        {tab === 'fields' && <FieldsTable rows={result.field_differences}/>} 
        {tab === 'tolerated' && <FieldsTable rows={result.tolerated_differences} soft/>}
      </section>}
    </main>
    <footer>PU2BRU · comparação local e somente leitura · nenhum upload externo</footer>
  </div>
}
