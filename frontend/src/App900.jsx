import React, { useEffect, useState } from 'react'
import { QSOManagerPage, ActivityPage } from './App600.jsx'
import { AdvancedCompare, QSLHub } from './App700.jsx'

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type':'application/json', ...(options.headers || {}) } })
  const text = await response.text()
  let payload = null
  if (text) { try { payload = JSON.parse(text) } catch { payload = text } }
  if (!response.ok) throw new Error(payload?.detail || payload?.message || payload || response.statusText)
  return payload
}
const fmt = n => Number(n || 0).toLocaleString('pt-BR')
const when = v => v ? new Date(v).toLocaleString('pt-BR') : 'Nunca'
const short = p => ({CLUBLOG:'CL',EQSL_INBOX:'eQ+',HRDLOG:'HL'}[p] || p)

const PRIMARY=[['home','Visão geral','⌂'],['log','Log','◎'],['review','Revisar','!'],['qsl','QSL','✓'],['sources','Fontes','◉']]
const SECONDARY=[['tools','Ferramentas','◇'],['activity','Histórico','◷'],['diagnostics','Diagnóstico','⊙']]
const FIELDS={
 QRZ:[['api_key','QRZ Logbook API Key','password','Use a chave do logbook, não a senha da conta.']],
 WRL:[['api_key','WRL Developer API Key','password','Integrations → Developer API'],['logbook_id','Logbook ID (opcional)','text','Deixe vazio para o padrão.']],
 CLUBLOG:[['email','E-mail','email','Conta do Club Log'],['app_password','Application Password','password','Use Application Password.'],['callsign','Indicativo','text','Ex.: PU2BRU'],['api_key','API Key de escrita','password','Necessária para publicar/excluir.']],
 EQSL:[['username','Indicativo / Username','text','Conta do eQSL'],['password','Senha','password','Armazenada apenas localmente.'],['qth_nickname','QTH Nickname (opcional)','text','Use se houver mais de um QTH.']],
 LOTW:[['login','Login LoTW','text','Conta ARRL LoTW'],['password','Senha LoTW','password','Somente leitura de confirmações.']],
 HRDLOG:[['callsign','Indicativo','text','Indicativo associado ao HRDLog.net'],['upload_code','Upload Code','password','Código de upload do HRDLog.net.']],
}
function Btn({children,kind='primary',small=false,...props}){return <button className={['v9-btn',kind,small?'small':''].join(' ')} {...props}>{children}</button>}
function Badge({children,tone='neutral'}){return <span className={'v9-badge '+tone}>{children}</span>}
function Notice({children,tone='info'}){return <div className={'v9-notice '+tone}>{children}</div>}
function Empty({children}){return <div className="v9-empty">{children||'Nada para mostrar.'}</div>}
function Surface({title,subtitle,action,children}){return <section className="v9-surface"><header><div><h3>{title}</h3>{subtitle&&<p>{subtitle}</p>}</div>{action}</header>{children}</section>}

function ProviderModal({provider,onClose,onSaved}){
 const key=provider.provider==='EQSL_INBOX'?'EQSL':provider.provider
 const [values,setValues]=useState(provider.credentials||{}),[busy,setBusy]=useState(false),[msg,setMsg]=useState('')
 async function save(test){
  setBusy(true);setMsg('')
  try{
   await api('/api/v8/connections/'+key,{method:'PUT',body:JSON.stringify({values})})
   if(test){const target=provider.provider==='EQSL_INBOX'?'EQSL_INBOX':key;const r=await api('/api/v8/connections/'+target+'/test',{method:'POST',body:'{}'});setMsg(r.message||r.status||'Conexão validada.')}
   else setMsg('Configuração salva.')
   await onSaved()
  }catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}
 }
 return <div className="v9-modal-bg" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><div className="v9-modal">
  <div className="v9-modal-head"><div><span>CONEXÃO</span><h2>{provider.label}</h2></div><button onClick={onClose}>×</button></div>
  {provider.provider==='EQSL_INBOX'&&<Notice>O Inbox usa a mesma credencial do eQSL OutBox.</Notice>}
  <div className="v9-fields">{(FIELDS[key]||[]).map(([name,label,type,help])=><label key={name}><span>{label}</span><input type={type} value={values[name]||''} onChange={e=>setValues(v=>({...v,[name]:e.target.value}))}/><small>{help}</small></label>)}</div>
  {msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}
  <div className="v9-modal-actions"><Btn kind="ghost" onClick={onClose}>Fechar</Btn><Btn kind="ghost" disabled={busy} onClick={()=>save(true)}>Salvar e testar</Btn><Btn disabled={busy} onClick={()=>save(false)}>Salvar</Btn></div>
 </div></div>
}

