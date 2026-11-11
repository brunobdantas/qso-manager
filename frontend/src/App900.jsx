import React, { useEffect, useMemo, useState } from 'react'

const VERSION = '1.1.4'
const NAV = [
  ['overview','Visão geral','⌂'],
  ['log','Log','◎'],
  ['inbox','Pendências','!'],
  ['integrity','Integridade','◈'],
  ['qsl','QSL','✓'],
  ['sources','Fontes','◉'],
  ['tools','Ferramentas','⌘'],
]
const PROVIDER_FIELDS = {
  QRZ:[['api_key','QRZ Logbook API Key','password','Chave do logbook, não a senha da conta.']],
  WRL:[['api_key','WRL Developer API Key','password','Integrations → Developer API.'],['logbook_id','Logbook ID (opcional)','text','Deixe vazio para o logbook padrão.']],
  CLUBLOG:[['email','E-mail','email','Conta Club Log.'],['app_password','Application Password','password','Prefira uma Application Password.'],['callsign','Indicativo','text','Ex.: PU2BRU'],['api_key','API Key de escrita','password','Necessária para publicar/excluir.']],
  EQSL:[['username','Indicativo / Username','text','Ex.: PU2BRU'],['password','Senha','password','Armazenada somente no computador.'],['qth_nickname','QTH Nickname (opcional)','text','Use quando houver mais de um QTH.']],
  LOTW:[['login','Username da conta LoTW','text','Use o username da conta LoTW. Normalmente é o indicativo, mas pode ser diferente.'],['password','Senha LoTW','password','Use a senha da conta LoTW; não é a senha do certificado TQSL. Armazenada somente no computador.']],
  HRDLOG:[['callsign','Indicativo','text','Ex.: PU2BRU'],['upload_code','Upload Code','password','Código de upload do HRDLog.net.']],
}
const short = p => ({CLUBLOG:'CL',EQSL_INBOX:'eQ+',HRDLOG:'HL',HRD:'HRD'}[p] || p)
const providerLabel = p => ({QRZ:'QRZ',WRL:'World Radio League',CLUBLOG:'Club Log',EQSL:'eQSL OutBox',EQSL_INBOX:'eQSL Inbox',LOTW:'LoTW',HRDLOG:'HRDLog.net',HRD:'Ham Radio Deluxe'}[p] || p)
const sourceKindLabel = value => ({remote_api:'API remota',confirmation_api:'API de confirmações',hybrid_bootstrap_upload:'ADIF + escrita online',local_adif:'ADIF local'}[value] || value)
const fmt = n => Number(n||0).toLocaleString('pt-BR')
const words = (n,singular,plural=singular+'s') => `${fmt(n)} ${Number(n)===1?singular:plural}`
const dt = v => v ? new Date(v).toLocaleString('pt-BR') : 'Nunca'
const cls = (...x) => x.filter(Boolean).join(' ')

async function api(path, options={}) {
  const response = await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}})
  const text = await response.text(); let payload=null
  if(text){try{payload=JSON.parse(text)}catch{payload=text}}
  if(!response.ok){const detail=payload?.detail||payload?.message||payload||`${response.status} ${response.statusText}`;throw new Error(typeof detail==='string'?detail:JSON.stringify(detail))}
  return payload
}
function downloadBlob(name, content, type='text/plain;charset=utf-8'){
  const blob=content instanceof Blob?content:new Blob([content],{type});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url)
}
function Button({children,kind='primary',small=false,...props}){return <button className={cls('u-btn','u-'+kind,small&&'small')} {...props}>{children}</button>}
function Badge({children,tone='neutral',...props}){return <span className={'u-badge '+tone} {...props}>{children}</span>}
function Empty({title='Nada por aqui',children}){return <div className="u-empty"><b>{title}</b>{children&&<p>{children}</p>}</div>}
function Notice({children,tone='info'}){return <div className={'u-notice '+tone}>{children}</div>}
function PageHead({eyebrow,title,subtitle,action}){return <div className="u-pagehead"><div><small>{eyebrow}</small><h1>{title}</h1>{subtitle&&<p>{subtitle}</p>}</div>{action}</div>}
function Card({title,subtitle,action,children,className=''}){return <section className={'u-card '+className}><header><div><h3>{title}</h3>{subtitle&&<p>{subtitle}</p>}</div>{action}</header>{children}</section>}


function SyncProgress({job}){
  if(!job)return null
  const rows=Object.values(job.providers||{}).filter(x=>x.configured)
  const finished=['completed','completed_with_errors'].includes(job.status)
  const statusLabel=x=>({queued:'na fila',running:'baixando',success:'concluído',failed:'falhou',skipped:'ignorado'}[x]||x)
  return <section className="u-sync-progress"><div className="u-sync-progress-head"><div><b>{finished?'Atualização concluída':'Atualizando fontes em paralelo'}</b><small>{job.completed||0} de {job.total||0} fontes · até {job.parallelism||0} downloads simultâneos</small></div><strong>{job.progress||0}%</strong></div><div className="u-progress-track"><i style={{width:(job.progress||0)+'%'}}/></div><div className="u-sync-provider-list">{rows.map(x=><div key={x.provider} className={'state-'+x.status}><span className="u-sync-state"/><b>{x.label||x.provider}</b><small>{x.status==='success'?fmt(x.records)+' registros':x.status==='failed'?(x.error||'falha'):(x.status==='running'&&x.loaded_records>0?fmt(x.loaded_records)+' registros · '+fmt(x.pages)+' páginas':statusLabel(x.status))}</small>{x.duration_ms!=null&&x.status==='success'&&<em>{(x.duration_ms/1000).toFixed(1)}s</em>}</div>)}</div>{finished&&job.failed>0&&<Notice tone="warn">{job.failed} fonte(s) falharam. As demais foram preservadas e atualizadas normalmente.</Notice>}</section>
}

