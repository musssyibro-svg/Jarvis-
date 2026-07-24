import { useState, useEffect, useRef } from 'react'
import { Badge, Btn, StatCard, Modal } from '../components/UI'

import { API } from '../config.js'

const AGENT_COLORS = {
  scout:        '#00d4ff',
  score:        '#ff9500',
  proposal:     '#00ff88',
  browser:      '#ff4444',
  memory:       '#a855f7',
  orchestrator: '#ffffff',
}
const AGENT_ICONS = {
  scout:'◎', score:'▲', proposal:'◈', browser:'⬡', memory:'◉', orchestrator:'⟳'
}

const PLATFORMS = [
  { id:'remoteok',       label:'RemoteOK'         },
  { id:'weworkremotely', label:'We Work Remotely'  },
  { id:'hubstaff',       label:'Hubstaff Talent'   },
  { id:'wellfound',      label:'Wellfound'          },
  { id:'peopleperhour',  label:'PeoplePerHour'     },
  { id:'contra',         label:'Contra'            },
  { id:'clickworker',    label:'Clickworker'       },
  { id:'zuodao',         label:'Zuodao'            },
]

export default function Workspace() {
  const [tab, setTab]             = useState('control')
  const [status, setStatus]       = useState(null)
  const [feed, setFeed]           = useState([])
  const [queue, setQueue]         = useState([])
  const [jobs, setJobs]           = useState([])
  const [proposals, setProposals] = useState([])
  const [memory, setMemory]       = useState(null)
  const [selJob, setSelJob]       = useState(null)
  const [selQ, setSelQ]           = useState(null)
  const [config, setConfig]       = useState({
    platforms:        ['remoteok','weworkremotely','hubstaff'],
    your_name:        'Ibrahim',
    your_skills:      'Python, automation, web scraping, AI integration, FastAPI',
    max_per_platform: 10,
    min_score:        30,
    max_generate:     5,
  })
  const feedRef    = useRef(null)
  const sseRef     = useRef(null)

  // ── SSE live feed ──────────────────────────────────────────────────────────
  useEffect(() => {
    connectSSE()
    loadAll()
    const t = setInterval(loadAll, 8000)
    return () => { clearInterval(t); sseRef.current?.close() }
  }, [])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [feed])

  const connectSSE = () => {
    if (sseRef.current) sseRef.current.close()
    const es = new EventSource(`${API}/orchestrator/feed`)
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.ping) return
        setFeed(prev => [...prev.slice(-150), data])
      } catch {}
    }
    es.onerror = () => { es.close(); setTimeout(connectSSE, 3000) }
    sseRef.current = es
  }

  const loadAll = async () => {
    try { const r = await fetch(`${API}/orchestrator/status`);      if(r.ok) setStatus(await r.json()) } catch{}
    try { const r = await fetch(`${API}/automation/queue`);  if(r.ok) setQueue((await r.json()).queue||[]) } catch{}
    try { const r = await fetch(`${API}/automation/platform-jobs?limit=50`); if(r.ok) setJobs((await r.json()).jobs||[]) } catch{}
    try { const r = await fetch(`${API}/proposals/`);        if(r.ok) setProposals((await r.json()).proposals||[]) } catch{}
    try { const r = await fetch(`${API}/orchestrator/memory`);      if(r.ok) setMemory(await r.json()) } catch{}
  }

  const startPipeline = async () => {
    await fetch(`${API}/orchestrator/start`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(config)
    })
    setTimeout(loadAll, 1000)
  }

  const stopPipeline = async () => {
    await fetch(`${API}/orchestrator/stop`, { method:'POST' })
    loadAll()
  }

  const approveQ = async (qid, action) => {
    await fetch(`${API}/automation/queue/${qid}/status?status=${action}`, { method:'PATCH' })
    loadAll()
  }

  const togglePlatform = (id) => setConfig(c => ({
    ...c,
    platforms: c.platforms.includes(id) ? c.platforms.filter(p=>p!==id) : [...c.platforms, id]
  }))

  const running  = status?.running
  const pct      = status?.progress || 0
  const pending  = queue.filter(q=>q.status==='pending').length
  const qualified = jobs.filter(j=>j.score>=config.min_score).length

  const tabs = [
    { id:'control',   label:'CONTROL' },
    { id:'feed',      label:`LIVE FEED ${feed.length>0?`(${feed.length})`:''}` },
    { id:'pipeline',  label:`OPPORTUNITIES (${jobs.length})` },
    { id:'approvals', label:`APPROVALS${pending>0?` ● ${pending}`:''}` },
    { id:'memory',    label:'MEMORY' },
  ]

  const inS = { width:'100%', background:'rgba(0,10,20,0.8)', border:'1px solid rgba(0,212,255,0.2)', outline:'none', color:'#c8e8f0', padding:'7px 10px', fontSize:'11px', fontFamily:'monospace', borderRadius:'3px' }

  return (
    <div style={{ padding:'28px', overflowY:'auto', height:'100%' }}>

      {/* Header */}
      <div style={{ marginBottom:'20px' }}>
        <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.3em', marginBottom:'4px' }}>
          JARVIS // AGENT WORKSPACE
        </div>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', flexWrap:'wrap', gap:'10px' }}>
          <h1 style={{ fontSize:'20px', color:'#00d4ff', letterSpacing:'0.1em', textShadow:'0 0 20px rgba(0,212,255,0.4)', fontFamily:'sans-serif', margin:0 }}>
            ⟳ AUTONOMOUS PIPELINE
          </h1>
          <div style={{ display:'flex', gap:'8px' }}>
            {!running
              ? <Btn onClick={startPipeline} variant="success">▶ START PIPELINE</Btn>
              : <Btn onClick={stopPipeline} variant="danger">■ STOP</Btn>
            }
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ marginTop:'12px', height:'3px', background:'rgba(255,255,255,0.06)', borderRadius:'2px' }}>
          <div style={{ height:'100%', width:`${pct}%`, background:`linear-gradient(90deg,#00d4ff,#00ff88)`, borderRadius:'2px', transition:'width 0.4s ease', boxShadow:'0 0 8px rgba(0,212,255,0.5)' }}/>
        </div>
        <div style={{ display:'flex', justifyContent:'space-between', marginTop:'4px', fontSize:'9px', color:'rgba(255,255,255,0.25)', letterSpacing:'0.1em' }}>
          <span>{status?.stage?.toUpperCase().replace('_',' ')||'IDLE'}</span>
          <span>{pct}%</span>
        </div>
      </div>

      {/* Stats row */}
      {status && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'8px', marginBottom:'16px' }}>
          <StatCard label="JOBS FOUND"    value={status.stats?.jobs_found||0}     color="#00d4ff" />
          <StatCard label="QUALIFIED"     value={status.stats?.jobs_qualified||0} color="#ff9500" />
          <StatCard label="PROPOSALS GEN" value={status.stats?.proposals_gen||0}  color="#00ff88" />
          <StatCard label="APPROVALS"     value={pending}                          color="#ff4444" />
        </div>
      )}

      {/* Sub-tabs */}
      <div style={{ display:'flex', gap:'4px', marginBottom:'16px', flexWrap:'wrap' }}>
        {tabs.map(t => (
          <button key={t.id} onClick={()=>setTab(t.id)} style={{
            padding:'6px 12px', fontSize:'9px', cursor:'pointer', letterSpacing:'0.13em',
            fontFamily:'monospace', borderRadius:'3px', transition:'all 0.15s',
            background: tab===t.id?'rgba(0,212,255,0.13)':'transparent',
            border: `1px solid ${tab===t.id?'#00d4ff':'rgba(255,255,255,0.1)'}`,
            color: tab===t.id?'#00d4ff':'rgba(255,255,255,0.35)',
          }}>{t.label}</button>
        ))}
      </div>

      {/* ── CONTROL TAB ── */}
      {tab==='control' && (
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'14px' }}>
          <div style={{ border:'1px solid rgba(0,212,255,0.15)', borderRadius:'4px', padding:'18px', background:'rgba(0,10,20,0.7)' }}>
            <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'14px' }}>PLATFORM SELECTION</div>
            <div style={{ display:'flex', flexDirection:'column', gap:'6px', marginBottom:'14px' }}>
              {PLATFORMS.map(p => (
                <label key={p.id} style={{ display:'flex', alignItems:'center', gap:'10px', cursor:'pointer', fontSize:'11px', color: config.platforms.includes(p.id)?'#00d4ff':'rgba(255,255,255,0.3)' }}>
                  <input type="checkbox" checked={config.platforms.includes(p.id)} onChange={()=>togglePlatform(p.id)} style={{ accentColor:'#00d4ff' }}/>
                  {p.label}
                </label>
              ))}
            </div>
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:'12px' }}>
            <div style={{ border:'1px solid rgba(0,212,255,0.15)', borderRadius:'4px', padding:'18px', background:'rgba(0,10,20,0.7)' }}>
              <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'12px' }}>PROFILE</div>
              {[
                ['NAME',   'your_name',   'text'],
                ['SKILLS', 'your_skills', 'text'],
              ].map(([label, key]) => (
                <div key={key} style={{ marginBottom:'10px' }}>
                  <div style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'4px' }}>{label}</div>
                  <input value={config[key]} onChange={e=>setConfig(c=>({...c,[key]:e.target.value}))} style={inS}/>
                </div>
              ))}
            </div>
            <div style={{ border:'1px solid rgba(0,212,255,0.15)', borderRadius:'4px', padding:'18px', background:'rgba(0,10,20,0.7)' }}>
              <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'12px' }}>PIPELINE SETTINGS</div>
              {[
                ['JOBS PER PLATFORM', 'max_per_platform', 1, 30],
                ['MIN SCORE THRESHOLD','min_score',       0, 100],
                ['MAX PROPOSALS/RUN',  'max_generate',    1, 20],
              ].map(([label,key,min,max]) => (
                <div key={key} style={{ marginBottom:'10px' }}>
                  <div style={{ display:'flex', justifyContent:'space-between', fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'4px' }}>
                    <span>{label}</span><span style={{color:'#00d4ff'}}>{config[key]}</span>
                  </div>
                  <input type="range" min={min} max={max} value={config[key]}
                    onChange={e=>setConfig(c=>({...c,[key]:parseInt(e.target.value)}))}
                    style={{ width:'100%', accentColor:'#00d4ff' }}/>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── LIVE FEED TAB ── */}
      {tab==='feed' && (
        <div style={{ border:'1px solid rgba(0,212,255,0.1)', borderRadius:'4px', background:'rgba(0,4,8,0.95)' }}>
          <div style={{ padding:'10px 14px', borderBottom:'1px solid rgba(0,212,255,0.08)', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <span style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em' }}>AGENT ACTIVITY LOG</span>
            <Btn onClick={()=>setFeed([])} variant="ghost" small>CLEAR</Btn>
          </div>
          <div ref={feedRef} style={{ height:'500px', overflowY:'auto', padding:'12px', display:'flex', flexDirection:'column', gap:'3px' }}>
            {feed.length===0 && (
              <div style={{ color:'rgba(255,255,255,0.15)', fontSize:'11px', textAlign:'center', paddingTop:'40px' }}>
                Waiting for agent activity...<br/>
                <span style={{fontSize:'9px'}}>Start the pipeline to see live feed</span>
              </div>
            )}
            {feed.map((entry, i) => {
              const c = AGENT_COLORS[entry.agent] || '#888'
              const icon = AGENT_ICONS[entry.agent] || '·'
              return (
                <div key={i} style={{ display:'flex', gap:'10px', alignItems:'flex-start', fontSize:'10px', lineHeight:'1.6', padding:'2px 0', borderBottom:'1px solid rgba(255,255,255,0.03)', animation:'fadeIn 0.2s ease' }}>
                  <span style={{ color:'rgba(255,255,255,0.2)', flexShrink:0, fontFamily:'monospace', fontSize:'9px', paddingTop:'1px' }}>{entry.ts}</span>
                  <span style={{ color:c, flexShrink:0, fontSize:'9px', letterSpacing:'0.15em', minWidth:'80px' }}>{icon} {(entry.agent||'').toUpperCase()}</span>
                  <span style={{ color: entry.level==='error'?'#ff4444':'rgba(255,255,255,0.6)' }}>{entry.msg}</span>
                </div>
              )
            })}
            <div style={{ display:'inline-block', width:'7px', height:'12px', background:'#00d4ff', animation:'blink 1s step-end infinite', marginLeft:'2px', marginTop:'4px' }}/>
          </div>
        </div>
      )}

      {/* ── PIPELINE / OPPORTUNITIES TAB ── */}
      {tab==='pipeline' && (
        <div style={{ display:'flex', flexDirection:'column', gap:'6px' }}>
          <div style={{ display:'flex', gap:'8px', marginBottom:'8px', alignItems:'center' }}>
            <Btn onClick={loadAll} variant="ghost" small>↺ REFRESH</Btn>
            <span style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)' }}>{jobs.length} opportunities | {qualified} qualified</span>
          </div>
          {jobs.slice(0,40).map(j => {
            const isSel = selJob?.id===j.id
            const scoreColor = j.score>=70?'#00ff88':j.score>=40?'#ff9500':'#ff4444'
            let skills = []; try { skills=JSON.parse(j.skills||'[]') } catch{}
            return (
              <div key={j.id} onClick={()=>setSelJob(isSel?null:j)} style={{
                padding:'12px 14px', borderRadius:'4px', cursor:'pointer',
                background: isSel?'rgba(0,212,255,0.06)':'rgba(255,255,255,0.02)',
                border: `1px solid ${isSel?'#00d4ff':'rgba(255,255,255,0.06)'}`,
                transition:'all 0.15s',
              }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' }}>
                  <div style={{ flex:1 }}>
                    <div style={{ display:'flex', gap:'6px', marginBottom:'4px', flexWrap:'wrap', alignItems:'center' }}>
                      <span style={{ fontSize:'9px', fontFamily:'monospace', padding:'2px 6px', borderRadius:'2px', border:`1px solid ${AGENT_COLORS.scout}`, color:AGENT_COLORS.scout }}>{j.platform}</span>
                      {j.company && <span style={{ fontSize:'10px', color:'rgba(255,149,0,0.8)' }}>{j.company}</span>}
                    </div>
                    <div style={{ fontSize:'13px', fontWeight:'600', color:'#c4e4ef', marginBottom:'3px' }}>{j.title}</div>
                    {isSel && <div style={{ fontSize:'11px', color:'rgba(255,255,255,0.4)', lineHeight:1.6, marginBottom:'8px' }}>{j.description}</div>}
                    {skills.length>0 && isSel && (
                      <div style={{ display:'flex', gap:'4px', flexWrap:'wrap', marginBottom:'8px' }}>
                        {skills.map(s=><span key={s} style={{ fontSize:'9px', padding:'1px 6px', borderRadius:'2px', background:'rgba(0,212,255,0.08)', border:'1px solid rgba(0,212,255,0.15)', color:'rgba(0,212,255,0.7)' }}>{s}</span>)}
                      </div>
                    )}
                  </div>
                  <div style={{ textAlign:'right', flexShrink:0, marginLeft:'12px' }}>
                    <div style={{ fontSize:'20px', fontWeight:'700', color:scoreColor, fontFamily:'monospace' }}>{j.score||0}</div>
                    <div style={{ fontSize:'8px', color:'rgba(255,255,255,0.2)' }}>SCORE</div>
                  </div>
                </div>
                {isSel && (
                  <div style={{ display:'flex', gap:'6px', marginTop:'8px' }}>
                    {j.link && <Btn onClick={e=>{e.stopPropagation();window.open(j.link,'_blank')}} variant="ghost" small>OPEN ↗</Btn>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* ── APPROVALS TAB ── */}
      {tab==='approvals' && (
        <div style={{ display:'flex', flexDirection:'column', gap:'8px' }}>
          <div style={{ display:'flex', gap:'8px', marginBottom:'8px' }}>
            <Btn onClick={loadAll} variant="ghost" small>↺ REFRESH</Btn>
            <span style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', alignSelf:'center' }}>{pending} pending approval</span>
          </div>
          {queue.length===0 && <div style={{ textAlign:'center', padding:'50px', color:'rgba(255,255,255,0.15)', fontSize:'11px', lineHeight:2 }}>No items in queue.<br/><span style={{fontSize:'9px'}}>Run the pipeline to generate proposals for review.</span></div>}
          {queue.map(q => {
            const app = q.payload?.application||''
            const job = q.payload?.job||{}
            const isSel = selQ?.id===q.id
            const statusColors = { pending:'#ff9500', approved:'#00ff88', done:'#888', rejected:'#ff4444' }
            return (
              <div key={q.id} onClick={()=>setSelQ(isSel?null:q)} style={{
                padding:'14px 16px', borderRadius:'4px', cursor:'pointer',
                background: isSel?'rgba(0,212,255,0.05)':'rgba(255,255,255,0.02)',
                border: `1px solid ${statusColors[q.status]||'rgba(255,255,255,0.07)'}44`,
                transition:'all 0.15s',
              }}>
                <div style={{ display:'flex', gap:'8px', alignItems:'center', marginBottom:'5px', flexWrap:'wrap' }}>
                  <span style={{ fontSize:'9px', padding:'2px 7px', borderRadius:'2px', border:`1px solid ${statusColors[q.status]||'#888'}`, color:statusColors[q.status]||'#888' }}>{q.status?.toUpperCase()}</span>
                  <span style={{ fontSize:'9px', padding:'2px 7px', borderRadius:'2px', border:'1px solid rgba(0,212,255,0.3)', color:'#00d4ff' }}>{q.platform}</span>
                  <span style={{ fontSize:'12px', fontWeight:'600', color:'#c4e4ef' }}>{q.job_title}</span>
                </div>
                {isSel && app && (
                  <div style={{ fontSize:'11px', color:'rgba(255,255,255,0.55)', lineHeight:1.75, whiteSpace:'pre-wrap', background:'rgba(0,10,20,0.6)', padding:'12px', borderRadius:'3px', border:'1px solid rgba(0,212,255,0.12)', marginBottom:'10px', marginTop:'8px' }}>
                    {app}
                  </div>
                )}
                {isSel && (
                  <div style={{ display:'flex', gap:'6px', flexWrap:'wrap', marginTop:'8px' }} onClick={e=>e.stopPropagation()}>
                    {q.status==='pending' && <>
                      <Btn onClick={()=>approveQ(q.id,'approved')} variant="success" small>✓ APPROVE</Btn>
                      <Btn onClick={()=>approveQ(q.id,'rejected')} variant="danger" small>✗ REJECT</Btn>
                    </>}
                    {q.status==='approved' && <Btn onClick={()=>approveQ(q.id,'done')} variant="ghost" small>MARK SENT</Btn>}
                    {app && <Btn onClick={()=>navigator.clipboard?.writeText(app)} variant="ghost" small>COPY APPLICATION</Btn>}
                    {job.link && <Btn onClick={()=>window.open(job.link,'_blank')} variant="ghost" small>OPEN JOB ↗</Btn>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* ── MEMORY TAB ── */}
      {tab==='memory' && (
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'14px' }}>
          <div style={{ border:'1px solid rgba(168,85,247,0.2)', borderRadius:'4px', padding:'18px', background:'rgba(0,10,20,0.7)' }}>
            <div style={{ fontSize:'9px', color:'rgba(168,85,247,0.7)', letterSpacing:'0.2em', marginBottom:'14px' }}>◉ MEMORY INSIGHTS</div>
            {memory ? (
              <div style={{ display:'flex', flexDirection:'column', gap:'10px' }}>
                {[
                  ['Top Win Pattern',  memory.top_pattern   || '—'],
                  ['Best Platform',    memory.best_platform  || '—'],
                  ['Worst Platform',   memory.worst_platform || '—'],
                  ['Total Wins',       memory.total_wins     || 0 ],
                ].map(([label, val]) => (
                  <div key={label} style={{ display:'flex', justifyContent:'space-between', padding:'8px 0', borderBottom:'1px solid rgba(255,255,255,0.05)', fontSize:'11px' }}>
                    <span style={{ color:'rgba(255,255,255,0.35)', letterSpacing:'0.1em' }}>{label}</span>
                    <span style={{ color:'#a855f7', fontWeight:'700', fontFamily:'monospace' }}>{val}</span>
                  </div>
                ))}
              </div>
            ) : <div style={{ color:'rgba(255,255,255,0.2)', fontSize:'11px' }}>No memory data yet. Run a pipeline cycle first.</div>}
          </div>
          <div style={{ border:'1px solid rgba(168,85,247,0.2)', borderRadius:'4px', padding:'18px', background:'rgba(0,10,20,0.7)' }}>
            <div style={{ fontSize:'9px', color:'rgba(168,85,247,0.7)', letterSpacing:'0.2em', marginBottom:'14px' }}>TOP WIN KEYWORDS</div>
            {memory?.top_patterns?.length > 0 ? (
              <div style={{ display:'flex', flexDirection:'column', gap:'6px' }}>
                {memory.top_patterns.map((p,i) => (
                  <div key={i} style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                    <span style={{ fontSize:'10px', color:'rgba(168,85,247,0.8)', fontFamily:'monospace', minWidth:'80px' }}>{p.pattern}</span>
                    <div style={{ flex:1, height:'3px', background:'rgba(255,255,255,0.05)', borderRadius:'2px' }}>
                      <div style={{ height:'100%', width:`${p.win_rate}%`, background:'linear-gradient(90deg,rgba(168,85,247,0.5),#a855f7)', borderRadius:'2px' }}/>
                    </div>
                    <span style={{ fontSize:'9px', color:'#a855f7', fontFamily:'monospace', minWidth:'35px', textAlign:'right' }}>{p.win_rate}%</span>
                    <span style={{ fontSize:'9px', color:'rgba(255,255,255,0.2)' }}>({p.total})</span>
                  </div>
                ))}
              </div>
            ) : <div style={{ color:'rgba(255,255,255,0.2)', fontSize:'11px' }}>Win patterns build up as you track proposal outcomes.</div>}
          </div>
        </div>
      )}
    </div>
  )
}