function Home({status,dashboard,diagnostics,go,syncAll,busy}){
 const sum=dashboard?.summary||{},counts=dashboard?.issues?.counts||{},sources=status?.providers||[]
 const pending=(counts.missing||0)+(counts.differences||0)+(counts.duplicates||0)
 const next=pending?['Revisar pendências',fmt(pending)+' item(ns) merecem decisão.','review']:!sources.find(x=>x.provider==='QRZ')?.snapshot?.records?['Conectar o QRZ','O QRZ é a referência preferencial.','sources']:['Tudo em ordem','Seu log não tem pendências prioritárias.','log']
 return <>
  <section className="v9-hero"><div><span className="v9-eyebrow">CENTRAL DE OPERAÇÃO</span><h1>Seu log, reconciliado e confiável.</h1><p>Uma única jornada para manter todas as fontes alinhadas sem esconder diferenças nem sobrescrever confirmações.</p></div><div><Btn disabled={busy} onClick={syncAll}>{busy?'Atualizando…':'Atualizar fontes'}</Btn><Btn kind="ghost" onClick={()=>go('log')}>Abrir log</Btn></div></section>
  <div className="v9-kpis"><button onClick={()=>go('log')}><span>QSOs consolidados</span><b>{fmt(sum.logical_qsos)}</b><small>{fmt(sum.multi_source)} multifonte</small></button><button onClick={()=>go('review')}><span>Pendências</span><b>{fmt(pending)}</b><small>{fmt(counts.missing)} ausências · {fmt(counts.differences)} diferenças</small></button><button onClick={()=>go('qsl')}><span>QSL</span><b>{fmt(counts.qsl)}</b><small>eQSL + LoTW</small></button><button onClick={()=>go('sources')}><span>Fontes</span><b>{sources.filter(x=>x.configured||x.snapshot?.records).length}/{sources.length}</b><small>conectadas ou carregadas</small></button></div>
  <div className="v9-home-grid"><Surface title="Próxima melhor ação" subtitle="O sistema prioriza o que muda seu log."><button className="v9-next-action" onClick={()=>go(next[2])}><div><b>{next[0]}</b><p>{next[1]}</p></div><span>→</span></button></Surface><Surface title="Saúde do aplicativo" subtitle="Verificações do runtime instalado." action={<Badge tone={diagnostics?.ok?'ok':'warn'}>{diagnostics?.ok?'operacional':'atenção'}</Badge>}><div className="v9-health-list">{Object.entries(diagnostics?.checks||{}).map(([k,v])=><div key={k}><span className={v?'ok':'bad'}/><b>{k.replaceAll('_',' ')}</b><em>{v?'OK':'falha'}</em></div>)}</div><button className="v9-link" onClick={()=>go('diagnostics')}>Ver diagnóstico →</button></Surface></div>
  <Surface title="Fontes" subtitle="Estado e última atualização."><div className="v9-source-row">{sources.map(s=><button key={s.provider} onClick={()=>go('sources')}><i className={s.configured||s.snapshot?.records?'ok':''}>{short(s.provider)}</i><span><b>{s.label}</b><small>{s.snapshot?.records?fmt(s.snapshot.records)+' registros':s.configured?'conectado · sem snapshot':'não configurado'}</small></span><em>{s.snapshot?.downloaded_at?when(s.snapshot.downloaded_at):'—'}</em></button>)}</div></Surface>
 </>
}