function ConnectionModal({source,onClose,onChanged}){
  const key=source.provider==='EQSL_INBOX'?'EQSL':source.provider
  const [values,setValues]=useState(source.credentials||{}),[busy,setBusy]=useState(false),[msg,setMsg]=useState('')
  async function save(test){setBusy(true);setMsg('');try{await api('/api/product/connections/'+key,{method:'PUT',body:JSON.stringify({values})});if(test){const r=await api('/api/product/connections/'+source.provider+'/test',{method:'POST',body:'{}'});setMsg(r.message||r.status||`Conexão validada${r.records!=null?` · ${fmt(r.records)} registros`:''}.`)}else setMsg('Configuração salva.');await onChanged()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  async function disconnect(){if(!window.confirm(`Desconectar ${source.label}? O snapshot local será preservado.`))return;setBusy(true);try{await api('/api/product/connections/'+key,{method:'DELETE'});await onChanged();onClose()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  return <div className="u-modal-bg" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><div className="u-modal" role="dialog" aria-modal="true" aria-label={`Conexão segura ${source.label}`}><div className="u-modal-title"><div><small>CONEXÃO SEGURA</small><h2>{source.label}</h2></div><button aria-label="Fechar configuração" onClick={onClose}>×</button></div>{source.provider==='EQSL_INBOX'&&<Notice>O Inbox compartilha a conta configurada no eQSL OutBox.</Notice>}<div className="u-fields">{(PROVIDER_FIELDS[key]||[]).map(([name,label,type,help])=><label key={name}><span>{label}</span><input type={type} value={values[name]||''} placeholder={source.credentials?.[name]||''} onChange={e=>setValues(v=>({...v,[name]:e.target.value}))}/><small>{help}</small></label>)}</div>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}<div className="u-modal-actions"><div>{source.configured&&<Button kind="danger" disabled={busy} onClick={disconnect}>Desconectar</Button>}</div><div><Button kind="secondary" disabled={busy} onClick={()=>save(false)}>Salvar</Button><Button disabled={busy} onClick={()=>save(true)}>{busy?'Validando…':'Salvar e testar'}</Button></div></div></div></div>
}

function QsoDrawer({logicalId,onClose}){
  const [data,setData]=useState(null),[msg,setMsg]=useState('')
  useEffect(()=>{let alive=true;api('/api/product/log/'+encodeURIComponent(logicalId)).then(x=>alive&&setData(x)).catch(e=>alive&&setMsg(e.message));return()=>{alive=false}},[logicalId])
  const stale=new Set(data?.stale_missing_in||[]),actionable=(data?.missing_in||[]).filter(p=>!stale.has(p))
  return <div className="u-drawer-bg" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><aside className="u-drawer" role="dialog" aria-modal="true" aria-label="Detalhe do QSO"><div className="u-drawer-head"><div><small>DETALHE DO QSO</small><h2>{data?.call||'Carregando…'}</h2>{data&&<p>{data.date} {data.time} · {data.band} · {data.mode}</p>}</div><button aria-label="Fechar detalhe do QSO" onClick={onClose}>×</button></div>{msg&&<Notice tone="error">{msg}</Notice>}{data&&<><div className="u-detail-kpis"><div><span>Fontes</span><b>{data.providers?.length||0}</b></div><div><span>Ausências acionáveis</span><b>{actionable.length}</b></div><div><span>Diferenças</span><b>{data.difference_fields?.length||0}</b></div></div><div className="u-badges">{data.providers?.map(p=><Badge key={p} title={providerLabel(p)} tone={p==='QRZ'?'truth':'ok'}>{short(p)}</Badge>)}{actionable.map(p=><Badge key={p} title={`Ausente em ${providerLabel(p)}`} tone="warn">− {short(p)}</Badge>)}{[...stale].map(p=><Badge key={p} title={`${providerLabel(p)} precisa ser atualizado antes de afirmar ausência`}>↻ {short(p)}</Badge>)}</div>{stale.size>0&&<Notice>Ausências em snapshot desatualizado ficam aguardando nova sincronização e não entram como pendência acionável.</Notice>}{data.difference_fields?.length>0&&<><Notice tone="warn">Campos divergentes: {data.difference_fields.join(', ')}</Notice><div className="u-diff-table">{data.difference_fields.map(field=><section key={field}><b>{field}</b><div>{Object.entries(data.source_records||{}).map(([provider,payload])=><p key={provider}><Badge tone={provider==='QRZ'?'truth':'neutral'}>{provider}</Badge><code>{String(payload.record?.[field]??'—')}</code></p>)}</div></section>)}</div></>}<details className="u-raw-details"><summary>Ver todos os campos brutos por fonte</summary><div className="u-records">{Object.entries(data.source_records||{}).map(([provider,payload])=><section key={provider}><header><Badge tone={provider==='QRZ'?'truth':'neutral'}>{provider}</Badge><span>{Object.keys(payload.record||{}).length} campos</span></header><div>{Object.entries(payload.record||{}).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=><p key={k}><span>{k}</span><code>{String(v)}</code></p>)}</div></section>)}</div></details></>}</aside></div>
}

function Overview({boot,navigate,syncAll,busy,syncJob}){
  const summary=boot?.dashboard?.summary||{}, counts=boot?.issues?.counts||{}, providers=boot?.status?.providers||[]
  const scoped=providers.filter(p=>p.participates!==false),available=scoped.filter(p=>p.configured||p.snapshot_loaded).length
  return <><div className="u-hero"><div><small>QRZ · REFERÊNCIA OPERACIONAL</small><h1>{fmt(summary.reference_qsos)} QSOs no QRZ</h1><p>{fmt(summary.observed_logical_qsos)} contatos lógicos observados nas fontes ativas; {fmt(summary.external_observations)} ainda não têm pareamento seguro no QRZ.</p><div className="u-hero-actions"><Button onClick={()=>navigate('inbox')}>Revisar pendências</Button><Button kind="secondary" disabled={busy} onClick={syncAll}>{busy?'Atualizando…':'Atualizar tudo'}</Button></div></div><div className="u-health"><span>Fontes ativas</span><b>{available}/{scoped.length}</b><small>com conexão ou dados carregados</small><i className={available?'ok':''}/></div></div>{syncJob&&<SyncProgress job={syncJob}/>}<div className="u-metrics"><button onClick={()=>navigate('log')}><span>QSOs multifonte</span><b>{fmt(summary.multi_source)}</b><small>presentes em mais de uma fonte</small></button><button onClick={()=>navigate('inbox')}><span>Ausências acionáveis</span><b>{fmt(counts.missing)}</b><small>snapshots desatualizados ficam em espera</small></button><button onClick={()=>navigate('inbox')}><span>Divergências por QSO</span><b>{fmt(counts.differences)}</b><small>sem ruído apenas informativo</small></button><button onClick={()=>navigate('qsl')}><span>Com evidência QSL</span><b>{fmt(counts.qsl)}</b><small>não entram como pendência</small></button></div><div className="u-two"><Card title="Próximas ações" subtitle="O sistema prioriza decisões, não telas."><div className="u-actions-list"><button onClick={()=>navigate('inbox')}><i>01</i><span><b>Resolver o que está divergente</b><small>{words((boot?.issues?.total)||0,'QSO')} na caixa de entrada</small></span><em>›</em></button><button onClick={()=>navigate('sources')}><i>02</i><span><b>Manter as fontes frescas</b><small>Veja autenticação, cobertura e última atualização</small></span><em>›</em></button><button onClick={()=>navigate('tools')}><i>03</i><span><b>Auditar e proteger o log</b><small>Comparação ADIF, exportação, backup e atividade</small></span><em>›</em></button></div></Card><Card title="Cobertura das fontes" subtitle="Conexão, dados carregados e escopo são estados independentes."><div className="u-source-mini">{providers.map(p=><button key={p.provider} onClick={()=>navigate('sources')}><i className={p.configured||p.snapshot_loaded?'ok':''}>{short(p.provider)}</i><span><b>{p.label}</b><small>{p.participates===false?'fora do escopo':p.snapshot_loaded?`${fmt(p.snapshot?.records)} registros${p.snapshot_state==='STALE'?' · desatualizado':''}`:p.configured?'conectada, sem dados':'não configurada'}</small></span></button>)}</div></Card></div></>
}


function BulkActionDialog({ids,workspace,onClose,onDone}){
  const [action,setAction]=useState('PUBLISH'),[target,setTarget]=useState('WRL')
  const [field,setField]=useState('COMMENT'),[value,setValue]=useState('')
  const [plan,setPlan]=useState(null),[job,setJob]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[deleteText,setDeleteText]=useState(''),[remoteOptions,setRemoteOptions]=useState(null)
  const labels={PUBLISH:'Adicionar ausentes',UPDATE:'Editar registros',DELETE:'Excluir registros'}
  const activeWorkspace=workspace||remoteOptions||{}
  const capability=activeWorkspace.capability_matrix||{}
  const actionKey={PUBLISH:'add',UPDATE:'update',DELETE:'delete'}[action]
  const targetOptions=(activeWorkspace.write_targets||['QRZ','WRL','CLUBLOG','EQSL','HRDLOG']).filter(p=>capability[p]?.[actionKey])
  const targetCaps=capability[target]||{}
  const allowedFields=targetCaps.update_fields||[]
  const statusLabel=s=>({unsupported:'operação indisponível',not_present:'não existe no destino',already_present:'já existe no destino',duplicate_review_required:'duplicidade exige revisão',stable_remote_id_missing:'ID remoto ausente',no_changes:'informe uma alteração',provider_batch_limit:'limite seguro da plataforma'}[s]||String(s||'').replace('unsupported_fields:','campos não suportados: '))
  const payload=()=>({action,logical_ids:ids,target,changes:action==='UPDATE'?{[field]:value}:{}})
  useEffect(()=>{if(!workspace)api('/api/qso-manager/options').then(setRemoteOptions).catch(e=>setMessage('Erro: '+e.message))},[workspace])
  useEffect(()=>{
    if(targetOptions.length&&!targetOptions.includes(target)){setTarget(targetOptions[0]);setPlan(null)}
  },[action,targetOptions.join('|')])
  useEffect(()=>{
    if(action==='UPDATE'&&allowedFields.length&&!allowedFields.includes(field)){setField(allowedFields[0]);setPlan(null)}
  },[target,action,allowedFields.join('|')])
  async function preview(){
    setBusy(true);setPlan(null);setMessage('')
    try{setPlan(await api('/api/qso-manager/bulk/preview',{method:'POST',body:JSON.stringify(payload())}))}
    catch(e){setMessage('Erro na prévia: '+e.message)}finally{setBusy(false)}
  }
  async function execute(){
    if(!plan?.actionable||busy||(action==='DELETE'&&deleteText!=='EXCLUIR'))return
    if(!window.confirm('Confirmar '+action+' em '+words(plan.actionable,'QSO')+' na plataforma '+target+'? Esta ação modifica dados remotos.'))return
    setBusy(true);setMessage('Executando, sem fechar esta janela…')
    try{
      const started=await api('/api/qso-manager/bulk/jobs',{method:'POST',body:JSON.stringify(payload())})
      let state=started
      for(let i=0;i<2400;i++){
        await new Promise(resolve=>setTimeout(resolve,700))
        state=await api('/api/qso-manager/bulk/jobs/'+encodeURIComponent(started.job_id))
        setJob(state)
        if(['succeeded','failed','completed_with_errors'].includes(state.status))break
      }
      setMessage((state.message||state.status||'')+' Os snapshots gerenciados foram atualizados para conferência.')
      onDone()
    }catch(e){setMessage('Erro: '+e.message)}finally{setBusy(false)}
  }
  function changeAction(v){setAction(v);setPlan(null);setMessage('');setDeleteText('')}
  return <div className="u-modal-bg"><div className="u-modal" role="dialog" aria-modal="true" aria-label="Sincronizar QSOs selecionados" style={{maxWidth:650}}>
    <div className="u-modal-title"><div><small>OPERAÇÕES REMOTAS AUDITADAS</small><h2>Gerenciar {words(ids.length,'QSO')}</h2></div><button aria-label="Fechar operações remotas" disabled={busy} onClick={onClose}>×</button></div>
    <Notice>QRZ é a referência. Operações só serão executadas em plataformas e registros compatíveis, com prévia obrigatória.</Notice>
    <div className="u-fields">
      <label><span>Operação</span><select value={action} disabled={busy} onChange={e=>changeAction(e.target.value)}>{Object.entries(labels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
      <label><span>Plataforma de destino</span><select value={target} disabled={busy} onChange={e=>{setTarget(e.target.value);setPlan(null);setDeleteText('')}}>{targetOptions.map(p=><option key={p}>{p}</option>)}</select></label>
      {action==='UPDATE'&&<><label><span>Campo permitido</span><select value={field} onChange={e=>{setField(e.target.value);setPlan(null)}}>{allowedFields.map(x=><option key={x}>{x}</option>)}</select></label><label><span>Novo valor</span><input value={value} onChange={e=>{setValue(e.target.value);setPlan(null)}} placeholder="Deixe vazio para limpar o campo"/></label></>}
    </div>
    <div className="u-source-tags"><Badge tone={targetCaps.read?'ok':'neutral'}>{targetCaps.read?'ler por API':'sem leitura API'}</Badge><Badge tone={targetCaps.add?'ok':'neutral'}>criar</Badge><Badge tone={targetCaps.update?'ok':'neutral'}>editar</Badge><Badge tone={targetCaps.delete?'ok':'neutral'}>excluir</Badge>{targetCaps.max_batch&&<Badge>lote máx. {fmt(targetCaps.max_batch)}</Badge>}</div>
    {(targetCaps.update_note||targetCaps.read_note)&&<Notice>{targetCaps.update_note||targetCaps.read_note}</Notice>}
    {action==='DELETE'&&<label className="u-danger-confirm"><span>Exclusão remota é permanente. Digite <b>EXCLUIR</b> para liberar a execução.</span><input value={deleteText} disabled={busy} onChange={e=>setDeleteText(e.target.value.toUpperCase())} placeholder="EXCLUIR"/></label>}
    {ids.length>10000&&<Notice tone="warn">Limite de 10.000 QSOs por lote. Reduza a seleção.</Notice>}
    {plan&&<Notice tone={plan.actionable?'info':'warn'}>{fmt(plan.actionable)} prontos · {fmt(plan.skipped)} ignorados · {fmt(plan.unsupported)} não suportados. {plan.sample?.filter(x=>x.status!=='ready').slice(0,3).map(x=>x.call+': '+statusLabel(x.status)).join(' · ')}</Notice>}
    {job&&<Notice>{fmt(job.processed)} processados · {fmt(job.succeeded)} concluídos · {fmt(job.failed)} erros · {job.phase}</Notice>}
    {message&&<Notice tone={message.startsWith('Erro')?'error':'info'}>{message}</Notice>}
    <div className="u-modal-actions"><Button kind="secondary" disabled={busy} onClick={onClose}>Fechar</Button><div><Button kind="secondary" disabled={busy||ids.length>10000||!targetOptions.length} onClick={preview}>1. Simular</Button><Button disabled={busy||!plan?.actionable||ids.length>10000||(action==='DELETE'&&deleteText!=='EXCLUIR')} onClick={execute}>2. Executar ({fmt(plan?.actionable)})</Button></div></div>
  </div></div>
}

function LogPage({workspace}){
  const [data,setData]=useState({items:[],total:0,page:1,pages:1}),[filters,setFilters]=useState({q:'',band:'',mode:'',provider:'',missing_in:'',differences:'',duplicate:'',confirmed:'',date_from:'',date_to:''}),[page,setPage]=useState(1),[loading,setLoading]=useState(false),[msg,setMsg]=useState(''),[detail,setDetail]=useState(null),[selected,setSelected]=useState(new Set()),[selectionScope,setSelectionScope]=useState('manual'),[bulkOpen,setBulkOpen]=useState(false)
  const query=()=>{const p=new URLSearchParams({page:String(page),page_size:'100'});Object.entries(filters).forEach(([k,v])=>v&&p.set(k,v));return p.toString()}
  async function load(){setLoading(true);setMsg('');try{setData(await api('/api/product/log?'+query()))}catch(e){setMsg('Erro: '+e.message)}finally{setLoading(false)}}
  useEffect(()=>{const t=setTimeout(load,160);return()=>clearTimeout(t)},[page,filters.q,filters.band,filters.mode,filters.provider,filters.missing_in,filters.differences,filters.duplicate,filters.confirmed,filters.date_from,filters.date_to])
  useEffect(()=>{setPage(1);setSelected(new Set());setSelectionScope('manual')},[filters.q,filters.band,filters.mode,filters.provider,filters.missing_in,filters.differences,filters.duplicate,filters.confirmed,filters.date_from,filters.date_to])
  useEffect(()=>{if(selectionScope==='page'){setSelected(new Set());setSelectionScope('manual')}},[page])
  function toggle(id){setSelectionScope('manual');setSelected(prev=>{const n=new Set(prev);n.has(id)?n.delete(id):n.add(id);return n})}
  function selectPage(){const count=data.items?.length||0;setSelected(new Set((data.items||[]).map(row=>row.logical_id)));setSelectionScope('page');setMsg(count===1?'1 QSO selecionado nesta página.':`${fmt(count)} QSOs selecionados nesta página.`)}
  async function selectAll(){if(!data.total)return;if(!window.confirm(`Selecionar todos os ${fmt(data.total)} resultados filtrados, incluindo as outras páginas?`))return;try{const p=new URLSearchParams();Object.entries(filters).forEach(([k,v])=>v&&p.set(k,v));p.set('limit','50000');const r=await api('/api/qso-manager/ids?'+p.toString());const count=r.ids?.length||0;setSelected(new Set(r.ids||[]));setSelectionScope('all');setMsg(count===1?'1 QSO selecionado em todos os resultados filtrados.':`${fmt(count)} QSOs selecionados em todos os resultados filtrados.`)}catch(e){setMsg('Erro: '+e.message)}}
  async function exportSelected(){if(!selected.size)return;try{const response=await fetch('/api/qso-manager/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({logical_ids:[...selected]})});if(!response.ok){const x=await response.json();throw new Error(x.detail||'Falha no export')};const blob=await response.blob();downloadBlob('PU2BRU-QSO-Manager-export.adi',blob);setMsg(selected.size===1?'1 QSO exportado.':`${fmt(selected.size)} QSOs exportados.`)}catch(e){setMsg('Erro: '+e.message)}}
  const opts=workspace||{}
  const filterCount=Object.values(filters).filter(Boolean).length
  const clearSelection=()=>{setSelected(new Set());setSelectionScope('manual')}
  const clearFilters=()=>setFilters({q:'',band:'',mode:'',provider:'',missing_in:'',differences:'',duplicate:'',confirmed:'',date_from:'',date_to:''})
  const selectionLabel=selectionScope==='all'?`${words(selected.size,'QSO')} em todos os resultados filtrados`:selectionScope==='page'?`${words(selected.size,'QSO')} nesta página`:words(selected.size,'QSO')
  return <><PageHead eyebrow="LOG CONSOLIDADO" title="Um QSO. Todas as fontes." subtitle="Pesquise, filtre e abra qualquer contato para entender exatamente de onde cada campo veio." action={<div className="u-head-actions"><Button kind="secondary" onClick={selectPage}>Selecionar esta página ({fmt(data.items?.length)})</Button><Button kind="secondary" onClick={selectAll}>Selecionar todos ({fmt(data.total)})</Button></div>}/>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'info'}>{msg}</Notice>}<section className="u-filterbar"><label className="u-search"><span>⌕</span><input aria-label="Pesquisar QSOs" value={filters.q} onChange={e=>setFilters(v=>({...v,q:e.target.value.toUpperCase()}))} placeholder="Indicativo, país, grid, comentário…"/></label><label className="u-filter-field"><span>Banda</span><select aria-label="Filtrar por banda" value={filters.band} onChange={e=>setFilters(v=>({...v,band:e.target.value}))}><option value="">Todas</option>{(opts.bands||[]).map(x=><option key={x}>{x}</option>)}</select></label><label className="u-filter-field"><span>Modo</span><select aria-label="Filtrar por modo" value={filters.mode} onChange={e=>setFilters(v=>({...v,mode:e.target.value}))}><option value="">Todos</option>{(opts.modes||[]).map(x=><option key={x}>{x}</option>)}</select></label><label className="u-filter-field"><span>Presente em</span><select aria-label="Filtrar por fonte presente" value={filters.provider} onChange={e=>setFilters(v=>({...v,provider:e.target.value}))}><option value="">Qualquer fonte</option>{(opts.providers||[]).map(x=><option key={x} value={x}>{providerLabel(x)}</option>)}</select></label><label className="u-filter-field"><span>Ausente em</span><select aria-label="Filtrar por fonte ausente" value={filters.missing_in} onChange={e=>setFilters(v=>({...v,missing_in:e.target.value}))}><option value="">Sem filtro</option>{(opts.available_providers||[]).map(x=><option key={x} value={x}>{providerLabel(x)}</option>)}</select></label><label className="u-filter-field"><span>Diferenças</span><select aria-label="Filtrar por diferenças" value={filters.differences} onChange={e=>setFilters(v=>({...v,differences:e.target.value}))}><option value="">Todas</option><option value="true">Com diferenças</option><option value="false">Sem diferenças</option></select></label><label className="u-filter-field"><span>De</span><input aria-label="Data inicial" type="date" value={filters.date_from} onChange={e=>setFilters(v=>({...v,date_from:e.target.value}))}/></label><label className="u-filter-field"><span>Até</span><input aria-label="Data final" type="date" value={filters.date_to} onChange={e=>setFilters(v=>({...v,date_to:e.target.value}))}/></label>{filterCount>0&&<button className="u-clear-filters" onClick={clearFilters}>Limpar {words(filterCount,'filtro')}</button>}</section>{selected.size>0&&<div className="u-selection"><span><b>{selectionLabel}</b></span><div><Button small kind="secondary" onClick={exportSelected}>Exportar ADIF</Button><Button small disabled={selected.size>10000} onClick={()=>setBulkOpen(true)}>Sincronizar selecionados</Button><button onClick={clearSelection}>Limpar seleção</button></div></div>}<div className="u-log-list">{loading&&!data.items?.length?<div className="u-loading">Carregando log…</div>:(data.items||[]).map(row=>{const stale=new Set(row.stale_missing_in||[]),missing=(row.missing_in||[]).filter(p=>!stale.has(p));return <article key={row.logical_id} className={selected.has(row.logical_id)?'selected':''}><input aria-label={`Selecionar QSO ${row.call} de ${row.date} ${row.time||''}`} type="checkbox" checked={selected.has(row.logical_id)} onChange={()=>toggle(row.logical_id)}/><button className="u-log-main" onClick={()=>setDetail(row.logical_id)}><span><b>{row.call}</b><small>{row.date} · {row.time?.slice(0,5)} UTC</small></span><span className="u-band"><b>{row.band||'—'}</b><small>{row.mode||'—'} {row.freq?`· ${row.freq}`:''}</small></span><span className="u-place"><b>{row.country||'—'}</b><small>{row.grid||row.state||'sem localização'}</small></span><span className="u-badges">{row.providers?.map(p=><Badge key={p} title={providerLabel(p)} tone={p==='QRZ'?'truth':'ok'}>{short(p)}</Badge>)}{missing.slice(0,3).map(p=><Badge key={p} title={`Ausente em ${providerLabel(p)}`} tone="warn">−{short(p)}</Badge>)}{[...stale].slice(0,Math.max(0,3-missing.length)).map(p=><Badge key={p} title={`${providerLabel(p)} desatualizado; ausência não acionável`}>↻{short(p)}</Badge>)}</span><span className="u-row-status">{row.duplicate&&<Badge title="Duplicidade provável" tone="danger">dup</Badge>}{row.difference_count>0&&<Badge title={`${row.difference_count} campo(s) divergente(s)`} tone="warn">{row.difference_count} dif.</Badge>}{row.confirmed&&<Badge title={`Confirmação em ${(row.confirmation_sources||[]).map(providerLabel).join(', ')}`} tone="ok">QSL</Badge>}<em>›</em></span></button></article>})}</div>{!loading&&!data.items?.length&&<Empty title="Nenhum QSO encontrado">Ajuste os filtros ou atualize as fontes.</Empty>}<div className="u-pager"><Button kind="secondary" small disabled={page<=1} onClick={()=>setPage(p=>p-1)}>← Anterior</Button><span>Página <b>{data.page||page}</b> de {data.pages||1} · {fmt(data.total)} resultados</span><Button kind="secondary" small disabled={page>=(data.pages||1)} onClick={()=>setPage(p=>p+1)}>Próxima →</Button></div>{detail&&<QsoDrawer logicalId={detail} onClose={()=>setDetail(null)}/>} {bulkOpen&&<BulkActionDialog ids={[...selected]} workspace={workspace} onClose={()=>setBulkOpen(false)} onDone={()=>{load();clearSelection()}}/>}</>
}

function InboxPage({issues,onRefresh}){
  const [filter,setFilter]=useState('ALL'),[page,setPage]=useState(1),[search,setSearch]=useState(''),[loading,setLoading]=useState(false),[detail,setDetail]=useState(null);const visible=issues?.items||[];const counts=issues?.counts||{}
  const labels={MISSING:'Ausência',DIFFERENCE:'Divergência',DUPLICATE:'Duplicidade'}
  async function reload(nextPage=page,nextFilter=filter,nextSearch=search){setLoading(true);try{await onRefresh({page:nextPage,pageSize:50,kind:nextFilter,q:nextSearch})}finally{setLoading(false)}}
  useEffect(()=>{const t=setTimeout(()=>reload(),180);return()=>clearTimeout(t)},[page,filter,search])
  function chooseFilter(value){setFilter(value);setPage(1)}
  return <><PageHead eyebrow="CAIXA DE ENTRADA" title="Só o que exige atenção." subtitle="Cada QSO aparece uma vez. Ausências de fontes desatualizadas aguardam sincronização e não inflam a fila." action={<Button kind="secondary" disabled={loading} onClick={()=>reload()}>{loading?'Recalculando…':'Recalcular'}</Button>}/><div className="u-inbox-controls"><div className="u-chips">{[['ALL','Tudo',issues?.total],['MISSING','Ausentes',counts.missing],['DIFFERENCE','Divergências',counts.differences],['DUPLICATE','Duplicidades',counts.duplicates]].map(x=><button key={x[0]} className={filter===x[0]?'active':''} onClick={()=>chooseFilter(x[0])}>{x[1]} <b>{fmt(x[2])}</b></button>)}</div><label className="u-search compact"><span>⌕</span><input aria-label="Pesquisar pendências por indicativo" value={search} onChange={e=>{setSearch(e.target.value.toUpperCase());setPage(1)}} placeholder="Buscar indicativo…"/></label></div>{counts.informational>0&&<Notice>{words(counts.informational,'diferença')} somente informativas de nome, QTH ou comentário foram retiradas da fila.</Notice>}{counts.awaiting_refresh>0&&<Notice>{words(counts.awaiting_refresh,'QSO')} aguardam atualização de uma fonte e não são tratados como ausência acionável.</Notice>}{loading&&!visible.length?<div className="u-loading">Carregando pendências…</div>:<div className="u-inbox">{visible.map(x=><article key={x.logical_id}><i className={(x.types?.[0]||x.type).toLowerCase()}>{(x.types||[x.type]).includes('MISSING')?'−':'!'}</i><button className="u-inbox-open" onClick={()=>setDetail(x.logical_id)} aria-label={`Abrir pendência de ${x.call}`}><h3>{x.call} <span>{x.band} · {x.mode}</span> <Badge tone={x.severity==='HIGH'?'danger':'warn'}>{x.severity==='HIGH'?'alta':'revisar'}</Badge></h3><p>{x.date} {x.time?.slice(0,5)} · {x.message}</p><div className="u-badges">{(x.types||[x.type]).map(t=><Badge key={t} tone={t==='DUPLICATE'?'danger':'warn'}>{labels[t]||t}</Badge>)}{(x.sources||[]).map(p=><Badge title={providerLabel(p)} key={p}>{short(p)}</Badge>)}</div><span className="u-open-hint">Abrir QSO ›</span></button></article>)}</div>}{!loading&&!visible.length&&<Empty title="Fila limpa">Nenhuma ocorrência neste filtro.</Empty>}<div className="u-pager"><Button kind="secondary" small disabled={page<=1||loading} onClick={()=>setPage(p=>p-1)}>← Anterior</Button><span>Página <b>{issues?.page||page}</b> de {issues?.pages||1} · {fmt(issues?.filtered_total??issues?.total)} resultados</span><Button kind="secondary" small disabled={page>=(issues?.pages||1)||loading} onClick={()=>setPage(p=>p+1)}>Próxima →</Button></div>{detail&&<QsoDrawer logicalId={detail} onClose={()=>setDetail(null)}/>}</>
}

function QslPage({qsl,onRefresh,onChanged,setGlobalMessage}){
  const s=qsl?.summary||{}
  const [syncPlan,setSyncPlan]=useState(null)
  const [syncBusy,setSyncBusy]=useState('')
  const [proposalPage,setProposalPage]=useState(1),[proposalService,setProposalService]=useState(''),[proposalSearch,setProposalSearch]=useState('')
  const dateLabel=value=>{const v=String(value||'').replace(/-/g,'');return /^\d{8}$/.test(v)?v.slice(6,8)+'/'+v.slice(4,6)+'/'+v.slice(0,4):(value||'—')}
  const proposalParams=()=>({page:proposalPage,pageSize:100,service:proposalService,q:proposalSearch})
  useEffect(()=>{const current=qsl?.filters||{};if(!qsl?.ready||qsl?.loading)return;if((qsl.pagination?.page||1)===proposalPage&&(current.service||'')===proposalService&&(current.q||'')===proposalSearch)return;const t=setTimeout(()=>onRefresh(proposalParams()),180);return()=>clearTimeout(t)},[proposalPage,proposalService,proposalSearch,qsl?.ready,qsl?.loading])

  async function analyzeEqslQrz(){
    setSyncBusy('plan')
    try{
      const plan=await api('/api/product/qsl/eqsl-qrz/plan?refresh=true')
      setSyncPlan(plan)
      const n=plan.summary?.safe_updates||0
      setGlobalMessage(n?'eQSL → QRZ: '+fmt(n)+' atualização(ões) segura(s) pronta(s) para revisão.':'eQSL → QRZ: nenhuma atualização segura pendente.')
      await onRefresh(proposalParams())
    }catch(e){setGlobalMessage('Erro: '+e.message)}
    finally{setSyncBusy('')}
  }

  async function applyEqslQrz(){
    const n=Number(syncPlan?.summary?.safe_updates||0)
    if(!n)return
    if(!window.confirm('Aplicar '+n+' atualização(ões) eQSL seguras no QRZ?\n\nO sistema fará preflight, backup, canário e validação pós-gravação. Somente EQSL_QSL_RCVD e EQSL_QSLRDATE serão alterados.'))return
    setSyncBusy('apply')
    try{
      const result=await api('/api/product/qsl/eqsl-qrz/apply',{method:'POST',body:JSON.stringify({confirm:true,limit:Math.min(n,500)})})
      const suffix=result.full_resync?'QRZ resincronizado após a gravação.':'Atualizações verificadas; uma resincronização completa do QRZ ficou pendente.'
      setGlobalMessage('eQSL → QRZ: '+fmt(result.updated)+' atualizado(s), '+fmt(result.skipped)+' já alinhado(s). '+suffix)
      await onChanged(proposalParams())
      const plan=await api('/api/product/qsl/eqsl-qrz/plan')
      setSyncPlan(plan)
    }catch(e){setGlobalMessage('Erro: '+e.message)}
    finally{setSyncBusy('')}
  }

  const ps=syncPlan?.summary||{}
  const manualTotal=Number(ps.manual_review||0)+Number(ps.date_conflicts||0)
  const diagnosticTotal=Number(ps.collisions||0)+Number(ps.missing_explicit_date||0)
  return <><PageHead eyebrow="CENTRAL DE QSL" title="Confirmações com evidência." subtitle="eQSL Inbox e LoTW são tratados como fontes de confirmação. A análise pesada é carregada somente ao abrir esta área." action={<Button kind="secondary" onClick={()=>onRefresh(proposalParams())}>Atualizar análise</Button>}/>
    {(qsl?.lazy||qsl?.loading)&&<div className="u-loading">Analisando evidências QSL sob demanda…</div>}
    <div className="u-metrics static"><div><span>Pares QSO/serviço</span><b>{fmt(s.matched_confirmation_groups)}</b><small>um QSO pode ter eQSL e LoTW</small></div><div><span>Propostas</span><b>{fmt(s.actionable_proposals)}</b><small>confirmações ainda não refletidas</small></div><div><span>Sem par seguro</span><b>{fmt(s.unmatched_evidence)}</b></div><div><span>Conflitos de data</span><b>{fmt(s.date_conflicts)}</b></div></div>
    <Card title="eQSL → QRZ" subtitle="Sincronização segura das confirmações recebidas. Atualiza somente eQSL recebido e a data de recebimento no QRZ.">
      <div className="u-eqsl-sync-head"><div><p>Critério automático: CALL + data + banda + modo compatível, diferença máxima de 2 minutos e pareamento estritamente 1:1.</p><small>Casos ambíguos, sem data explícita ou fora da janela ficam para revisão e nunca são gravados automaticamente.</small></div><Button disabled={!!syncBusy} onClick={analyzeEqslQrz}>{syncBusy==='plan'?'Atualizando fontes…':'Atualizar fontes e analisar'}</Button></div>
      {syncPlan&&<><div className="u-metrics static"><div><span>Atualizações seguras</span><b>{fmt(ps.safe_updates)}</b></div><div><span>Novas confirmações</span><b>{fmt(ps.new_confirmations)}</b></div><div><span>Datas a alinhar</span><b>{fmt(ps.date_alignments)}</b></div><div><span>Revisão acionável</span><b>{fmt(manualTotal)}</b></div></div>
        <div className="u-eqsl-sync-meta"><span>QRZ: {dt(syncPlan.snapshot_freshness?.QRZ)}</span><span>eQSL Inbox: {dt(syncPlan.snapshot_freshness?.EQSL_INBOX)}</span></div>
        {(syncPlan.candidates||[]).length>0?<div className="u-eqsl-sync-list">{(syncPlan.candidates||[]).slice(0,200).map((p,i)=><article key={p.logid||i}><div><b>{p.call}</b><small>{p.qso_date} · {p.time_qrz} · {p.band} · {p.mode_qrz}</small></div><Badge tone={p.kind==='NEW_CONFIRMATION'?'ok':'warn'}>{p.kind==='NEW_CONFIRMATION'?'nova QSL':'alinhar data'}</Badge><div><small>QRZ atual</small><b>{p.current_received||'—'} / {dateLabel(p.current_date)}</b></div><div><small>eQSL alvo</small><b>Y / {dateLabel(p.target_date)}</b></div></article>)}</div>:<Empty title="QRZ e eQSL alinhados">Nenhuma atualização automática segura foi encontrada.</Empty>}
        {(syncPlan.candidates||[]).length>200&&<p className="u-muted">Mostrando os primeiros 200 de {fmt(syncPlan.candidates.length)} candidatos. A aplicação processa no máximo 500 por rodada.</p>}
        <div className="u-eqsl-sync-actions"><Button disabled={!!syncBusy||!ps.safe_updates} onClick={applyEqslQrz}>{syncBusy==='apply'?'Aplicando e validando…':'Aplicar '+fmt(ps.safe_updates)+' atualização(ões) seguras'}</Button><span>Backup local + backup ADIF live + canário + verificação de CONTEST_ID e LoTW.</span></div>
        {!!manualTotal&&<Notice tone="warn">{fmt(ps.manual_review)} candidato(s) próximo(s) fora da janela automática e {fmt(ps.date_conflicts)} conflito(s) de data requerem revisão.</Notice>}{!!diagnosticTotal&&<Notice>{fmt(ps.collisions)} colisão(ões) histórica(s) e {fmt(ps.missing_explicit_date)} evidência(s) sem data explícita ficam apenas como diagnóstico e nunca são gravadas automaticamente.</Notice>}
      </>}
    </Card>
    {!qsl?.ready?(qsl?.loading||qsl?.lazy?null:<Empty title="Ainda sem evidência online">Atualize QRZ e ao menos eQSL Inbox ou LoTW.</Empty>):<Card title="Propostas de confirmação para o QRZ" subtitle="Lista auditável de eQSL e LoTW. O fluxo de gravação automática permanece separado e protegido."><div className="u-qsl-controls"><label className="u-search compact"><span>⌕</span><input aria-label="Pesquisar propostas QSL" value={proposalSearch} onChange={e=>{setProposalSearch(e.target.value.toUpperCase());setProposalPage(1)}} placeholder="Buscar indicativo…"/></label><label className="u-filter-field"><span>Serviço</span><select aria-label="Filtrar propostas por serviço" value={proposalService} onChange={e=>{setProposalService(e.target.value);setProposalPage(1)}}><option value="">eQSL e LoTW</option>{(qsl.services||[]).map(x=><option key={x} value={x}>{x}</option>)}</select></label></div><div className="u-qsl-list">{(qsl.proposals||[]).map((p,i)=><article key={`${p.service}-${p.qso?.index??i}`}><div><h3>{p.qso?.call}</h3><p>{p.qso?.date} · {p.qso?.band} · {p.qso?.mode}</p></div><Badge tone="ok">{p.service}</Badge><div><b>{Object.entries(p.changes||{}).map(([k,v])=>k+'='+v).join(' · ')}</b><small>{p.reason}</small></div></article>)}</div>{!(qsl.proposals||[]).length&&<Empty title="Nenhuma proposta neste filtro">Ajuste a busca ou selecione outro serviço.</Empty>}<div className="u-pager"><Button kind="secondary" small disabled={proposalPage<=1||qsl?.loading} onClick={()=>setProposalPage(p=>p-1)}>← Anterior</Button><span>Página <b>{qsl.pagination?.page||proposalPage}</b> de {qsl.pagination?.pages||1} · {fmt(qsl.pagination?.filtered_total)} propostas</span><Button kind="secondary" small disabled={proposalPage>=(qsl.pagination?.pages||1)||qsl?.loading} onClick={()=>setProposalPage(p=>p+1)}>Próxima →</Button></div></Card>}</>
}
function SourcesPage({status,onChanged,setGlobalMessage,onSyncAll,onSyncProvider,syncJob,globalBusy}){
  const [config,setConfig]=useState(null),[busy,setBusy]=useState('')
  const providers=status?.providers||[]
  async function sync(p){setBusy(p);try{await onSyncProvider(p)}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}
  async function importAdif(p,file){if(!file)return;if(p==='WRL'&&!window.confirm('Confirma que este arquivo é a EXPORTAÇÃO COMPLETA do World Radio League? Uma exportação parcial não serve para conciliação. O snapshot anterior será preservado em backup.'))return;setBusy(p);try{const r=await api('/api/product/sources/'+p+'/adif',{method:'PUT',body:JSON.stringify({content:await file.text(),filename:file.name})});setGlobalMessage(`${p}: ${fmt(r.records)} QSOs importados de ${file.name}.`);await onChanged()}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}
  async function updateHrdlog(){setBusy('HRDLOG');try{const plan=await api('/api/product/hrdlog/plan?limit=500');if(!plan.safe_missing){setGlobalMessage('HRDLog já está alinhado com o estado conhecido do QRZ.');return}if(!window.confirm(`Enviar ${plan.candidates.length} QSO(s) seguros ao HRDLog.net?`))return;const r=await api('/api/product/hrdlog/push',{method:'POST',body:JSON.stringify({confirm:true,limit:500})});setGlobalMessage(`HRDLog: ${fmt(r.sent_or_already_remote)} atualizados; ${fmt(r.errors?.length)} erro(s).`);await onChanged()}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}
  async function clear(p){if(!window.confirm(`Apagar somente o snapshot local de ${p}? Nada será removido na plataforma remota.`))return;setBusy(p);try{await api('/api/product/sources/'+p+'/snapshot',{method:'DELETE'});setGlobalMessage(`${p}: snapshot local removido.`);await onChanged()}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}
  async function setScope(p){const next=p.participates===false?'ACTIVE':'OUT_OF_SCOPE';setBusy('scope-'+p.provider);try{await api('/api/product/sources/'+p.provider+'/scope',{method:'PUT',body:JSON.stringify({scope:next})});setGlobalMessage(next==='ACTIVE'?`${p.label}: incluído novamente na comparação.`:`${p.label}: preservado, mas fora da comparação.`);await onChanged()}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}
  return <><PageHead eyebrow="FONTES" title="Uma central para todas as conexões." subtitle="Conexão, dados carregados, atualização e participação na comparação são estados independentes." action={<Button disabled={globalBusy||!!busy} onClick={onSyncAll}>{globalBusy?'Atualizando…':'Atualizar todas'}</Button>}/>{syncJob&&<SyncProgress job={syncJob}/>}<div className="u-source-grid">{providers.map(p=><Card key={p.provider} title={p.label} subtitle={p.note} action={<span title={p.configured?'Conexão configurada':p.snapshot_loaded?'Dados carregados sem conexão':'Fonte não configurada'} className={'u-dot '+(p.configured||p.snapshot_loaded?'ok':'')}/>}><div className="u-source-number"><b>{fmt(p.snapshot?.records)}</b><span>registros conhecidos</span><small>Atualizado: {dt(p.snapshot?.downloaded_at)}</small></div><div className="u-source-tags"><Badge>{sourceKindLabel(p.source_kind)}</Badge><Badge tone={p.configured?'ok':p.snapshot_loaded?'warn':'neutral'}>{p.provider==='HRD'?(p.snapshot_loaded?'ADIF carregado':'sem ADIF'):p.configured?'conexão pronta':p.snapshot_loaded?'dados carregados · sem conexão':'não configurada'}</Badge><Badge tone={p.participates===false?'neutral':'ok'}>{p.participates===false?'fora do escopo':'comparação ativa'}</Badge><Badge tone={p.snapshot_state==='STALE'?'warn':p.snapshot_state==='CURRENT'?'ok':'neutral'}>{p.snapshot_state==='STALE'?'snapshot desatualizado':p.snapshot_state==='CURRENT'?'snapshot atual':'sem snapshot'}</Badge>{p.comparison_role==='qsl_evidence'&&<Badge tone="ok">evidência QSL</Badge>}{p.provider==='QRZ'&&<Badge tone="truth">referência</Badge>}</div>{p.snapshot_state==='STALE'&&p.participates!==false&&<Notice tone="warn">{p.snapshot_stale_by_lag?'Esta fonte está atrasada em relação às demais. Ausências nela ficam aguardando atualização e não entram como pendência acionável.':'Este snapshot tem mais de 24 horas. Atualize a fonte para comparar dados recentes.'}</Notice>}<div className="u-source-actions">{!['HRD'].includes(p.provider)&&<Button kind="secondary" small onClick={()=>setConfig(p)}>{p.configured?'Conexão':'Configurar'}</Button>}{p.provider==='HRD'&&<label className="u-file">{p.configured?'Substituir ADIF':'Importar ADIF'}<input type="file" accept=".adi,.adif,.txt" onChange={e=>{importAdif('HRD',e.target.files?.[0]);e.target.value=''}}/></label>}{p.provider==='WRL'&&<label className="u-file">Importar ADIF completo<input type="file" accept=".adi,.adif,.txt" onChange={e=>{importAdif('WRL',e.target.files?.[0]);e.target.value=''}}/></label>}{p.provider==='HRDLOG'&&<label className="u-file">Reconciliar ADIF<input type="file" accept=".adi,.adif,.txt" onChange={e=>{importAdif('HRDLOG',e.target.files?.[0]);e.target.value=''}}/></label>}{p.provider==='HRDLOG'?<Button small disabled={globalBusy||busy===p.provider||!p.configured||!p.snapshot?.downloaded_at} onClick={updateHrdlog}>{busy===p.provider?'Processando…':'Atualizar online'}</Button>:p.capabilities?.read&&p.source_kind!=='local_adif'&&<Button small disabled={globalBusy||busy===p.provider||!p.configured} onClick={()=>sync(p.provider)}>{busy===p.provider?'Atualizando…':'Atualizar'}</Button>}{p.comparison_role==='log'&&p.provider!=='QRZ'&&<Button kind="secondary" small disabled={busy==='scope-'+p.provider} onClick={()=>setScope(p)}>{p.participates===false?'Incluir na comparação':'Retirar da comparação'}</Button>}{p.snapshot?.records>0&&<button className="u-text-danger" disabled={globalBusy||busy===p.provider} onClick={()=>clear(p.provider)}>Limpar cópia local</button>}</div></Card>)}</div>{config&&<ConnectionModal source={config} onClose={()=>setConfig(null)} onChanged={async()=>{await onChanged();setConfig(null)}}/>}</>
}


function IntegrityPage(){
  const [tab,setTab]=useState('cases'),[data,setData]=useState(null),[qsl,setQsl]=useState(null)
  const [history,setHistory]=useState(null),[monitor,setMonitor]=useState(null),[plan,setPlan]=useState(null)
  const [provider,setProvider]=useState(''),[kind,setKind]=useState(''),[search,setSearch]=useState(''),[page,setPage]=useState(1)
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState('')
  const [chosen,setChosen]=useState(new Set()),[reason,setReason]=useState(''),[job,setJob]=useState(null)
  const [decision,setDecision]=useState(null),[decisionReason,setDecisionReason]=useState('')
  const [hours,setHours]=useState(12)
  const qs=new URLSearchParams({page:String(page),page_size:'50'})
  if(provider)qs.set('provider',provider)
  if(kind)qs.set('kind',kind)
  if(search)qs.set('q',search.trim())
  async function loadReport(){setBusy('report');setError('');try{setData(await api('/api/integrity/report?'+qs.toString()))}catch(e){setError(e.message)}finally{setBusy('')}}
  async function loadTab(next=tab){
    setError('');setBusy(next)
    try{
      if(next==='qsl'){setQsl(await api('/api/integrity/qsl-dxcc?limit=150'))}
      if(next==='audit'){setHistory(await api('/api/integrity/history?limit=100'))}
      if(next==='monitor'){const m=await api('/api/integrity/monitor');setMonitor(m);setHours(m.monitor?.interval_hours||12)}
    }catch(e){setError(e.message)}finally{setBusy('')}
  }
  useEffect(()=>{loadReport()},[page,provider,kind,search])
  useEffect(()=>{loadTab(tab)},[tab])
  useEffect(()=>{
    const timer=setInterval(async()=>{
      try{
        const m=await api('/api/integrity/monitor')
        setMonitor(m)
        if(m.snapshot_changes_pending){await loadReport()}
      }catch{}
    },60000)
    return()=>clearInterval(timer)
  },[page,provider,kind,search])
  const statusLabel={ALIGNED_WITH_QRZ:'Alinhado',DIVERGENT:'Divergências',RECONCILED_WITH_EXCEPTIONS:'Revisado com exceções',STALE_SNAPSHOT:'Dados desatualizados',REFERENCE_MISSING:'QRZ não carregado',NO_COMPLETE_SNAPSHOT:'Sem log completo',PROVIDER_ERROR:'Erro de origem',OUT_OF_SCOPE:'Fora do escopo'}
  const caseLabel={MISSING:'AUSENTE',EXTRA:'SEM QRZ',DIFFERENCE:'DIVERGÊNCIA',DUPLICATE:'DUPLICIDADE'}
  const cases=data?.items||[],summary=data?.summary||{},metrics=summary.providers||{}
  async function preview(p){
    setBusy('plan');setPlan(null);setChosen(new Set());setMessage('')
    try{
      const result=await api('/api/integrity/plan/'+p+'?limit=100')
      setPlan(result)
      setChosen(new Set())
      setReason('Conciliação assistida QRZ → '+p+' após revisão dos candidatos.')
    }catch(e){setError(e.message)}finally{setBusy('')}
  }
  async function apply(){
    if(!plan||!chosen.size||reason.trim().length<5)return
    if(!window.confirm('CONFIRMAR inclusão de '+chosen.size+' QSO(s) em '+plan.target+'? Isso modifica o logbook remoto. Nenhum registro será excluído.'))return
    setBusy('apply');setMessage('Executando operações auditadas…')
    try{
      let state=await api('/api/integrity/apply',{method:'POST',body:JSON.stringify({
        target:plan.target,signature:plan.signature,logical_ids:[...chosen],reason,confirm:true
      })})
      setJob(state)
      for(let i=0;i<2400;i++){
        if(['succeeded','failed','completed_with_errors'].includes(state.status))break
        await new Promise(resolve=>setTimeout(resolve,800))
        state=await api('/api/qso-manager/bulk/jobs/'+encodeURIComponent(state.job_id))
        setJob(state)
      }
      setMessage((state.message||'Operação finalizada')+' Consulte Auditoria para o histórico.')
      setPlan(null)
      await loadReport()
    }catch(e){setError(e.message)}finally{setBusy('')}
  }
  async function saveDecision(){
    if(!decision||decisionReason.trim().length<5)return
    setBusy('decision')
    try{
      await api('/api/integrity/decision',{method:'POST',body:JSON.stringify({
        case_key:decision.case_key,provider:decision.provider,decision:decision.choice,
        reason:decisionReason,evidence:{call:decision.call,date:decision.date}
      })})
      setDecision(null);setDecisionReason('');setMessage('Decisão salva no histórico local.')
      await loadReport()
    }catch(e){setError(e.message)}finally{setBusy('')}
  }
  async function monitorSave(enabled){
    setBusy('monitor')
    try{
      const m=await api('/api/integrity/monitor',{method:'PUT',body:JSON.stringify({enabled,interval_hours:Number(hours)})})
      setMonitor({...monitor,monitor:m})
      setMessage(enabled?'Monitoramento somente leitura ativado.':'Monitoramento automático desativado.')
    }catch(e){setError(e.message)}finally{setBusy('')}
  }
  return <div className="u-integrity">
    <PageHead eyebrow="SAÚDE DOS LOGBOOKS" title="Integridade e conciliação" subtitle="QRZ como referência. Divergências por QSO, duplicidades explicadas, correções assistidas e trilha de auditoria." action={<Button kind="secondary" disabled={busy==='report'} onClick={loadReport}>↻ Recalcular</Button>}/>
    {error&&<Notice tone="error">{error}</Notice>}{message&&<Notice>{message}</Notice>}
    <div className="u-chips">{[['cases','Conciliação'],['qsl','QSL / DXCC'],['audit','Decisões e auditoria'],['monitor','Monitoramento']].map(([key,label])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}>{label}</button>)}</div>
    {tab==='cases'&&<>
      <div className="u-metrics static">
        <div><span>QSOs no QRZ</span><b>{fmt(summary.reference_records)}</b></div>
        <div><span>Casos para revisão</span><b>{fmt(summary.review_cases)}</b></div>
        <div><span>Ausências</span><b>{fmt(summary.by_kind?.MISSING)}</b></div>
        <div><span>Somente informativos</span><b>{fmt(summary.informational_cases)}</b></div>
      </div>
      <div className="u-integrity-providers">{Object.entries(metrics).map(([p,m])=><Card key={p} title={p} subtitle={statusLabel[m.state]||m.state} action={<Badge tone={m.state==='ALIGNED_WITH_QRZ'?'ok':['NO_COMPLETE_SNAPSHOT','OUT_OF_SCOPE'].includes(m.state)?'neutral':'warn'}>{m.scope==='OUT_OF_SCOPE'?'ignorado':m.coverage||'Cobertura desconhecida'}</Badge>}><div className="u-integrity-stats"><span>Registros <b>{fmt(m.records)}</b></span><span>Faltantes <b>{fmt(m.missing)}</b></span><span>Extras <b>{fmt(m.extra)}</b></span><span>Diferenças <b>{fmt(m.different)}</b></span><span>Dup. <b>{fmt(m.duplicates)}</b></span></div>{m.exception&&<Notice tone="warn">{m.exception.classification}: {m.exception.message}</Notice>}<Button small disabled={!m.loaded||busy==='plan'} onClick={()=>preview(p)}>Planejar QRZ → {p}</Button></Card>)}</div>
      {plan&&<Card title={'Plano seguro: QRZ → '+plan.target} subtitle={'Somente inclusões • '+fmt(plan.missing_total)+' ausentes • '+fmt(plan.total_candidates)+' elegíveis • '+fmt(plan.blocked)+' bloqueados'} action={<Button small kind="secondary" onClick={()=>setPlan(null)}>Fechar</Button>}>
        <Notice>Uma inclusão só será executada após sua confirmação; registros já presentes, sem suporte ou suspeitos de duplicidade são excluídos automaticamente do plano.</Notice>
        {plan.blocked>0&&<Notice tone="warn">Bloqueios: {Object.entries(plan.blocked_reasons||{}).map(([k,v])=>`${k.replaceAll('_',' ').toLowerCase()}: ${fmt(v)}`).join(' · ')}</Notice>}
        <div className="u-integrity-actions"><Button small kind="secondary" onClick={()=>setChosen(new Set(plan.logical_ids||[]))}>Selecionar lote ({fmt(plan.selected)})</Button><Button small kind="secondary" onClick={()=>setChosen(new Set())}>Desmarcar</Button></div>
        <div className="u-integrity-cases">{(plan.sample||[]).map(c=><label key={c.case_key} className="u-integrity-case"><input type="checkbox" checked={chosen.has(c.logical_id)} onChange={e=>setChosen(v=>{const n=new Set(v);e.target.checked?n.add(c.logical_id):n.delete(c.logical_id);return n})}/><b>{c.call}</b><small>{c.date} {c.time} · {c.band} {c.mode}</small></label>)}</div>
        <div className="u-integrity-actions"><input value={reason} onChange={e=>setReason(e.target.value)} placeholder="Justificativa da intervenção"/><Button disabled={!chosen.size||busy==='apply'||reason.trim().length<5} onClick={apply}>Aplicar {fmt(chosen.size)} inclusão(ões)</Button></div>
      </Card>}
      {job&&<Notice>Job {job.job_id?.slice(0,8)}: {job.status} · {fmt(job.succeeded)} concluídos · {fmt(job.failed)} falhas. {job.message}</Notice>}
      <div className="u-filterbar u-integrity-filters"><div className="u-search"><span>⌕</span><input placeholder="Buscar indicativo" value={search} onChange={e=>{setSearch(e.target.value.toUpperCase());setPage(1)}}/></div><select value={provider} onChange={e=>{setProvider(e.target.value);setPage(1)}}><option value="">Todas as fontes</option>{Object.keys(metrics).map(x=><option key={x}>{x}</option>)}</select><select value={kind} onChange={e=>{setKind(e.target.value);setPage(1)}}><option value="">Todos os problemas</option><option value="MISSING">Ausentes</option><option value="EXTRA">Sem QRZ</option><option value="DIFFERENCE">Campos divergentes</option><option value="DUPLICATE">Possíveis duplicidades</option></select></div>
      {busy==='report'&&!data?<div className="u-loading">Comparando registros…</div>:<div className="u-integrity-cases">{cases.map(c=><article key={c.case_key} className="u-integrity-case"><div className="u-integrity-row"><Badge tone={c.kind==='MISSING'?'warn':c.kind==='DUPLICATE'?'danger':'neutral'}>{caseLabel[c.kind]||c.kind}</Badge><Badge tone={c.severity==='HIGH'?'danger':c.severity==='INFO'?'neutral':'warn'}>{c.severity==='HIGH'?'ALTA':c.severity==='INFO'?'INFO':'REVISAR'}</Badge><b>{c.call}</b><small>{c.date} {c.time} · {c.band} {c.mode}</small><Badge>{c.provider}</Badge>{c.decision&&<Badge tone="ok">{c.decision}</Badge>}</div><p>{c.reason}{c.field&&<span> · {c.field}: QRZ {String(c.reference_value)} / {c.provider} {String(c.provider_value)}</span>}</p><div className="u-integrity-actions">{c.kind==='DUPLICATE'&&<Button small kind="secondary" onClick={()=>{setDecision({...c,choice:'KEEP_SEPARATE'});setDecisionReason('QSOs independentes confirmados após conferência de banda, modo e horário.')}}>Manter separados</Button>}{c.kind==='DUPLICATE'&&<Button small kind="secondary" onClick={()=>{setDecision({...c,choice:'CONFIRMED_DUPLICATE'});setDecisionReason('Duplicidade confirmada mediante revisão manual das evidências.')}}>Confirmar duplicidade</Button>}<Button small kind="secondary" onClick={()=>{setDecision({...c,choice:'ACCEPT_EXCEPTION'});setDecisionReason('Limitação específica do provedor aceita após revisão.')}}>Aceitar exceção</Button><Button small kind="secondary" onClick={()=>{setDecision({...c,choice:'NEEDS_REVIEW'});setDecisionReason('Verificar evidências do QSO antes de qualquer correção remota.')}}>Marcar revisão</Button></div></article>)}</div>}
      {!cases.length&&busy!=='report'&&<Empty title="Nenhuma ocorrência nesta seleção">Fontes sem export completo não são consideradas conciliadas.</Empty>}
      <div className="u-pager"><Button small kind="secondary" disabled={page<=1} onClick={()=>setPage(n=>n-1)}>← Anterior</Button><span>{fmt(data?.total)} ocorrência(s) · Página {page}</span><Button small kind="secondary" disabled={page*50>=(data?.total||0)} onClick={()=>setPage(n=>n+1)}>Próxima →</Button></div>
      {decision&&<div className="u-modal-bg"><div className="u-modal"><div className="u-modal-title"><div><small>DECISÃO AUDITÁVEL</small><h2>{decision.call} · {decision.provider}</h2></div><button onClick={()=>setDecision(null)}>×</button></div><Notice>Esta decisão registra a revisão; não exclui nem modifica QSOs remotamente.</Notice><p>{decision.reason}</p><div className="u-fields"><label><span>Justificativa</span><textarea rows={4} value={decisionReason} onChange={e=>setDecisionReason(e.target.value)}/></label></div><div className="u-modal-actions"><Button kind="secondary" onClick={()=>setDecision(null)}>Cancelar</Button><Button disabled={busy==='decision'||decisionReason.trim().length<5} onClick={saveDecision}>Salvar decisão</Button></div></div></div>}
    </>}
    {tab==='qsl'&&<>{busy==='qsl'&&!qsl?<div className="u-loading">Analisando confirmações e entidades DXCC…</div>:<><div className="u-metrics static"><div><span>DXCCs com evidência de QSL</span><b>{fmt(qsl?.summary?.confirmed_dxcc)}</b></div><div><span>DXCCs ainda não confirmados</span><b>{fmt(qsl?.summary?.pending_dxcc)}</b></div><div><span>QSOs prioritários</span><b>{fmt(qsl?.summary?.priority_qsos)}</b></div></div><Notice>As prioridades refletem novas possibilidades de DXCC/banda/modo. Não garantem confirmação nem homologação de award.</Notice><div className="u-integrity-cases">{(qsl?.items||[]).map((x,i)=><article key={x.call+x.date+x.time+i} className="u-integrity-case"><div className="u-integrity-row"><Badge tone={x.new_dxcc?'warn':'neutral'}>Prioridade {x.priority}</Badge><b>{x.call}</b><small>{x.date} · {x.band} {x.mode}</small><Badge>DXCC {x.dxcc}</Badge></div><p>{x.country||'Entidade não informada'} · {x.reason}</p></article>)}</div>{qsl&&!qsl.ready&&<Empty title="Sem dados do QRZ">Importe ou atualize o QRZ para analisar oportunidades.</Empty>}</>}</>}
    {tab==='audit'&&<><Card title="Histórico de decisões" subtitle="Justificativas e evidências armazenadas no computador.">{(history?.decisions||[]).slice(0,100).map(x=><article className="u-integrity-history" key={x.id}><b>{x.decision} · {x.provider}</b><small>{dt(x.created_at)}</small><p>{x.reason}</p></article>)}{!history?.decisions?.length&&<Empty title="Sem decisões registradas"/>}</Card><Card title="Resultados por QSO" subtitle="Cada tentativa de gravação e seu resultado ficam registrados.">{(history?.corrections||[]).slice(0,100).map(x=><article className="u-integrity-history" key={x.id}><b>{x.action} · {x.provider} · {x.status}</b><small>{dt(x.created_at)}</small><p>QSO {x.logical_id?.slice(0,12)} · job {x.job_id?.slice(0,10)}</p></article>)}</Card><Card title="Intervenções e sincronizações" subtitle="Rastreabilidade de ações do QSO Manager.">{(history?.actions||[]).slice(0,50).map(x=><article className="u-integrity-history" key={x.id}><b>{x.kind} · {x.status}</b><small>{dt(x.timestamp)}</small><p>{x.summary}</p></article>)}</Card><Card title="Histórico de medições" subtitle="Conciliação reavaliada quando os snapshots mudam.">{(history?.scans||[]).map((x,i)=><div className="u-integrity-history" key={i}><b>{dt(x.created_at)}</b><small>{fmt(x.summary?.cases)} ocorrências · QRZ {fmt(x.summary?.reference_records)}</small></div>)}</Card></>}
    {tab==='monitor'&&<><Card title="Monitoramento contínuo" subtitle="Somente leituras. Reavalia mudanças de snapshots e pode atualizar fontes automaticamente enquanto o aplicativo estiver aberto."><Notice>Por segurança, o monitoramento remoto é opt-in. Falhas persistentes, autenticação e limites de API interrompem novas tentativas automáticas por provedor.</Notice><div className="u-integrity-actions"><label>Intervalo entre atualizações<select value={hours} onChange={e=>setHours(Number(e.target.value))}>{[6,12,24,48,72,168].map(n=><option key={n} value={n}>{n} horas</option>)}</select></label><Button kind={monitor?.monitor?.enabled?'secondary':'primary'} disabled={busy==='monitor'} onClick={()=>monitorSave(!monitor?.monitor?.enabled)}>{monitor?.monitor?.enabled?'Desativar monitoramento':'Ativar monitoramento'}</Button></div><div className="u-integrity-history"><b>Última atualização automática</b><p>{dt(monitor?.monitor?.last_started)}</p><b>Alterações locais aguardando análise</b><p>{monitor?.snapshot_changes_pending?'Sim':'Não'}</p><b>Ocorrências no último diagnóstico</b><p>{fmt(monitor?.last_cases)} · Variação líquida: {monitor?.net_case_variation==null?'sem medição anterior':(monitor.net_case_variation>0?'+':'')+monitor.net_case_variation}</p><b>Provedores temporariamente bloqueados</b><p>{monitor?.monitor?.blocked_providers?.join(', ')||'Nenhum'}</p></div><Button kind="secondary" onClick={async()=>{setBusy('check');try{await api('/api/integrity/monitor/check',{method:'POST',body:'{}'});await loadTab('monitor');await loadReport();setMessage('Verificação concluída.')}catch(e){setError(e.message)}finally{setBusy('')}}}>Verificar snapshots agora</Button></Card></>}
  </div>
}

function AdvancedCompare(){
  const seed=name=>({id:crypto.randomUUID?.()||Math.random().toString(36),name,file:null,coverage:'FULL_EXPORT'});const [sources,setSources]=useState([seed('QRZ'),seed('HRD')]),[reference,setReference]=useState(0),[result,setResult]=useState(null),[busy,setBusy]=useState(false),[msg,setMsg]=useState('')
  function patch(i,changes){setSources(v=>v.map((x,j)=>j===i?{...x,...changes}:x))}
  async function compare(){setMsg('');if(sources.length<2||sources.some(x=>!x.file))return setMsg('Selecione ao menos dois arquivos ADIF.');setBusy(true);try{const payload=await Promise.all(sources.map(async x=>({source:x.name.trim().toUpperCase(),coverage:x.coverage,filename:x.file.name,content:await x.file.text()})));setResult(await api('/api/advanced/compare',{method:'POST',body:JSON.stringify({sources:payload,reference_index:reference})}))}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  return <div className="u-tool"><div className="u-tool-intro"><div><h2>Comparação avançada de ADIF</h2><p>Compare exports atuais, históricos ou de qualquer plataforma com a mesma lógica de pareamento usada pelo produto.</p></div><Button onClick={compare} disabled={busy}>{busy?'Comparando…':'Comparar fontes'}</Button></div>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'warn'}>{msg}</Notice>}<div className="u-adif-sources">{sources.map((x,i)=><article key={x.id} className={reference===i?'reference':''}><label className="u-radio"><input type="radio" checked={reference===i} onChange={()=>setReference(i)}/> referência</label><label><span>Nome</span><input value={x.name} onChange={e=>patch(i,{name:e.target.value})}/></label><label><span>Cobertura</span><select value={x.coverage} onChange={e=>patch(i,{coverage:e.target.value})}><option value="FULL_EXPORT">Export completo</option><option value="PARTIAL_EXPORT">Parcial</option><option value="FILTERED_EXPORT">Filtrado</option></select></label><label className="u-file wide">{x.file?.name||'Selecionar ADIF'}<input type="file" accept=".adi,.adif,.txt" onChange={e=>patch(i,{file:e.target.files?.[0]||null})}/></label>{sources.length>2&&<button className="u-text-danger" onClick={()=>setSources(v=>v.filter((_,j)=>j!==i))}>remover</button>}</article>)}</div><Button kind="secondary" small onClick={()=>setSources(v=>[...v,seed('FONTE_'+(v.length+1))])}>+ Adicionar fonte</Button>{result&&<><div className="u-metrics static"><div><span>Pareamentos</span><b>{fmt(result.summary?.matched_pairs)}</b></div><div><span>Ausências</span><b>{fmt(result.summary?.presence_differences)}</b></div><div><span>Campos</span><b>{fmt(result.summary?.field_differences)}</b></div><div><span>Revisar</span><b>{fmt(result.summary?.review_candidates)}</b></div></div><div className="u-compare-results">{(result.presence_differences||[]).slice(0,500).map((x,i)=><article key={'p'+i}><Badge tone={x.confidence==='HIGH'?'warn':'neutral'}>{x.confidence}</Badge><div><b>{x.call} · {x.date} {x.time}</b><p>Presente em {x.present_in}; ausente em {x.missing_in}. {x.reason}</p></div></article>)}{(result.field_differences||[]).slice(0,500).map((x,i)=><article key={'f'+i}><Badge tone="warn">{x.field}</Badge><div><b>{x.call} · {x.date}</b><p>{String(x.value_a??'∅')} → {String(x.value_b??'∅')} em {x.compared_source}</p></div></article>)}</div></>}</div>
}


function AwardMaster({status}){
  const [qrzFile,setQrzFile]=useState(null),[lotwFile,setLotwFile]=useState(null),[report,setReport]=useState(null),[busy,setBusy]=useState(''),[msg,setMsg]=useState(''),[advanced,setAdvanced]=useState(false)
  const providers=status?.providers||[]
  const qrzSnap=providers.find(x=>x.provider==='QRZ')?.snapshot||{}
  const lotwSnap=providers.find(x=>x.provider==='LOTW')?.snapshot||{}
  const lotwMeta=lotwSnap.metadata||{}
  const legacyLotw=lotwMeta.confirmations_only===true
  const snapshotReady=(qrzSnap.records||0)>0&&(lotwSnap.records||0)>0&&!legacyLotw
  const uploadReady=!!qrzFile&&!!lotwFile
  const ready=advanced?uploadReady:snapshotReady
  const stamp=v=>v?new Date(v).toLocaleString('pt-BR'):'Nunca'

  async function submit(kind,blob=false){
    if(!ready)throw new Error(advanced?'Selecione os exports completos do QRZ e do LoTW.':'Atualize QRZ e LoTW em Fontes antes de gerar o Master.')
    let response
    if(advanced){
      const path={preview:'/api/product/award-master/preview',export:'/api/product/award-master/export',audit:'/api/product/award-master/audit'}[kind]
      const form=new FormData();form.append('qrz',qrzFile);form.append('lotw',lotwFile)
      response=await fetch(path,{method:'POST',body:form})
    }else{
      const path={preview:'/api/product/award-master/snapshot/preview',export:'/api/product/award-master/snapshot/export',audit:'/api/product/award-master/snapshot/audit'}[kind]
      response=await fetch(path,{method:'POST'})
    }
    if(!response.ok){let detail=await response.text();try{detail=JSON.parse(detail)?.detail||detail}catch{};throw new Error(detail||'Falha ao montar o Master')}
    if(blob)return {blob:await response.blob(),disposition:response.headers.get('content-disposition')||''}
    return response.json()
  }
  async function preview(){setBusy('preview');setMsg('');setReport(null);try{const r=await submit('preview');setReport(r);const warnings=r.coverage?.warnings?.length||0;setMsg(r.safe_to_export?(warnings?`Validação concluída com ${warnings} alerta(s) auditado(s). A exportação segura continua liberada.`:'Validação concluída: nenhuma regressão crítica foi detectada.'):'O Master exige revisão antes da exportação. Veja os bloqueios abaixo.')}catch(e){setMsg('Erro: '+e.message)}finally{setBusy('')}}
  async function exportMaster(){if(!report?.safe_to_export)return;setBusy('export');setMsg('');try{const r=await submit('export',true);const m=/filename="?([^";]+)"?/i.exec(r.disposition);downloadBlob(m?.[1]||'PU2BRU-UltimateAAC-MASTER.adi',r.blob);setMsg('Master ADIF gerado. Nenhum log remoto foi alterado.')}catch(e){setMsg('Erro: '+e.message)}finally{setBusy('')}}
  async function exportAudit(){setBusy('audit');setMsg('');try{const r=await submit('audit',true);const m=/filename="?([^";]+)"?/i.exec(r.disposition);downloadBlob(m?.[1]||'PU2BRU-Award-Master-audit.csv',r.blob,'text/csv;charset=utf-8')}catch(e){setMsg('Erro: '+e.message)}finally{setBusy('')}}
  function clear(){setQrzFile(null);setLotwFile(null);setReport(null);setMsg('')}
  function toggleAdvanced(){setAdvanced(v=>!v);setReport(null);setMsg('')}
  const m=report?.coverage?.master||{},merge=report?.merge||{},conf=report?.conflicts||{},regs=report?.coverage?.blocking_regressions||[],warnings=report?.coverage?.warnings||[]
  return <div className="u-tool"><div className="u-tool-intro"><div><h2>Master ADIF para awards</h2><p>Usa por padrão os snapshots já carregados em Fontes. QRZ enriquece metadados; LoTW fornece o log completo e prevalece nos campos geográficos de award.</p></div><Badge tone={report?.safe_to_export?(warnings.length?'warn':'ok'):report?'warn':'neutral'}>{report?.safe_to_export?(warnings.length?'SAFE + AUDIT':'SAFE'):report?'REVISAR':'READ-ONLY'}</Badge></div>
    {!advanced&&<><Notice>Fluxo principal automático: atualize as fontes uma vez e gere o Master sem reenviar arquivos. Nada é gravado no QRZ, LoTW ou em outro logbook.</Notice><div className="u-master-snapshots"><div><span>QRZ carregado</span><b>{fmt(qrzSnap.records||0)} QSOs</b><small>{stamp(qrzSnap.downloaded_at)}</small></div><div className={legacyLotw?'warn':''}><span>LoTW carregado</span><b>{fmt(lotwSnap.records||0)} QSOs</b><small>{legacyLotw?'Snapshot antigo: somente QSLs — atualize em Fontes':`${fmt(lotwMeta.confirmed_qsos||0)} confirmados · ${stamp(lotwSnap.downloaded_at)}`}</small></div></div></>}
    {legacyLotw&&!advanced&&<Notice tone="warn">O LoTW desta instalação ainda está no formato antigo, somente confirmações. Volte em <b>Fontes</b>, atualize o LoTW e então gere o Master.</Notice>}
    {advanced&&<><Notice tone="warn">Modo avançado: use apenas se quiser testar arquivos externos diferentes dos snapshots já carregados.</Notice><div className="u-master-files"><label><span>Export QRZ</span><b>{qrzFile?.name||'Selecionar ADIF do QRZ'}</b><input type="file" accept=".adi,.adif,.txt" onChange={e=>{setQrzFile(e.target.files?.[0]||null);setReport(null)}}/></label><label><span>Export LoTW</span><b>{lotwFile?.name||'Selecionar lotwreport.adi'}</b><input type="file" accept=".adi,.adif,.txt" onChange={e=>{setLotwFile(e.target.files?.[0]||null);setReport(null)}}/></label></div></>}
    <div className="u-master-actions"><Button disabled={!ready||!!busy} onClick={preview}>{busy==='preview'?'Validando…':advanced?'Validar arquivos externos':'Validar fontes carregadas'}</Button><Button kind="secondary" disabled={!report?.safe_to_export||!!busy} onClick={exportMaster}>{busy==='export'?'Gerando…':'Baixar Master seguro'}</Button><Button kind="secondary" disabled={!report||!!busy} onClick={exportAudit}>{busy==='audit'?'Gerando…':'Baixar auditoria CSV'}</Button><button className="u-text-link" disabled={!!busy} onClick={toggleAdvanced}>{advanced?'usar fontes carregadas':'usar ADIFs externos (avançado)'}</button>{advanced&&<button className="u-text-danger" disabled={!!busy} onClick={clear}>limpar</button>}</div>
    {msg&&<Notice tone={msg.startsWith('Erro')?'error':report?.safe_to_export?'ok':'warn'}>{msg}</Notice>}
    {report&&<><div className="u-metrics static"><div><span>QSOs no Master</span><b>{fmt(merge.master_records)}</b><small>{fmt(merge.matched_pairs)} pareados</small></div><div><span>Grids únicos</span><b>{fmt(m.grids4)}</b><small>guardrail de cobertura</small></div><div><span>IOTAs</span><b>{fmt(m.iota)}</b><small>preservadas do melhor dado</small></div><div><span>Conflitos críticos</span><b>{fmt(conf.critical)}</b><small>{fmt(merge.ambiguous_groups)} grupo(s) ambíguo(s)</small></div></div>
      <div className="u-master-was"><div><span>FT8 · 10 m</span><b>{fmt(m.ft8_10m_states)}/50</b></div><div><span>FT8 · 12 m</span><b>{fmt(m.ft8_12m_states)}/50</b></div><div><span>FT8 · 15 m</span><b>{fmt(m.ft8_15m_states)}/50</b></div><div><span>Estados EUA</span><b>{fmt(m.us_states_all)}/50</b></div></div>
      {regs.length>0&&<Card title="Exportação bloqueada" subtitle="O arquivo não será liberado enquanto alguma dimensão crítica ficar abaixo da melhor fonte."><div className="u-master-problems">{regs.map((x,i)=><p key={i}><b>{x.metric}</b><span>QRZ {x.qrz} · LoTW {x.lotw} · Master {x.master}</span></p>)}</div></Card>}
      {warnings.length>0&&<Card title="Alertas auditados" subtitle="Há diferenças entre as fontes que não podem ser preservadas simultaneamente sem duplicar ou falsificar um QSO."><div className="u-master-problems">{warnings.map((x,i)=><p key={i}><b>{x.metric}</b><span>QRZ {x.qrz} · LoTW {x.lotw} · Master {x.master}</span></p>)}</div><p className="u-muted">Esses alertas não bloqueiam o Master porque a rotina prioriza integridade e mantém o conflito documentado no CSV.</p></Card>}
      {merge.ambiguous_groups>0&&<Notice tone="warn">{fmt(merge.ambiguous_groups)} grupo(s) têm mais de um pareamento possível. O QSO Manager preservou os registros separados e bloqueou a exportação segura para não inflar awards por duplicidade.</Notice>}
      <div className="u-master-foot"><span>SHA-256 do Master</span><code>{report.master_sha256}</code></div>
    </>}
  </div>
}

function ToolsPage({workspace,status,setGlobalMessage}){
  const [tab,setTab]=useState('compare'),[activity,setActivity]=useState([]),[diagnostics,setDiagnostics]=useState(null),[busy,setBusy]=useState(false)
  async function loadActivity(){try{setActivity(await api('/api/qso-manager/activity?limit=300'))}catch(e){setGlobalMessage('Erro: '+e.message)}}
  async function loadDiagnostics(){try{setDiagnostics(await api('/api/product/diagnostics'))}catch(e){setGlobalMessage('Erro: '+e.message)}}
  useEffect(()=>{if(tab==='activity')loadActivity();if(tab==='security')loadDiagnostics()},[tab])
  async function exportReference(){setBusy(true);try{const response=await fetch('/api/product/export/reference');if(!response.ok){let x={};try{x=await response.json()}catch{};throw new Error(x.detail||'Falha no backup QRZ')};const disposition=response.headers.get('content-disposition')||'';const m=/filename="?([^";]+)"?/i.exec(disposition);const count=response.headers.get('x-qso-records');downloadBlob(m?.[1]||`PU2BRU-QRZ-REFERENCIA-v${VERSION}.adi`,await response.blob());setGlobalMessage(`${fmt(count)} QSOs do QRZ exportados sem incorporar registros externos.`)}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy(false)}}
  async function exportAll(){if(!window.confirm('Esta união inclui observações externas ainda não pareadas no QRZ e não deve substituir seu log principal. Continuar?'))return;setBusy(true);try{const ids=await api('/api/qso-manager/ids?limit=50000');if(!ids.ids?.length)throw new Error('Nenhum QSO observado disponível');const filename=`PU2BRU-QSO-Manager-UNIAO-BRUTA-v${VERSION}.adi`;const response=await fetch('/api/qso-manager/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({logical_ids:ids.ids,filename})});if(!response.ok)throw new Error((await response.json()).detail||'Falha no export');downloadBlob(filename,await response.blob());setGlobalMessage(`${fmt(ids.ids.length)} observações exportadas para auditoria.`)}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy(false)}}
  async function exportDiagnostics(){const d=diagnostics||await api('/api/product/diagnostics');downloadBlob('PU2BRU-QSO-Manager-diagnostico.json',JSON.stringify(d,null,2),'application/json;charset=utf-8')}
  const tabs=[['compare','Comparar ADIF'],['award','Master para awards'],['backup','Importar & exportar'],['activity','Atividade'],['security','Segurança & diagnóstico']]
  return <><PageHead eyebrow="FERRAMENTAS" title="Tudo que é avançado, em um único lugar." subtitle="O fluxo principal fica limpo. Auditoria, exportações e diagnóstico continuam acessíveis sem espalhar a navegação."/><div className="u-tool-tabs">{tabs.map(x=><button key={x[0]} className={tab===x[0]?'active':''} onClick={()=>setTab(x[0])}>{x[1]}</button>)}</div>{tab==='compare'&&<AdvancedCompare/>}{tab==='award'&&<AwardMaster status={status}/>}{tab==='backup'&&<div className="u-two"><Card title="Backup fiel da referência" subtitle="Exporta somente o snapshot do QRZ. É a opção segura para restauração e migração."><div className="u-backup-big"><b>{fmt(workspace?.summary?.reference_qsos)}</b><span>QSOs no QRZ</span></div><Button disabled={busy} onClick={exportReference}>{busy?'Gerando…':'Baixar backup do QRZ'}</Button><Button kind="secondary" disabled={busy} onClick={exportAll}>Exportar união bruta para auditoria</Button></Card><Card title="Fontes manuais" subtitle="HRD e HRDLog usam ADIF quando uma leitura remota completa não existe."><div className="u-source-mini">{(status?.providers||[]).filter(p=>['HRD','HRDLOG'].includes(p.provider)).map(p=><div key={p.provider}><i className={p.configured?'ok':''}>{short(p.provider)}</i><span><b>{p.label}</b><small>{p.participates===false?'fora do escopo · ':''}{fmt(p.snapshot?.records)} registros · {dt(p.snapshot?.downloaded_at)}</small></span></div>)}</div><p className="u-muted">A importação é feita na página Fontes, onde a cobertura e o efeito de cada arquivo ficam explícitos.</p></Card></div>}{tab==='activity'&&<Card title="Histórico de atividade" subtitle="Sincronizações, exportações e ações em lote registradas pelo workspace.">{!activity.length?<Empty title="Sem atividade registrada"/>:<div className="u-activity">{activity.map((x,i)=><article key={x.id||i}><Badge>{x.kind||x.type||'EVENTO'}</Badge><div><b>{x.summary||x.message||x.action||'Atividade'}</b><small>{dt(x.at||x.created_at||x.timestamp)}</small></div></article>)}</div>}</Card>}{tab==='security'&&<div className="u-two"><Card title="Credenciais" subtitle="Nenhuma chave é exposta em texto aberto pela interface."><div className="u-security-list">{(status?.providers||[]).filter(p=>p.source_kind!=='local_adif').map(p=><div key={p.provider}><span className={'u-dot '+(p.configured?'ok':'')}/><b>{p.label}</b><small>{p.configured?'configurada':'não configurada'}</small></div>)}</div></Card><Card title="Diagnóstico do produto" subtitle="Estado mínimo para suporte e validação, sem incluir segredos."><div className="u-diagnostic"><p><span>Versão</span><b>{diagnostics?.version||VERSION}</b></p><p><span>Windows</span><b>{diagnostics?.windows_production_ready?'produção':'verificar'}</b></p><p><span>Android</span><b>{diagnostics?.android_stage||'preview'}</b></p><p><span>QSOs no QRZ</span><b>{fmt(diagnostics?.workspace?.summary?.reference_qsos)}</b></p><p><span>Observações lógicas</span><b>{fmt(diagnostics?.workspace?.summary?.observed_logical_qsos)}</b></p></div><Button kind="secondary" onClick={exportDiagnostics}>Baixar diagnóstico JSON</Button></Card></div>}</>
}

export default function App900(){
  const [page,setPage]=useState('overview'),[boot,setBoot]=useState({status:{providers:[]},dashboard:{summary:{}},workspace:{summary:{}},issues:{items:[],total:0,counts:{}},qsl:{summary:{}}}),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[syncJob,setSyncJob]=useState(null),[indexing,setIndexing]=useState(true)
  async function refresh(){const b=await api('/api/product/bootstrap');setBoot(b);setIndexing(false);return b}
  useEffect(()=>{let timer;api('/api/product/status').then(status=>setBoot(v=>({...v,status}))).catch(()=>{}).finally(()=>{timer=setTimeout(()=>refresh().catch(e=>{setIndexing(false);setMessage('Erro ao analisar o workspace: '+e.message)}),300)});api('/api/product/sync-all/active').then(r=>{if(r?.active&&r.job){setSyncJob(r.job);setBusy(true);pollSyncJob(r.job.job_id)}}).catch(()=>{})},[])
  async function pollSyncJob(jobId){
    try{
      while(true){
        await new Promise(resolve=>setTimeout(resolve,550))
        const job=await api('/api/product/sync-all/'+encodeURIComponent(jobId))
        setSyncJob(job)
        if(['completed','completed_with_errors'].includes(job.status)){
          const failed=Number(job.failed||0)
          setMessage(failed?`Atualização concluída em ${words(job.succeeded,'fonte')}; ${words(failed,'falha')}.`:`Atualização concluída em ${words(job.succeeded,'fonte')}.`)
          await refresh()
          setBusy(false)
          return
        }
      }
    }catch(e){setMessage('Erro ao acompanhar atualização: '+e.message);setBusy(false)}
  }
  async function syncProvider(provider){
    if(busy)return
    setBusy(true);setMessage(provider+': iniciando download em segundo plano…')
    try{
      const job=await api('/api/product/sync/'+encodeURIComponent(provider)+'/start',{method:'POST',body:'{}'})
      setSyncJob(job)
      if(['completed','completed_with_errors'].includes(job.status)){setBusy(false);return}
      await pollSyncJob(job.job_id)
    }catch(e){setMessage('Erro: '+e.message);setBusy(false);throw e}
  }
  async function syncAll(){
    if(busy)return
    setBusy(true);setMessage('Iniciando downloads paralelos…')
    try{
      const job=await api('/api/product/sync-all/start',{method:'POST',body:'{}'})
      setSyncJob(job)
      if(['completed','completed_with_errors'].includes(job.status)){
        setMessage('Nenhuma fonte remota configurada para atualizar.')
        setBusy(false)
        return
      }
      await pollSyncJob(job.job_id)
    }catch(e){setMessage('Erro: '+e.message);setBusy(false)}
  }
  async function refreshIssues({page=1,pageSize=50,kind='ALL',q=''}={}){try{const p=new URLSearchParams({page:String(page),page_size:String(pageSize),kind,q});const issues=await api('/api/product/issues?'+p.toString());setBoot(v=>({...v,issues}));return issues}catch(e){setMessage('Erro: '+e.message);return null}}
  async function refreshQsl({page=1,pageSize=100,service='',q=''}={}){try{setBoot(v=>({...v,qsl:{...(v.qsl||{}),lazy:false,loading:true}}));const p=new URLSearchParams({page:String(page),page_size:String(pageSize),service,q});const [qsl,issues]=await Promise.all([api('/api/product/qsl?'+p.toString()),api('/api/product/issues?page=1&page_size=50')]);setBoot(v=>({...v,qsl:{...qsl,lazy:false,loading:false},issues}));return qsl}catch(e){setBoot(v=>({...v,qsl:{ready:false,lazy:false,loading:false,summary:{},proposals:[],services:[],pagination:{page:1,pages:1,total:0,filtered_total:0}}}));setMessage('Erro: '+e.message);return null}}
  function nav(n){setPage(n);if(n==='qsl'&&boot.qsl?.lazy)refreshQsl()}
  async function refreshAfterQslChange(params){await refresh();await refreshQsl(params)}
  useEffect(()=>{if(page==='qsl'&&boot.qsl?.lazy)refreshQsl()},[page,boot.qsl?.lazy])
  return <div className="u-app"><aside className="u-sidebar"><div className="u-brand"><div className="u-brand-mark">PU2BRU</div><span><b>QSO Manager</b><small>PU2BRU · v{VERSION}</small></span></div><nav>{NAV.map(([id,label,icon])=><button key={id} className={page===id?'active':''} onClick={()=>nav(id)}><i>{icon}</i><span>{label}</span>{id==='inbox'&&boot?.issues?.total>0&&<em>{boot.issues.total>99?'99+':boot.issues.total}</em>}</button>)}</nav><div className="u-sidebar-foot"><span className={boot?'ok':''}/><div><b>{indexing?'Preparando índice':'Workspace pronto'}</b><small>{indexing?'Fontes locais disponíveis':`${fmt(boot.workspace?.summary?.reference_qsos)} QSOs no QRZ`}</small></div></div></aside><header className="u-mobile-top"><div><b>QSO Manager</b><small>PU2BRU · v{VERSION}</small></div><Button small disabled={busy} onClick={syncAll}>↻</Button></header><main className="u-main">{message&&<Notice tone={message.startsWith('Erro')?'error':'info'}>{message}<button aria-label="Fechar aviso" className="u-close" onClick={()=>setMessage('')}>×</button></Notice>}{!boot&&<div className="u-loading-screen"><div className="u-pulse">PU2BRU</div><h2>Montando seu workspace…</h2><p>Validando banco local, frontend e fontes.</p></div>}{boot&&<>{indexing&&<Notice>Interface disponível. Reconciliando os QSOs ativos em segundo plano…</Notice>}{page==='overview'&&<Overview boot={boot} navigate={nav} syncAll={syncAll} busy={busy} syncJob={syncJob}/>} {page==='log'&&<LogPage workspace={boot.workspace}/>} {page==='inbox'&&<InboxPage issues={boot.issues} onRefresh={refreshIssues}/>} {page==='integrity'&&<IntegrityPage/>} {page==='qsl'&&<QslPage qsl={boot.qsl} onRefresh={refreshQsl} onChanged={refreshAfterQslChange} setGlobalMessage={setMessage}/>} {page==='sources'&&<SourcesPage status={boot.status} onChanged={refresh} setGlobalMessage={setMessage} onSyncAll={syncAll} onSyncProvider={syncProvider} syncJob={syncJob} globalBusy={busy}/>} {page==='tools'&&<ToolsPage workspace={boot.workspace} status={boot.status} setGlobalMessage={setMessage}/>}</>}</main><nav className="u-bottom">{NAV.map(([id,label,icon])=><button key={id} className={page===id?'active':''} onClick={()=>nav(id)}><i>{icon}</i><span>{label}</span>{id==='inbox'&&boot?.issues?.total>0&&<em>{boot.issues.total>99?'99+':boot.issues.total}</em>}</button>)}</nav></div>
}
