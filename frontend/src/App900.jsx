import React, { useEffect, useMemo, useState } from 'react'

const VERSION = '1.0.1'
const NAV = [
  ['overview','Visão geral','⌂'],
  ['log','Log','◎'],
  ['inbox','Pendências','!'],
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
const fmt = n => Number(n||0).toLocaleString('pt-BR')
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
function Badge({children,tone='neutral'}){return <span className={'u-badge '+tone}>{children}</span>}
function Empty({title='Nada por aqui',children}){return <div className="u-empty"><b>{title}</b>{children&&<p>{children}</p>}</div>}
function Notice({children,tone='info'}){return <div className={'u-notice '+tone}>{children}</div>}
function PageHead({eyebrow,title,subtitle,action}){return <div className="u-pagehead"><div><small>{eyebrow}</small><h1>{title}</h1>{subtitle&&<p>{subtitle}</p>}</div>{action}</div>}
function Card({title,subtitle,action,children,className=''}){return <section className={'u-card '+className}><header><div><h3>{title}</h3>{subtitle&&<p>{subtitle}</p>}</div>{action}</header>{children}</section>}

function ConnectionModal({source,onClose,onChanged}){
  const key=source.provider==='EQSL_INBOX'?'EQSL':source.provider
  const [values,setValues]=useState(source.credentials||{}),[busy,setBusy]=useState(false),[msg,setMsg]=useState('')
  async function save(test){setBusy(true);setMsg('');try{await api('/api/product/connections/'+key,{method:'PUT',body:JSON.stringify({values})});if(test){const r=await api('/api/product/connections/'+source.provider+'/test',{method:'POST',body:'{}'});setMsg(r.message||r.status||`Conexão validada${r.records!=null?` · ${fmt(r.records)} registros`:''}.`)}else setMsg('Configuração salva.');await onChanged()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  async function disconnect(){if(!window.confirm(`Desconectar ${source.label}? O snapshot local será preservado.`))return;setBusy(true);try{await api('/api/product/connections/'+key,{method:'DELETE'});await onChanged();onClose()}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  return <div className="u-modal-bg" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><div className="u-modal"><div className="u-modal-title"><div><small>CONEXÃO SEGURA</small><h2>{source.label}</h2></div><button onClick={onClose}>×</button></div>{source.provider==='EQSL_INBOX'&&<Notice>O Inbox compartilha a conta configurada no eQSL OutBox.</Notice>}<div className="u-fields">{(PROVIDER_FIELDS[key]||[]).map(([name,label,type,help])=><label key={name}><span>{label}</span><input type={type} value={values[name]||''} placeholder={source.credentials?.[name]||''} onChange={e=>setValues(v=>({...v,[name]:e.target.value}))}/><small>{help}</small></label>)}</div>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'ok'}>{msg}</Notice>}<div className="u-modal-actions"><div>{source.configured&&<Button kind="danger" disabled={busy} onClick={disconnect}>Desconectar</Button>}</div><div><Button kind="secondary" disabled={busy} onClick={()=>save(false)}>Salvar</Button><Button disabled={busy} onClick={()=>save(true)}>{busy?'Validando…':'Salvar e testar'}</Button></div></div></div></div>
}

function QsoDrawer({logicalId,onClose}){
  const [data,setData]=useState(null),[msg,setMsg]=useState('')
  useEffect(()=>{let alive=true;api('/api/product/log/'+encodeURIComponent(logicalId)).then(x=>alive&&setData(x)).catch(e=>alive&&setMsg(e.message));return()=>{alive=false}},[logicalId])
  return <div className="u-drawer-bg" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><aside className="u-drawer"><div className="u-drawer-head"><div><small>DETALHE DO QSO</small><h2>{data?.call||'Carregando…'}</h2>{data&&<p>{data.date} {data.time} · {data.band} · {data.mode}</p>}</div><button onClick={onClose}>×</button></div>{msg&&<Notice tone="error">{msg}</Notice>}{data&&<><div className="u-detail-kpis"><div><span>Fontes</span><b>{data.providers?.length||0}</b></div><div><span>Ausente em</span><b>{data.missing_in?.length||0}</b></div><div><span>Diferenças</span><b>{data.difference_fields?.length||0}</b></div></div><div className="u-badges">{data.providers?.map(p=><Badge key={p} tone={p==='QRZ'?'truth':'ok'}>{short(p)}</Badge>)}{data.missing_in?.map(p=><Badge key={p} tone="warn">− {short(p)}</Badge>)}</div>{data.difference_fields?.length>0&&<Notice tone="warn">Campos divergentes: {data.difference_fields.join(', ')}</Notice>}<div className="u-records">{Object.entries(data.source_records||{}).map(([provider,payload])=><section key={provider}><header><Badge tone={provider==='QRZ'?'truth':'neutral'}>{provider}</Badge><span>{Object.keys(payload.record||{}).length} campos</span></header><div>{Object.entries(payload.record||{}).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=><p key={k}><span>{k}</span><code>{String(v)}</code></p>)}</div></section>)}</div></>}</aside></div>
}

function Overview({boot,navigate,syncAll,busy}){
  const summary=boot?.dashboard?.summary||{}, counts=boot?.issues?.counts||{}, providers=boot?.status?.providers||[]
  const configured=providers.filter(p=>p.configured).length
  return <><div className="u-hero"><div><small>SEU LOG, UMA ÚNICA VERDADE OPERACIONAL</small><h1>{fmt(summary.logical_qsos)} QSOs consolidados</h1><p>QRZ, WRL, Club Log, eQSL, LoTW, HRDLog.net e ADIF do Ham Radio Deluxe em uma jornada única — sem trocar de “modo” dentro do sistema.</p><div className="u-hero-actions"><Button onClick={()=>navigate('inbox')}>Revisar pendências</Button><Button kind="secondary" disabled={busy} onClick={syncAll}>{busy?'Atualizando…':'Atualizar tudo'}</Button></div></div><div className="u-health"><span>Estado do workspace</span><b>{configured}/{providers.length}</b><small>fontes configuradas/carregadas</small><i className={configured?'ok':''}/></div></div><div className="u-metrics"><button onClick={()=>navigate('log')}><span>QSOs multifonte</span><b>{fmt(summary.multi_source)}</b><small>presentes em mais de uma fonte</small></button><button onClick={()=>navigate('inbox')}><span>Ausências</span><b>{fmt(counts.missing)}</b><small>fonte carregada sem o QSO</small></button><button onClick={()=>navigate('inbox')}><span>Divergências</span><b>{fmt(counts.differences)}</b><small>campos que pedem revisão</small></button><button onClick={()=>navigate('qsl')}><span>QSL online</span><b>{fmt(counts.qsl)}</b><small>eQSL/LoTW detectadas</small></button></div><div className="u-two"><Card title="Próximas ações" subtitle="O sistema prioriza decisões, não telas."><div className="u-actions-list"><button onClick={()=>navigate('inbox')}><i>01</i><span><b>Resolver o que está divergente</b><small>{fmt((boot?.issues?.total)||0)} ocorrências na caixa de entrada</small></span><em>›</em></button><button onClick={()=>navigate('sources')}><i>02</i><span><b>Manter as fontes frescas</b><small>Veja autenticação, cobertura e última atualização</small></span><em>›</em></button><button onClick={()=>navigate('tools')}><i>03</i><span><b>Auditar e proteger o log</b><small>Comparação ADIF, exportação, backup e atividade</small></span><em>›</em></button></div></Card><Card title="Cobertura das fontes" subtitle="Um resumo simples do que participa da comparação."><div className="u-source-mini">{providers.map(p=><button key={p.provider} onClick={()=>navigate('sources')}><i className={p.configured?'ok':''}>{short(p.provider)}</i><span><b>{p.label}</b><small>{p.configured?`${fmt(p.snapshot?.records)} registros`:'não configurado'}</small></span></button>)}</div></Card></div></>
}

function LogPage({workspace}){
  const [data,setData]=useState({items:[],total:0,page:1,pages:1}),[filters,setFilters]=useState({q:'',band:'',mode:'',provider:'',missing_in:'',differences:'',duplicate:'',confirmed:''}),[page,setPage]=useState(1),[loading,setLoading]=useState(false),[msg,setMsg]=useState(''),[detail,setDetail]=useState(null),[selected,setSelected]=useState(new Set())
  const query=()=>{const p=new URLSearchParams({page:String(page),page_size:'100'});Object.entries(filters).forEach(([k,v])=>v&&p.set(k,v));return p.toString()}
  async function load(){setLoading(true);setMsg('');try{setData(await api('/api/product/log?'+query()))}catch(e){setMsg('Erro: '+e.message)}finally{setLoading(false)}}
  useEffect(()=>{const t=setTimeout(load,160);return()=>clearTimeout(t)},[page,filters.q,filters.band,filters.mode,filters.provider,filters.missing_in,filters.differences,filters.duplicate,filters.confirmed])
  useEffect(()=>setPage(1),[filters.q,filters.band,filters.mode,filters.provider,filters.missing_in,filters.differences,filters.duplicate,filters.confirmed])
  function toggle(id){setSelected(prev=>{const n=new Set(prev);n.has(id)?n.delete(id):n.add(id);return n})}
  async function selectAll(){try{const p=new URLSearchParams();Object.entries(filters).forEach(([k,v])=>v&&p.set(k,v));p.set('limit','50000');const r=await api('/api/qso-manager/ids?'+p.toString());setSelected(new Set(r.ids||[]));setMsg(`${fmt(r.ids?.length)} QSO(s) selecionados.`)}catch(e){setMsg('Erro: '+e.message)}}
  async function exportSelected(){if(!selected.size)return;try{const response=await fetch('/api/qso-manager/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({logical_ids:[...selected]})});if(!response.ok){const x=await response.json();throw new Error(x.detail||'Falha no export')};const blob=await response.blob();downloadBlob('PU2BRU-QSO-Manager-export.adi',blob);setMsg(`${fmt(selected.size)} QSO(s) exportados.`)}catch(e){setMsg('Erro: '+e.message)}}
  const opts=workspace||{}
  return <><PageHead eyebrow="LOG CONSOLIDADO" title="Um QSO. Todas as fontes." subtitle="Pesquise, filtre e abra qualquer contato para entender exatamente de onde cada campo veio." action={<Button kind="secondary" onClick={selectAll}>Selecionar todos</Button>}/>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'info'}>{msg}</Notice>}<section className="u-filterbar"><div className="u-search"><span>⌕</span><input value={filters.q} onChange={e=>setFilters(v=>({...v,q:e.target.value.toUpperCase()}))} placeholder="Indicativo, país, grid, comentário…"/></div><select value={filters.band} onChange={e=>setFilters(v=>({...v,band:e.target.value}))}><option value="">Todas as bandas</option>{(opts.bands||[]).map(x=><option key={x}>{x}</option>)}</select><select value={filters.mode} onChange={e=>setFilters(v=>({...v,mode:e.target.value}))}><option value="">Todos os modos</option>{(opts.modes||[]).map(x=><option key={x}>{x}</option>)}</select><select value={filters.provider} onChange={e=>setFilters(v=>({...v,provider:e.target.value}))}><option value="">Qualquer fonte</option>{(opts.providers||[]).map(x=><option key={x}>{x}</option>)}</select><select value={filters.missing_in} onChange={e=>setFilters(v=>({...v,missing_in:e.target.value}))}><option value="">Sem filtro de ausência</option>{(opts.available_providers||[]).map(x=><option key={x}>{x}</option>)}</select><select value={filters.differences} onChange={e=>setFilters(v=>({...v,differences:e.target.value}))}><option value="">Diferenças: todas</option><option value="true">Com diferenças</option><option value="false">Sem diferenças</option></select></section>{selected.size>0&&<div className="u-selection"><span><b>{fmt(selected.size)}</b> selecionado(s)</span><div><Button small kind="secondary" onClick={exportSelected}>Exportar ADIF</Button><button onClick={()=>setSelected(new Set())}>Limpar</button></div></div>}<div className="u-log-list">{loading&&!data.items?.length?<div className="u-loading">Carregando log…</div>:(data.items||[]).map(row=><article key={row.logical_id} className={selected.has(row.logical_id)?'selected':''}><input type="checkbox" checked={selected.has(row.logical_id)} onChange={()=>toggle(row.logical_id)}/><button className="u-log-main" onClick={()=>setDetail(row.logical_id)}><span><b>{row.call}</b><small>{row.date} · {row.time?.slice(0,5)} UTC</small></span><span className="u-band"><b>{row.band||'—'}</b><small>{row.mode||'—'} {row.freq?`· ${row.freq}`:''}</small></span><span className="u-place"><b>{row.country||'—'}</b><small>{row.grid||row.state||'sem localização'}</small></span><span className="u-badges">{row.providers?.map(p=><Badge key={p} tone={p==='QRZ'?'truth':'ok'}>{short(p)}</Badge>)}{row.missing_in?.slice(0,3).map(p=><Badge key={p} tone="warn">−{short(p)}</Badge>)}</span><span className="u-row-status">{row.duplicate&&<Badge tone="danger">dup</Badge>}{row.difference_count>0&&<Badge tone="warn">{row.difference_count} dif.</Badge>}{row.confirmed&&<Badge tone="ok">QSL</Badge>}<em>›</em></span></button></article>)}</div>{!loading&&!data.items?.length&&<Empty title="Nenhum QSO encontrado">Ajuste os filtros ou atualize as fontes.</Empty>}<div className="u-pager"><Button kind="secondary" small disabled={page<=1} onClick={()=>setPage(p=>p-1)}>← Anterior</Button><span>Página <b>{data.page||page}</b> de {data.pages||1} · {fmt(data.total)} resultados</span><Button kind="secondary" small disabled={page>=(data.pages||1)} onClick={()=>setPage(p=>p+1)}>Próxima →</Button></div>{detail&&<QsoDrawer logicalId={detail} onClose={()=>setDetail(null)}/>}</>
}

function InboxPage({issues,onRefresh}){
  const [filter,setFilter]=useState('ALL');const items=issues?.items||[];const visible=filter==='ALL'?items:items.filter(x=>x.type===filter);const counts=issues?.counts||{}
  return <><PageHead eyebrow="CAIXA DE ENTRADA" title="Só o que exige atenção." subtitle="Ausências, divergências, duplicidades e confirmações ficam na mesma fila de trabalho." action={<Button kind="secondary" onClick={onRefresh}>Recalcular</Button>}/><div className="u-chips">{[['ALL','Tudo',issues?.total],['MISSING','Ausentes',counts.missing],['DIFFERENCE','Divergências',counts.differences],['DUPLICATE','Duplicidades',counts.duplicates],['QSL','QSL',counts.qsl]].map(x=><button key={x[0]} className={filter===x[0]?'active':''} onClick={()=>setFilter(x[0])}>{x[1]} <b>{fmt(x[2])}</b></button>)}</div><div className="u-inbox">{visible.map((x,i)=><article key={i}><i className={x.type.toLowerCase()}>{x.type==='QSL'?'✓':x.type==='MISSING'?'−':'!'}</i><div><h3>{x.call} <span>{x.band} · {x.mode}</span></h3><p>{x.date} {x.time?.slice(0,5)} · {x.message}</p><div className="u-badges">{(x.sources||[]).map(p=><Badge key={p}>{short(p)}</Badge>)}{(x.missing_in||[]).map(p=><Badge key={p} tone="warn">−{short(p)}</Badge>)}</div></div></article>)}</div>{!visible.length&&<Empty title="Fila limpa">Nenhuma ocorrência neste filtro.</Empty>}</>
}

function QslPage({qsl,onRefresh,onChanged,setGlobalMessage}){
  const s=qsl?.summary||{}
  const [syncPlan,setSyncPlan]=useState(null)
  const [syncBusy,setSyncBusy]=useState('')
  const dateLabel=value=>{const v=String(value||'').replace(/-/g,'');return /^\d{8}$/.test(v)?v.slice(6,8)+'/'+v.slice(4,6)+'/'+v.slice(0,4):(value||'—')}

  async function analyzeEqslQrz(){
    setSyncBusy('plan')
    try{
      const plan=await api('/api/product/qsl/eqsl-qrz/plan?refresh=true')
      setSyncPlan(plan)
      const n=plan.summary?.safe_updates||0
      setGlobalMessage(n?'eQSL → QRZ: '+fmt(n)+' atualização(ões) segura(s) pronta(s) para revisão.':'eQSL → QRZ: nenhuma atualização segura pendente.')
      await onRefresh()
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
      await onChanged()
      const plan=await api('/api/product/qsl/eqsl-qrz/plan')
      setSyncPlan(plan)
    }catch(e){setGlobalMessage('Erro: '+e.message)}
    finally{setSyncBusy('')}
  }

  const ps=syncPlan?.summary||{}
  const manualTotal=Number(ps.manual_review||0)+Number(ps.date_conflicts||0)
  const diagnosticTotal=Number(ps.collisions||0)+Number(ps.missing_explicit_date||0)
  return <><PageHead eyebrow="CENTRAL DE QSL" title="Confirmações com evidência." subtitle="eQSL Inbox e LoTW são tratados como fontes de confirmação. A data do QSO nunca é inventada como data de recebimento." action={<Button kind="secondary" onClick={onRefresh}>Atualizar análise</Button>}/>
    <div className="u-metrics static"><div><span>Grupos confirmados</span><b>{fmt(s.matched_confirmation_groups)}</b></div><div><span>Propostas</span><b>{fmt(s.actionable_proposals)}</b></div><div><span>Sem par</span><b>{fmt(s.unmatched_evidence)}</b></div><div><span>Conflitos</span><b>{fmt(s.date_conflicts)}</b></div></div>
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
    {!qsl?.ready?<Empty title="Ainda sem evidência online">Atualize QRZ e ao menos eQSL Inbox ou LoTW.</Empty>:<div className="u-qsl-list">{(qsl.proposals||[]).map((p,i)=><article key={i}><div><h3>{p.qso?.call}</h3><p>{p.qso?.date} · {p.qso?.band} · {p.qso?.mode}</p></div><Badge tone="ok">{p.service}</Badge><div><b>{Object.entries(p.changes||{}).map(([k,v])=>k+'='+v).join(' · ')}</b><small>{p.reason}</small></div></article>)}</div>}</>
}
function SourcesPage({status,onChanged,setGlobalMessage}){
  const [config,setConfig]=useState(null),[busy,setBusy]=useState(''),[jobs,setJobs]=useState({})
  const providers=status?.providers||[]
  const syncable=providers.filter(p=>p.configured&&p.capabilities?.read&&p.source_kind!=='local_adif')
  const running=Object.values(jobs).filter(j=>j&&['queued','running'].includes(j.status))
  const activeIds=running.map(j=>j.job_id).sort().join(',')
  const visibleJobs=Object.values(jobs).filter(Boolean)
  const overall=visibleJobs.length?Math.round(visibleJobs.reduce((n,j)=>n+Number(j.progress||0),0)/visibleJobs.length):0

  useEffect(()=>{let alive=true;api('/api/product/sync-jobs-active').then(x=>{if(alive)setJobs(x||{})}).catch(()=>{});return()=>{alive=false}},[])

  useEffect(()=>{
    if(!activeIds)return
    let alive=true
    async function poll(){
      const current=Object.values(jobs).filter(j=>j&&['queued','running'].includes(j.status))
      if(!current.length)return
      const results=await Promise.all(current.map(async j=>{try{return await api('/api/product/sync-jobs/'+j.job_id)}catch(e){return {...j,status:'failed',phase:'failed',progress:100,error:e.message,message:'Falha ao consultar progresso.'}}}))
      if(!alive)return
      setJobs(prev=>{const next={...prev};results.forEach(j=>{next[j.provider]=j});return next})
      if(results.every(j=>!['queued','running'].includes(j.status))){
        const failed=results.filter(j=>j.status==='failed')
        await onChanged()
        setGlobalMessage(failed.length?'Atualização concluída com '+failed.length+' falha(s). Os snapshots anteriores foram preservados.':results.length+' fonte(s) atualizada(s) em paralelo.')
      }
    }
    poll()
    const timer=setInterval(poll,700)
    return()=>{alive=false;clearInterval(timer)}
  },[activeIds])

  async function sync(p){
    setBusy(p)
    try{
      const job=await api('/api/product/sync-jobs/'+p,{method:'POST',body:'{}'})
      setJobs(prev=>({...prev,[p]:job}))
    }catch(e){setGlobalMessage('Erro: '+e.message)}
    finally{setBusy('')}
  }

  async function syncAll(){
    setBusy('ALL')
    try{
      const result=await api('/api/product/sync-jobs-all',{method:'POST',body:'{}'})
      const next={};(result.jobs||[]).forEach(job=>{next[job.provider]=job})
      setJobs(prev=>({...prev,...next}))
      setGlobalMessage(result.started?result.started+' fonte(s) iniciada(s) em paralelo. Acompanhe o progresso abaixo.':'Nenhuma fonte remota configurada para atualizar.')
    }catch(e){setGlobalMessage('Erro: '+e.message)}
    finally{setBusy('')}
  }

  async function importAdif(p,file){if(!file)return;setBusy(p);try{const r=await api('/api/product/sources/'+p+'/adif',{method:'PUT',body:JSON.stringify({content:await file.text(),filename:file.name})});setGlobalMessage(p+': '+fmt(r.records)+' QSOs importados de '+file.name+'.');await onChanged()}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}
  async function updateHrdlog(){setBusy('HRDLOG');try{const plan=await api('/api/product/hrdlog/plan?limit=500');if(!plan.safe_missing){setGlobalMessage('HRDLog já está alinhado com o estado conhecido do QRZ.');return}if(!window.confirm('Enviar '+plan.candidates.length+' QSO(s) seguros ao HRDLog.net?'))return;const r=await api('/api/product/hrdlog/push',{method:'POST',body:JSON.stringify({confirm:true,limit:500})});setGlobalMessage('HRDLog: '+fmt(r.sent_or_already_remote)+' atualizados; '+fmt(r.errors?.length)+' erro(s).');await onChanged()}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}
  async function clear(p){if(!window.confirm('Apagar somente o snapshot local de '+p+'? Nada será removido na plataforma remota.'))return;setBusy(p);try{await api('/api/product/sources/'+p+'/snapshot',{method:'DELETE'});setGlobalMessage(p+': snapshot local removido.');await onChanged()}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy('')}}

  return <><PageHead eyebrow="FONTES" title="Downloads paralelos e acompanháveis." subtitle="Atualize várias fontes ao mesmo tempo. Cada download roda de forma independente, com progresso por etapa e preservação do snapshot anterior em caso de falha." action={<Button disabled={busy==='ALL'||!!running.length||!syncable.length} onClick={syncAll}>{running.length?'Atualizando…':'Atualizar todas'}</Button>}/>
    {visibleJobs.length>0&&<section className="u-sync-overall"><div><span>Progresso geral</span><b>{overall}%</b><small>{running.length?running.length+' fonte(s) em andamento':'última atualização concluída'}</small></div><div className="u-progress"><i style={{width:overall+'%'}}/></div></section>}
    <div className="u-source-grid">{providers.map(p=>{const job=jobs[p.provider],isRunning=job&&['queued','running'].includes(job.status);return <Card key={p.provider} title={p.label} subtitle={p.note} action={<span className={'u-dot '+(p.configured?'ok':'')}/>}><div className="u-source-number"><b>{fmt(p.snapshot?.records)}</b><span>registros conhecidos</span><small>Atualizado: {dt(p.snapshot?.downloaded_at)}</small></div><div className="u-source-tags"><Badge>{p.source_kind}</Badge>{p.comparison_role==='qsl_evidence'&&<Badge tone="ok">evidência QSL</Badge>}{p.provider==='QRZ'&&<Badge tone="truth">referência</Badge>}</div>
      {job&&<div className={'u-source-progress '+job.status}><div><span>{job.status==='failed'?'Falhou':job.status==='succeeded'?'Concluído':job.phase==='downloading'?'Baixando':job.phase==='validating'?'Validando':job.phase==='saving'?'Salvando':'Conectando'}</span><b>{Math.round(Number(job.progress||0))}%</b></div><div className={'u-progress '+(isRunning?'active':'')}><i style={{width:Math.max(2,Number(job.progress||0))+'%'}}/></div><small>{job.error||job.message}{job.records!=null?' · '+fmt(job.records)+' registros':''}</small></div>}
      <div className="u-source-actions">{!['HRD'].includes(p.provider)&&<Button kind="secondary" small disabled={isRunning} onClick={()=>setConfig(p)}>{p.configured?'Conexão':'Configurar'}</Button>}{p.provider==='HRD'&&<label className="u-file">{p.configured?'Substituir ADIF':'Importar ADIF'}<input type="file" accept=".adi,.adif,.txt" onChange={e=>{importAdif('HRD',e.target.files?.[0]);e.target.value=''}}/></label>}{p.provider==='HRDLOG'&&<label className="u-file">Reconciliar ADIF<input type="file" accept=".adi,.adif,.txt" onChange={e=>{importAdif('HRDLOG',e.target.files?.[0]);e.target.value=''}}/></label>}{p.provider==='HRDLOG'?<Button small disabled={busy===p.provider||!p.configured||!p.snapshot?.downloaded_at} onClick={updateHrdlog}>{busy===p.provider?'Processando…':'Atualizar online'}</Button>:p.capabilities?.read&&p.source_kind!=='local_adif'&&<Button small disabled={busy===p.provider||!p.configured||isRunning} onClick={()=>sync(p.provider)}>{isRunning?'Atualizando…':'Atualizar'}</Button>}{p.snapshot?.records>0&&<button className="u-text-danger" disabled={busy===p.provider||isRunning} onClick={()=>clear(p.provider)}>limpar cópia local</button>}</div></Card>})}</div>{config&&<ConnectionModal source={config} onClose={()=>setConfig(null)} onChanged={async()=>{await onChanged();setConfig(null)}}/>}</>
}

function AdvancedCompare(){
  const seed=name=>({id:crypto.randomUUID?.()||Math.random().toString(36),name,file:null,coverage:'FULL_EXPORT'});const [sources,setSources]=useState([seed('QRZ'),seed('HRD')]),[reference,setReference]=useState(0),[result,setResult]=useState(null),[busy,setBusy]=useState(false),[msg,setMsg]=useState('')
  function patch(i,changes){setSources(v=>v.map((x,j)=>j===i?{...x,...changes}:x))}
  async function compare(){setMsg('');if(sources.length<2||sources.some(x=>!x.file))return setMsg('Selecione ao menos dois arquivos ADIF.');setBusy(true);try{const payload=await Promise.all(sources.map(async x=>({source:x.name.trim().toUpperCase(),coverage:x.coverage,filename:x.file.name,content:await x.file.text()})));setResult(await api('/api/advanced/compare',{method:'POST',body:JSON.stringify({sources:payload,reference_index:reference})}))}catch(e){setMsg('Erro: '+e.message)}finally{setBusy(false)}}
  return <div className="u-tool"><div className="u-tool-intro"><div><h2>Comparação avançada de ADIF</h2><p>Compare exports atuais, históricos ou de qualquer plataforma com a mesma lógica de pareamento usada pelo produto.</p></div><Button onClick={compare} disabled={busy}>{busy?'Comparando…':'Comparar fontes'}</Button></div>{msg&&<Notice tone={msg.startsWith('Erro')?'error':'warn'}>{msg}</Notice>}<div className="u-adif-sources">{sources.map((x,i)=><article key={x.id} className={reference===i?'reference':''}><label className="u-radio"><input type="radio" checked={reference===i} onChange={()=>setReference(i)}/> referência</label><label><span>Nome</span><input value={x.name} onChange={e=>patch(i,{name:e.target.value})}/></label><label><span>Cobertura</span><select value={x.coverage} onChange={e=>patch(i,{coverage:e.target.value})}><option value="FULL_EXPORT">Export completo</option><option value="PARTIAL_EXPORT">Parcial</option><option value="FILTERED_EXPORT">Filtrado</option></select></label><label className="u-file wide">{x.file?.name||'Selecionar ADIF'}<input type="file" accept=".adi,.adif,.txt" onChange={e=>patch(i,{file:e.target.files?.[0]||null})}/></label>{sources.length>2&&<button className="u-text-danger" onClick={()=>setSources(v=>v.filter((_,j)=>j!==i))}>remover</button>}</article>)}</div><Button kind="secondary" small onClick={()=>setSources(v=>[...v,seed('FONTE_'+(v.length+1))])}>+ Adicionar fonte</Button>{result&&<><div className="u-metrics static"><div><span>Pareamentos</span><b>{fmt(result.summary?.matched_pairs)}</b></div><div><span>Ausências</span><b>{fmt(result.summary?.presence_differences)}</b></div><div><span>Campos</span><b>{fmt(result.summary?.field_differences)}</b></div><div><span>Revisar</span><b>{fmt(result.summary?.review_candidates)}</b></div></div><div className="u-compare-results">{(result.presence_differences||[]).slice(0,500).map((x,i)=><article key={'p'+i}><Badge tone={x.confidence==='HIGH'?'warn':'neutral'}>{x.confidence}</Badge><div><b>{x.call} · {x.date} {x.time}</b><p>Presente em {x.present_in}; ausente em {x.missing_in}. {x.reason}</p></div></article>)}{(result.field_differences||[]).slice(0,500).map((x,i)=><article key={'f'+i}><Badge tone="warn">{x.field}</Badge><div><b>{x.call} · {x.date}</b><p>{String(x.value_a??'∅')} → {String(x.value_b??'∅')} em {x.compared_source}</p></div></article>)}</div></>}</div>
}


function AwardMaster(){
  const [qrzFile,setQrzFile]=useState(null),[lotwFile,setLotwFile]=useState(null),[report,setReport]=useState(null),[busy,setBusy]=useState(''),[msg,setMsg]=useState('')
  const ready=!!qrzFile&&!!lotwFile
  async function submit(path,blob=false){
    if(!ready)throw new Error('Selecione os exports completos do QRZ e do LoTW.')
    const form=new FormData();form.append('qrz',qrzFile);form.append('lotw',lotwFile)
    const response=await fetch(path,{method:'POST',body:form})
    if(!response.ok){let detail=await response.text();try{detail=JSON.parse(detail)?.detail||detail}catch{};throw new Error(detail||'Falha ao processar os ADIFs')}
    if(blob)return {blob:await response.blob(),disposition:response.headers.get('content-disposition')||''}
    return response.json()
  }
  async function preview(){setBusy('preview');setMsg('');setReport(null);try{const r=await submit('/api/product/award-master/preview');setReport(r);const warnings=r.coverage?.warnings?.length||0;setMsg(r.safe_to_export?(warnings?`Validação concluída com ${warnings} alerta(s) auditado(s). A exportação segura continua liberada.`:'Validação concluída: nenhuma regressão crítica foi detectada.'):'O Master exige revisão antes da exportação. Veja os bloqueios abaixo.')}catch(e){setMsg('Erro: '+e.message)}finally{setBusy('')}}
  async function exportMaster(){if(!report?.safe_to_export)return;setBusy('export');setMsg('');try{const r=await submit('/api/product/award-master/export',true);const m=/filename="?([^";]+)"?/i.exec(r.disposition);downloadBlob(m?.[1]||'PU2BRU-UltimateAAC-MASTER.adi',r.blob);setMsg('Master ADIF gerado. Nenhum log remoto foi alterado.')}catch(e){setMsg('Erro: '+e.message)}finally{setBusy('')}}
  async function exportAudit(){setBusy('audit');setMsg('');try{const r=await submit('/api/product/award-master/audit',true);const m=/filename="?([^";]+)"?/i.exec(r.disposition);downloadBlob(m?.[1]||'PU2BRU-Award-Master-audit.csv',r.blob,'text/csv;charset=utf-8')}catch(e){setMsg('Erro: '+e.message)}finally{setBusy('')}}
  function clear(){setQrzFile(null);setLotwFile(null);setReport(null);setMsg('')}
  const m=report?.coverage?.master||{},merge=report?.merge||{},conf=report?.conflicts||{},regs=report?.coverage?.blocking_regressions||[],warnings=report?.coverage?.warnings||[]
  return <div className="u-tool"><div className="u-tool-intro"><div><h2>Master ADIF para awards</h2><p>Combina QRZ + LoTW com política conservadora, auditoria e bloqueio automático se houver regressão de cobertura. O processo é somente leitura: nada é gravado no QRZ, LoTW ou em outro logbook.</p></div><Badge tone={report?.safe_to_export?(warnings.length?'warn':'ok'):report?'warn':'neutral'}>{report?.safe_to_export?(warnings.length?'SAFE + AUDIT':'SAFE'):report?'REVISAR':'READ-ONLY'}</Badge></div>
    <Notice>Use exports completos e atuais. QRZ enriquece grids/IOTA/metadados; LoTW prevalece nos campos geográficos usados por awards. Pareamentos ambíguos nunca são mesclados silenciosamente.</Notice>
    <div className="u-master-files"><label><span>Export QRZ</span><b>{qrzFile?.name||'Selecionar ADIF do QRZ'}</b><input type="file" accept=".adi,.adif,.txt" onChange={e=>{setQrzFile(e.target.files?.[0]||null);setReport(null)}}/></label><label><span>Export LoTW</span><b>{lotwFile?.name||'Selecionar lotwreport.adi'}</b><input type="file" accept=".adi,.adif,.txt" onChange={e=>{setLotwFile(e.target.files?.[0]||null);setReport(null)}}/></label></div>
    <div className="u-master-actions"><Button disabled={!ready||!!busy} onClick={preview}>{busy==='preview'?'Validando…':'Validar e montar Master'}</Button><Button kind="secondary" disabled={!report?.safe_to_export||!!busy} onClick={exportMaster}>{busy==='export'?'Gerando…':'Baixar Master seguro'}</Button><Button kind="secondary" disabled={!report||!!busy} onClick={exportAudit}>{busy==='audit'?'Gerando…':'Baixar auditoria CSV'}</Button><button className="u-text-danger" disabled={!!busy} onClick={clear}>limpar</button></div>
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
  async function exportAll(){setBusy(true);try{const ids=await api('/api/qso-manager/ids?limit=50000');if(!ids.ids?.length)throw new Error('Nenhum QSO consolidado disponível');const response=await fetch('/api/qso-manager/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({logical_ids:ids.ids,filename:'PU2BRU-QSO-Manager-backup.adi'})});if(!response.ok)throw new Error((await response.json()).detail||'Falha no export');downloadBlob('PU2BRU-QSO-Manager-backup.adi',await response.blob());setGlobalMessage(`${fmt(ids.ids.length)} QSOs exportados para backup ADIF.`)}catch(e){setGlobalMessage('Erro: '+e.message)}finally{setBusy(false)}}
  async function exportDiagnostics(){const d=diagnostics||await api('/api/product/diagnostics');downloadBlob('PU2BRU-QSO-Manager-diagnostico.json',JSON.stringify(d,null,2),'application/json;charset=utf-8')}
  const tabs=[['compare','Comparar ADIF'],['award','Master para awards'],['backup','Importar & exportar'],['activity','Atividade'],['security','Segurança & diagnóstico']]
  return <><PageHead eyebrow="FERRAMENTAS" title="Tudo que é avançado, em um único lugar." subtitle="O fluxo principal fica limpo. Auditoria, exportações e diagnóstico continuam acessíveis sem espalhar a navegação."/><div className="u-tool-tabs">{tabs.map(x=><button key={x[0]} className={tab===x[0]?'active':''} onClick={()=>setTab(x[0])}>{x[1]}</button>)}</div>{tab==='compare'&&<AdvancedCompare/>}{tab==='award'&&<AwardMaster/>}{tab==='backup'&&<div className="u-two"><Card title="Backup operacional" subtitle="Exporte o log lógico consolidado em ADIF — independente das plataformas individuais."><div className="u-backup-big"><b>{fmt(workspace?.summary?.logical_qsos)}</b><span>QSOs disponíveis</span></div><Button disabled={busy} onClick={exportAll}>{busy?'Gerando…':'Baixar backup ADIF'}</Button></Card><Card title="Fontes manuais" subtitle="HRD e HRDLog usam ADIF quando uma leitura remota completa não existe."><div className="u-source-mini">{(status?.providers||[]).filter(p=>['HRD','HRDLOG'].includes(p.provider)).map(p=><div key={p.provider}><i className={p.configured?'ok':''}>{short(p.provider)}</i><span><b>{p.label}</b><small>{fmt(p.snapshot?.records)} registros · {dt(p.snapshot?.downloaded_at)}</small></span></div>)}</div><p className="u-muted">A importação é feita na página Fontes, onde a cobertura e o efeito de cada arquivo ficam explícitos.</p></Card></div>}{tab==='activity'&&<Card title="Histórico de atividade" subtitle="Sincronizações, exportações e ações em lote registradas pelo workspace.">{!activity.length?<Empty title="Sem atividade registrada"/>:<div className="u-activity">{activity.map((x,i)=><article key={i}><Badge>{x.kind||x.type||'EVENTO'}</Badge><div><b>{x.message||x.action||'Atividade'}</b><small>{dt(x.at||x.created_at||x.timestamp)}</small></div></article>)}</div>}</Card>}{tab==='security'&&<div className="u-two"><Card title="Credenciais" subtitle="Nenhuma chave é exposta em texto aberto pela interface."><div className="u-security-list">{(status?.providers||[]).filter(p=>p.source_kind!=='local_adif').map(p=><div key={p.provider}><span className={'u-dot '+(p.configured?'ok':'')}/><b>{p.label}</b><small>{p.configured?'configurada':'não configurada'}</small></div>)}</div></Card><Card title="Diagnóstico do produto" subtitle="Estado mínimo para suporte e validação, sem incluir segredos."><div className="u-diagnostic"><p><span>Versão</span><b>{diagnostics?.version||VERSION}</b></p><p><span>Windows</span><b>{diagnostics?.windows_production_ready?'produção':'verificar'}</b></p><p><span>Android</span><b>{diagnostics?.android_stage||'preview'}</b></p><p><span>QSOs lógicos</span><b>{fmt(diagnostics?.workspace?.summary?.logical_qsos)}</b></p><p><span>Fontes</span><b>{fmt(diagnostics?.sources?.length)}</b></p></div><Button kind="secondary" onClick={exportDiagnostics}>Baixar diagnóstico JSON</Button></Card></div>}</>
}

export default function App900(){
  const [page,setPage]=useState('overview'),[boot,setBoot]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('')
  async function refresh(){const b=await api('/api/product/bootstrap');setBoot(b);return b}
  useEffect(()=>{refresh().catch(e=>setMessage('Erro ao iniciar: '+e.message))},[])
  async function syncAll(){setBusy(true);try{const r=await api('/api/product/sync-jobs-all',{method:'POST',body:'{}'});setMessage(r.started?r.started+' fonte(s) iniciada(s) em paralelo. Acompanhe o progresso em Fontes.':'Nenhuma fonte remota configurada para atualizar.');setPage('sources')}catch(e){setMessage('Erro: '+e.message)}finally{setBusy(false)}}
  async function refreshIssues(){try{const [issues,qsl]=await Promise.all([api('/api/product/issues?limit=500'),api('/api/product/qsl')]);setBoot(v=>({...v,issues,qsl}))}catch(e){setMessage('Erro: '+e.message)}}
  const nav=n=>setPage(n)
  return <div className="u-app"><aside className="u-sidebar"><div className="u-brand"><div className="u-brand-mark">PU2BRU</div><span><b>QSO Manager</b><small>PU2BRU · v{VERSION}</small></span></div><nav>{NAV.map(([id,label,icon])=><button key={id} className={page===id?'active':''} onClick={()=>nav(id)}><i>{icon}</i><span>{label}</span>{id==='inbox'&&boot?.issues?.total>0&&<em>{boot.issues.total>99?'99+':boot.issues.total}</em>}</button>)}</nav><div className="u-sidebar-foot"><span className={boot?'ok':''}/><div><b>{boot?'Workspace pronto':'Inicializando'}</b><small>{boot?`${fmt(boot.workspace?.summary?.logical_qsos)} QSOs lógicos`:'validando serviços'}</small></div></div></aside><header className="u-mobile-top"><div><b>QSO Manager</b><small>PU2BRU · v{VERSION}</small></div><Button small disabled={busy} onClick={syncAll}>↻</Button></header><main className="u-main">{message&&<Notice tone={message.startsWith('Erro')?'error':'info'}>{message}<button className="u-close" onClick={()=>setMessage('')}>×</button></Notice>}{!boot&&<div className="u-loading-screen"><div className="u-pulse">PU2BRU</div><h2>Montando seu workspace…</h2><p>Validando banco local, frontend e fontes.</p></div>}{boot&&<>{page==='overview'&&<Overview boot={boot} navigate={nav} syncAll={syncAll} busy={busy}/>} {page==='log'&&<LogPage workspace={boot.workspace}/>} {page==='inbox'&&<InboxPage issues={boot.issues} onRefresh={refreshIssues}/>} {page==='qsl'&&<QslPage qsl={boot.qsl} onRefresh={refreshIssues} onChanged={refresh} setGlobalMessage={setMessage}/>} {page==='sources'&&<SourcesPage status={boot.status} onChanged={refresh} setGlobalMessage={setMessage}/>} {page==='tools'&&<ToolsPage workspace={boot.workspace} status={boot.status} setGlobalMessage={setMessage}/>}</>}</main><nav className="u-bottom">{NAV.map(([id,label,icon])=><button key={id} className={page===id?'active':''} onClick={()=>nav(id)}><i>{icon}</i><span>{label}</span>{id==='inbox'&&boot?.issues?.total>0&&<em>{boot.issues.total>99?'99+':boot.issues.total}</em>}</button>)}</nav></div>
}