function ReviewPage({issues,go}){
 const [filter,setFilter]=useState('ALL'),items=issues?.items||[],counts=issues?.counts||{},shown=filter==='ALL'?items:items.filter(x=>x.type===filter)
 return <><div className="v9-page-head"><div><span className="v9-eyebrow">RECONCILIAÇÃO</span><h1>Revise apenas o que exige decisão.</h1><p>Ausências, diferenças, duplicidades e QSL em uma única caixa de entrada.</p></div><Btn kind="ghost" onClick={()=>go('log')}>Abrir QSO Manager</Btn></div><div className="v9-chips">{[['ALL','Tudo',issues?.total],['MISSING','Ausências',counts.missing],['DIFFERENCE','Diferenças',counts.differences],['DUPLICATE','Duplicidades',counts.duplicates],['QSL','QSL',counts.qsl]].map(x=><button key={x[0]} className={filter===x[0]?'active':''} onClick={()=>setFilter(x[0])}>{x[1]} <b>{fmt(x[2])}</b></button>)}</div>{!shown.length?<Empty>Nenhuma pendência nesse grupo.</Empty>:<div className="v9-inbox">{shown.map((x,i)=><article key={i}><div className={'v9-issue-icon '+x.type.toLowerCase()}>{x.type==='QSL'?'✓':x.type==='MISSING'?'−':'!'}</div><div><h3>{x.call} <small>{x.band} · {x.mode}</small></h3><p>{x.date} {x.time?.slice(0,5)} · {x.message}</p><div>{(x.sources||[]).map(s=><Badge key={s}>{short(s)}</Badge>)}</div></div></article>)}</div>}</>
}

function QSLPage({qsl,manual}){
 const s=qsl?.summary||{}
 return <><div className="v9-page-head"><div><span className="v9-eyebrow">CONFIRMAÇÕES</span><h1>QSL sem confundir contato com confirmação.</h1><p>eQSL Inbox e LoTW entram como evidências independentes. QSO_DATE nunca vira data de recebimento.</p></div><Btn kind="ghost" onClick={manual}>Analisar arquivos</Btn></div>{!qsl?.ready?<Empty>Sincronize QRZ, eQSL Inbox e/ou LoTW.</Empty>:<><div className="v9-kpis compact"><div><span>Confirmados</span><b>{fmt(s.matched_confirmation_groups)}</b></div><div><span>Propostas</span><b>{fmt(s.actionable_proposals)}</b></div><div><span>Sem par</span><b>{fmt(s.unmatched_evidence)}</b></div><div><span>Conflitos</span><b>{fmt(s.date_conflicts)}</b></div></div><Surface title="Confirmações encontradas" subtitle="Nada é sobrescrito silenciosamente.">{!(qsl.proposals||[]).length?<Empty>Nenhuma confirmação nova.</Empty>:<div className="v9-qsl-list">{qsl.proposals.slice(0,500).map((p,i)=><article key={i}><div><h3>{p.qso?.call}</h3><p>{p.qso?.date} · {p.qso?.band} · {p.qso?.mode}</p></div><Badge tone="ok">{p.service}</Badge><div><b>{Object.entries(p.changes||{}).map(([k,v])=>k+'='+v).join(' · ')}</b><small>{p.reason}</small></div></article>)}</div>}</Surface></>}</>
}

function Sources({status,busy,configure,syncOne,importSource,pushHrd,syncAll}){
 const providers=status?.providers||[],logs=providers.filter(x=>x.comparison_role!=='qsl_evidence'),qsl=providers.filter(x=>x.comparison_role==='qsl_evidence')
 function Card({s}){const file=['HRD','HRDLOG'].includes(s.provider),sync=s.capabilities?.read&&!file;return <article className="v9-source-card"><header><div className="v9-source-brand"><i className={s.configured||s.snapshot?.records?'ok':''}>{short(s.provider)}</i><div><h3>{s.label}</h3><p>{s.comparison_role==='qsl_evidence'?'evidência de QSL':s.source_kind==='local_adif'?'fonte por ADIF':s.source_kind==='hybrid_bootstrap_upload'?'ADIF + envio online':'fonte online'}</p></div></div><Badge tone={s.configured||s.snapshot?.records?'ok':'neutral'}>{s.configured||s.snapshot?.records?'pronto':'configurar'}</Badge></header><p className="v9-source-note">{s.note}</p><div className="v9-source-meta"><div><span>Registros</span><b>{fmt(s.snapshot?.records)}</b></div><div><span>Atualização</span><b>{s.snapshot?.downloaded_at?when(s.snapshot.downloaded_at):'Nunca'}</b></div></div><div className="v9-capabilities">{Object.entries(s.capabilities||{}).map(([k,v])=><span key={k} className={v?'yes':'no'}>{v?'✓':'—'} {({read:'ler',add:'incluir',update:'editar',delete:'excluir'})[k]}</span>)}</div><div className="v9-card-actions">{s.provider!=='HRD'&&<Btn kind="ghost" small onClick={()=>configure(s)}>{s.configured?'Conexão':'Configurar'}</Btn>}{file&&<label className="v9-file-button">Importar/Reconciliar ADIF<input type="file" accept=".adi,.adif,.txt" onChange={e=>importSource(s.provider,e.target.files?.[0])}/></label>}{sync&&<Btn small disabled={busy||!s.configured} onClick={()=>syncOne(s.provider)}>Atualizar</Btn>}{s.provider==='HRDLOG'&&<Btn small disabled={busy||!s.configured||!s.snapshot?.records} onClick={pushHrd}>Enviar ausentes</Btn>}</div></article>}
 return <><div className="v9-page-head"><div><span className="v9-eyebrow">FONTES</span><h1>Conecte uma vez. Reconcilie sempre.</h1><p>Logs e evidências de QSL separados por papel, mas unidos na mesma jornada.</p></div><Btn disabled={busy} onClick={syncAll}>{busy?'Atualizando…':'Atualizar tudo'}</Btn></div><h2 className="v9-section-title">Logs comparáveis</h2><div className="v9-source-grid">{logs.map(s=><Card key={s.provider} s={s}/>)}</div><h2 className="v9-section-title">Confirmações</h2><div className="v9-source-grid">{qsl.map(s=><Card key={s.provider} s={s}/>)}</div></>
}

function Tools({initial}){
 const [tool,setTool]=useState(initial||'compare')
 return <><div className="v9-page-head"><div><span className="v9-eyebrow">FERRAMENTAS</span><h1>Recursos avançados, fora da jornada principal.</h1><p>Audite arquivos e evidências quando as conexões automáticas não forem suficientes.</p></div></div><div className="v9-chips"><button className={tool==='compare'?'active':''} onClick={()=>setTool('compare')}>Comparar múltiplos ADIF</button><button className={tool==='qsl'?'active':''} onClick={()=>setTool('qsl')}>QSL por arquivos</button></div><div className="v9-legacy-module">{tool==='compare'?<AdvancedCompare/>:<QSLHub/>}</div></>
}

function Diagnostics({data,reload}){
 const [log,setLog]=useState(null)
 async function getLog(){try{setLog(await api('/api/diagnostics/launcher-log'))}catch(e){setLog({error:e.message,lines:[]})}}
 return <><div className="v9-page-head"><div><span className="v9-eyebrow">DIAGNÓSTICO</span><h1>Sem falhas silenciosas.</h1><p>Banco, frontend, diretórios e inicialização do Windows verificados em tempo real.</p></div><Btn kind="ghost" onClick={reload}>Executar novamente</Btn></div><div className="v9-diagnostic-grid">{Object.entries(data?.checks||{}).map(([k,v])=><div key={k}><span className={v?'ok':'bad'}>{v?'✓':'!'}</span><div><b>{k.replaceAll('_',' ')}</b><small>{v?'Operacional':'Requer atenção'}</small></div></div>)}</div><Surface title="Runtime"><div className="v9-runtime">{Object.entries(data?.runtime||{}).map(([k,v])=><div key={k}><span>{k}</span><code>{String(v)}</code></div>)}</div><div className="v9-runtime">{Object.entries(data?.paths||{}).map(([k,v])=><div key={k}><span>{k}</span><code>{String(v)}</code></div>)}</div></Surface><Surface title="Log de inicialização" action={<Btn kind="ghost" small onClick={getLog}>Carregar log</Btn>}>{!log?<Empty>Carregue o log para diagnosticar o atalho do Windows.</Empty>:log.error?<Notice tone="error">{log.error}</Notice>:<pre className="v9-log">{(log.lines||[]).join('\n')||'Nenhum registro.'}</pre>}</Surface></>
}

export default function App900(){
 const [view,setView]=useState('home'),[status,setStatus]=useState(null),[dashboard,setDashboard]=useState(null),[workspace,setWorkspace]=useState(null),[issues,setIssues]=useState(null),[qsl,setQsl]=useState(null),[diagnostics,setDiagnostics]=useState(null),[configure,setConfigure]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[managerKey,setManagerKey]=useState(0),[toolInitial,setToolInitial]=useState('compare')
 async function refresh(){
  const r=await Promise.all([api('/api/v8/status'),api('/api/v8/dashboard'),api('/api/qso-manager/options'),api('/api/v8/issues?limit=1000'),api('/api/v8/qsl'),api('/api/diagnostics')])
  setStatus(r[0]);setDashboard(r[1]);setWorkspace(r[2]);setIssues(r[3]);setQsl(r[4]);setDiagnostics(r[5]);setManagerKey(x=>x+1)
 }
 useEffect(()=>{refresh().catch(e=>setMessage('Erro: '+e.message))},[])
 async function syncAll(){setBusy(true);setMessage('Atualizando fontes online…');try{const r=await api('/api/v8/sync-all',{method:'POST',body:'{}'});await refresh();const f=(r.results||[]).filter(x=>!x.ok&&!x.skipped);setMessage(f.length?'Concluído com '+f.length+' falha(s).':'Fontes atualizadas e reconciliação recalculada.')}catch(e){setMessage('Erro: '+e.message)}finally{setBusy(false)}}
 async function syncOne(p){setBusy(true);try{const r=await api('/api/v8/sync/'+p,{method:'POST',body:'{}'});await refresh();setMessage(p+': '+fmt(r.records)+' registro(s) atualizados.')}catch(e){setMessage('Erro: '+e.message)}finally{setBusy(false)}}
 async function importSource(p,file){if(!file)return;setBusy(true);try{const content=await file.text(),endpoint=p==='HRDLOG'?'/api/v8/hrdlog/bootstrap':'/api/cloud/snapshots/HRD/adif';const r=await api(endpoint,{method:'PUT',body:JSON.stringify({content,filename:file.name})});await refresh();setMessage(p+': '+fmt(r.records)+' QSO(s) importados.')}catch(e){setMessage('Erro: '+e.message)}finally{setBusy(false)}}
 async function pushHrd(){setBusy(true);try{const plan=await api('/api/v8/hrdlog/plan?limit=500');if(!plan.safe_missing){setMessage('HRDLog já está alinhado.');return}if(!window.confirm('Enviar '+plan.candidates.length+' QSO(s) seguros ao HRDLog.net?'))return;const r=await api('/api/v8/hrdlog/push',{method:'POST',body:JSON.stringify({confirm:true,limit:500})});await refresh();setMessage('HRDLog: '+fmt(r.sent_or_already_remote)+' enviado(s)/confirmado(s).')}catch(e){setMessage('Erro: '+e.message)}finally{setBusy(false)}}
 function go(v){setView(v);window.scrollTo({top:0,behavior:'smooth'})}
 function manualQsl(){setToolInitial('qsl');go('tools')}
 const title=[...PRIMARY,...SECONDARY].find(x=>x[0]===view)?.[1]||'QSO Manager',pending=(issues?.counts?.missing||0)+(issues?.counts?.differences||0)+(issues?.counts?.duplicates||0)
 return <div className="v9-app"><aside className="v9-sidebar"><div className="v9-brand"><div>PU</div><span><b>QSO Manager</b><small>PU2BRU · v9.0</small></span></div><nav>{PRIMARY.map(([k,l,i])=><button key={k} className={view===k?'active':''} onClick={()=>go(k)}><i>{i}</i><span>{l}</span>{k==='review'&&pending>0&&<em>{pending>99?'99+':pending}</em>}</button>)}</nav><div className="v9-nav-label">Mais</div><nav>{SECONDARY.map(([k,l,i])=><button key={k} className={view===k?'active':''} onClick={()=>go(k)}><i>{i}</i><span>{l}</span></button>)}</nav><div className="v9-sidebar-foot"><span className={diagnostics?.ok?'ok':'warn'}/><div><b>{diagnostics?.ok?'Sistema operacional':'Verificar sistema'}</b><small>{diagnostics?.runtime?.packaged?'Windows instalado':'desenvolvimento'}</small></div></div></aside><div className="v9-workspace"><header className="v9-topbar"><div><span className="v9-eyebrow">PU2BRU QSO MANAGER</span><h2>{title}</h2></div><div className="v9-top-actions"><div className="v9-mini-sources">{(status?.providers||[]).filter(x=>['QRZ','WRL','CLUBLOG','EQSL','LOTW'].includes(x.provider)).map(s=><span key={s.provider} className={s.configured?'on':''}>{short(s.provider)}</span>)}</div><Btn small disabled={busy} onClick={syncAll}>↻ Atualizar</Btn></div></header><main className="v9-content">{message&&<Notice tone={message.startsWith('Erro')?'error':'info'}><div className="v9-message-row"><span>{message}</span><button onClick={()=>setMessage('')}>×</button></div></Notice>}{view==='home'&&<Home status={status} dashboard={dashboard} diagnostics={diagnostics} go={go} syncAll={syncAll} busy={busy}/>} {view==='log'&&<QSOManagerPage key={managerKey} status={status} workspace={workspace} refresh={refresh}/>} {view==='review'&&<ReviewPage issues={issues} go={go}/>} {view==='qsl'&&<QSLPage qsl={qsl} manual={manualQsl}/>} {view==='sources'&&<Sources status={status} busy={busy} configure={setConfigure} syncOne={syncOne} importSource={importSource} pushHrd={pushHrd} syncAll={syncAll}/>} {view==='tools'&&<Tools key={toolInitial} initial={toolInitial}/>} {view==='activity'&&<ActivityPage/>} {view==='diagnostics'&&<Diagnostics data={diagnostics} reload={()=>api('/api/diagnostics').then(setDiagnostics).catch(e=>setMessage('Erro: '+e.message))}/>}</main></div><nav className="v9-mobile-nav">{PRIMARY.map(([k,l,i])=><button key={k} className={view===k?'active':''} onClick={()=>go(k)}><i>{i}</i><span>{l}</span>{k==='review'&&pending>0&&<em>{pending>99?'99+':pending}</em>}</button>)}</nav>{configure&&<ProviderModal provider={configure} onClose={()=>setConfigure(null)} onSaved={async()=>{await refresh();setConfigure(null)}}/>}</div>
}
