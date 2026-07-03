import { useState, useEffect, useRef } from 'react'
import { Btn, Badge, StatCard } from '../components/UI'

import { API } from '../config.js'

const PLATFORMS = [
  { id:'hubstaff',       label:'Hubstaff Talent',   color:'#ff9500' },
  { id:'remoteok',       label:'RemoteOK',           color:'#00ff88' },
  { id:'weworkremotely', label:'We Work Remotely',   color:'#00d4ff' },
  { id:'remoteco',       label:'Remote.co',          color:'#00d4ff' },
  { id:'wellfound',      label:'Wellfound',          color:'#ff9500' },
  { id:'peopleperhour',  label:'PeoplePerHour',      color:'#00ff88' },
  { id:'contra',         label:'Contra',             color:'#00d4ff' },
]

const LEVEL_COLOR = { info:'#00d4ff', success:'#00ff88', warning:'#ff9500', error:'#ff4444' }

const S = {
  page:    { padding:'24px', overflowY:'auto', height:'100%', boxSizing:'border-box' },
  card:    { border:'1px solid rgba(0,212,255,0.15)', borderRadius:'4px', padding:'18px', background:'rgba(0,10,20,0.75)', marginBottom:'12px' },
  label:   { fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'12px' },
  inp:     { width:'100%', background:'rgba(0,10,20,0.8)', border:'1px solid rgba(0,212,255,0.2)', outline:'none', color:'#c8e8f0', padding:'7px 10px', fontSize:'11px', fontFamily:'monospace', borderRadius:'3px', boxSizing:'border-box' },
  tabBtn:  (active) => ({ padding:'5px 14px', borderRadius:'3px', border:`1px solid ${active?'#00d4ff':'rgba(255,255,255,0.1)'}`, background:active?'rgba(0,212,255,0.1)':'transparent', color:active?'#00d4ff':'rgba(255,255,255,0.35)', cursor:'pointer', fontFamily:'monospace', fontSize:'9px', letterSpacing:'0.1em' }),
}

export default function AutoMode() {
  const [tab,         setTab]        = useState('control')
  const [status,      setStatus]     = useState(null)
  const [execStatus,  setExecStatus] = useState(null)
  const [queue,       setQueue]      = useState([])
  const [feed,        setFeed]       = useState([])
  const [selected,    setSelected]   = useState(['hubstaff','remoteok','weworkremotely'])
  const [yourName,    setYourName]   = useState('Ibrahim')
  const [yourSkills,  setYourSkills] = useState('Python, automation, web scraping, AI integration, FastAPI')
  const [expanded,    setExpanded]   = useState({})
  const feedRef  = useRef(null)
  const sseRef   = useRef(null)

  // ── SSE live feed ──────────────────────────────────────────────────────────
  useEffect(() => {
    const connect = () => {
      const es = new EventSource(`${API}/orchestrator/feed`)
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data)
          if (d.ping) return
          setFeed(f => [...f.slice(-199), d])
        } catch {}
      }
      es.onerror = () => { es.close(); setTimeout(connect, 3000) }
      sseRef.current = es
    }
    connect()
    return () => sseRef.current?.close()
  }, [])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [feed])

  // ── Polling ────────────────────────────────────────────────────────────────
  useEffect(() => {
    const poll = () => { loadStatus(); loadQueue(); loadExecStatus() }
    poll()
    const t = setInterval(poll, 2500)
    return () => clearInterval(t)
  }, [])

  const loadStatus     = async () => { try { const r = await fetch(`${API}/orchestrator/status`); if (r.ok) setStatus(await r.json()) } catch {} }
  const loadExecStatus = async () => { try { const r = await fetch(`${API}/automation/executor/status`); if (r.ok) setExecStatus(await r.json()) } catch {} }
  const loadQueue      = async () => {
    try {
      const r = await fetch(`${API}/automation/queue?limit=100`)
      if (r.ok) setQueue((await r.json()).queue || [])
    } catch {}
  }

  // ── Actions ────────────────────────────────────────────────────────────────
  const startPipeline = async () => {
    await fetch(`${API}/orchestrator/start`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ platforms:selected, your_name:yourName, your_skills:yourSkills, max_per_platform:10, min_score:30, max_generate:5 })
    })
    loadStatus()
  }
  const stopPipeline = async () => { await fetch(`${API}/orchestrator/stop`, {method:'POST'}); loadStatus() }

  const approveItem = async (qid) => {
    await fetch(`${API}/automation/queue/${qid}/status?status=approved`, {method:'PATCH'})
    loadQueue()
  }
  const rejectItem = async (qid) => {
    await fetch(`${API}/automation/queue/${qid}/status?status=rejected`, {method:'PATCH'})
    loadQueue()
  }

  // Approve + immediately submit via Playwright
  const approveAndSubmit = async (qid) => {
    await fetch(`${API}/automation/queue/${qid}/status?status=approved`, {method:'PATCH'})
    await fetch(`${API}/automation/queue/${qid}/execute`, {method:'POST'})
    loadQueue(); loadExecStatus()
  }

  // Approve all pending then execute them all
  const approveAllAndSubmit = async () => {
    const pending = queue.filter(q => q.status === 'pending')
    for (const q of pending) {
      await fetch(`${API}/automation/queue/${q.id}/status?status=approved`, {method:'PATCH'})
    }
    await fetch(`${API}/automation/execute-approved`, {method:'POST'})
    setTimeout(() => { loadQueue(); loadExecStatus() }, 1000)
  }

  // Execute all already-approved items
  const executeApproved = async () => {
    await fetch(`${API}/automation/execute-approved`, {method:'POST'})
    loadExecStatus()
  }

  const stopExecutor = async () => { await fetch(`${API}/automation/executor/stop`, {method:'POST'}); loadExecStatus() }
  const clearDone    = async () => { await fetch(`${API}/automation/queue`, {method:'DELETE'}); loadQueue() }
  const clearFeed    = () => setFeed([])

  const toggle = (id) => setSelected(s => s.includes(id) ? s.filter(x=>x!==id) : [...s, id])

  const running      = status?.running
  const execRunning  = execStatus?.running
  const pct          = status?.progress || 0
  const pendingQ     = queue.filter(q => q.status === 'pending').length
  const approvedQ    = queue.filter(q => q.status === 'approved').length
  const doneQ        = queue.filter(q => q.status === 'done').length

  return (
    <div style={S.page}>
      {/* ── Header ── */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'20px', flexWrap:'wrap', gap:'10px' }}>
        <div>
          <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.4)', letterSpacing:'0.2em', marginBottom:'4px' }}>JARVIS OS // V4</div>
          <div style={{ fontSize:'18px', fontWeight:'700', color:'#00d4ff', letterSpacing:'0.05em' }}>⟳ AUTONOMOUS MODE</div>
        </div>
        <div style={{ display:'flex', gap:'6px', alignItems:'center' }}>
          {/* Live status dot */}
          <div style={{ width:8, height:8, borderRadius:'50%', background: running||execRunning ? '#00ff88' : 'rgba(255,255,255,0.15)', boxShadow: running||execRunning ? '0 0 8px #00ff88' : 'none', animation: running||execRunning ? 'pulse 1.5s infinite' : 'none' }} />
          <span style={{ fontSize:'9px', color:'rgba(255,255,255,0.35)', fontFamily:'monospace' }}>{running ? 'SCANNING' : execRunning ? 'SUBMITTING' : 'IDLE'}</span>
          {['control','queue','feed'].map(t => (
            <button key={t} style={S.tabBtn(tab===t)} onClick={()=>setTab(t)}>
              {t==='queue' ? `QUEUE${pendingQ>0?` (${pendingQ})`:''}` : t.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* ── CONTROL TAB ── */}
      {tab==='control' && (
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'14px' }}>

          {/* Left column */}
          <div>
            {/* Platform selector */}
            <div style={S.card}>
              <div style={S.label}>STEP 1 — SELECT PLATFORMS</div>
              <div style={{ display:'flex', flexDirection:'column', gap:'7px' }}>
                {PLATFORMS.map(p => (
                  <label key={p.id} style={{ display:'flex', alignItems:'center', gap:'10px', cursor:'pointer', fontSize:'11px', color: selected.includes(p.id)?p.color:'rgba(255,255,255,0.25)' }}>
                    <input type="checkbox" checked={selected.includes(p.id)} onChange={()=>toggle(p.id)} style={{ accentColor:p.color }} />
                    {p.label}
                  </label>
                ))}
              </div>
            </div>

            {/* Profile */}
            <div style={S.card}>
              <div style={S.label}>STEP 2 — YOUR PROFILE</div>
              <div style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'5px' }}>YOUR NAME</div>
              <input value={yourName} onChange={e=>setYourName(e.target.value)} style={{...S.inp, marginBottom:'10px'}} />
              <div style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'5px' }}>YOUR SKILLS</div>
              <textarea value={yourSkills} onChange={e=>setYourSkills(e.target.value)} rows={3} style={{...S.inp, resize:'vertical'}} />
            </div>

            {/* Start/Stop pipeline */}
            <div style={S.card}>
              <div style={S.label}>STEP 3 — SCAN & GENERATE</div>
              <p style={{ fontSize:'11px', color:'rgba(255,255,255,0.4)', lineHeight:1.6, marginBottom:'12px' }}>
                Jarvis will scan selected platforms, score jobs, and draft proposals.
                They will appear in the <strong style={{color:'#ff9500'}}>QUEUE</strong> tab for your review.
                Nothing is submitted until you approve.
              </p>
              <div style={{ display:'flex', gap:'8px' }}>
                <button onClick={startPipeline} disabled={running||selected.length===0}
                  style={{ padding:'9px 20px', borderRadius:'3px', border:'1px solid #00ff88', background: running||selected.length===0 ? 'rgba(0,255,136,0.05)' : 'rgba(0,255,136,0.1)', color: running ? '#888' : '#00ff88', fontFamily:'monospace', fontSize:'10px', cursor: running||selected.length===0 ? 'not-allowed':'pointer', letterSpacing:'0.1em' }}>
                  {running ? '⟳ SCANNING…' : '▶ START SCAN'}
                </button>
                {running && (
                  <button onClick={stopPipeline}
                    style={{ padding:'9px 16px', borderRadius:'3px', border:'1px solid #ff4444', background:'rgba(255,68,68,0.1)', color:'#ff4444', fontFamily:'monospace', fontSize:'10px', cursor:'pointer' }}>
                    ■ STOP
                  </button>
                )}
              </div>
            </div>

            {/* Executor controls */}
            <div style={{...S.card, borderColor:'rgba(0,255,136,0.2)'}}>
              <div style={{...S.label, color:'rgba(0,255,136,0.5)'}}>STEP 4 — SUBMIT APPROVED BIDS</div>
              <p style={{ fontSize:'11px', color:'rgba(255,255,255,0.4)', lineHeight:1.6, marginBottom:'12px' }}>
                After approving items in the Queue, Jarvis uses Playwright to open each job page,
                fill the bid form with your proposal, and click <strong style={{color:'#00ff88'}}>Place Bid</strong>.
                You stay in control — nothing submits without your approval.
              </p>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'8px', marginBottom:'12px' }}>
                <div style={{ background:'rgba(0,10,20,0.6)', border:'1px solid rgba(0,255,136,0.15)', borderRadius:'3px', padding:'10px', textAlign:'center' }}>
                  <div style={{ fontSize:'8px', color:'rgba(0,255,136,0.5)', marginBottom:'4px' }}>PENDING</div>
                  <div style={{ fontSize:'22px', fontWeight:'700', color:'#ff9500' }}>{pendingQ}</div>
                </div>
                <div style={{ background:'rgba(0,10,20,0.6)', border:'1px solid rgba(0,255,136,0.15)', borderRadius:'3px', padding:'10px', textAlign:'center' }}>
                  <div style={{ fontSize:'8px', color:'rgba(0,255,136,0.5)', marginBottom:'4px' }}>APPROVED</div>
                  <div style={{ fontSize:'22px', fontWeight:'700', color:'#00ff88' }}>{approvedQ}</div>
                </div>
                <div style={{ background:'rgba(0,10,20,0.6)', border:'1px solid rgba(0,255,136,0.15)', borderRadius:'3px', padding:'10px', textAlign:'center' }}>
                  <div style={{ fontSize:'8px', color:'rgba(0,255,136,0.5)', marginBottom:'4px' }}>SUBMITTED</div>
                  <div style={{ fontSize:'22px', fontWeight:'700', color:'#00d4ff' }}>{doneQ}</div>
                </div>
                <div style={{ background:'rgba(0,10,20,0.6)', border:'1px solid rgba(0,255,136,0.15)', borderRadius:'3px', padding:'10px', textAlign:'center' }}>
                  <div style={{ fontSize:'8px', color:'rgba(0,255,136,0.5)', marginBottom:'4px' }}>EXECUTOR</div>
                  <div style={{ fontSize:'11px', fontWeight:'700', color: execRunning?'#00ff88':'rgba(255,255,255,0.25)' }}>{execRunning?'● RUNNING':'○ IDLE'}</div>
                </div>
              </div>
              <div style={{ display:'flex', gap:'8px', flexWrap:'wrap' }}>
                <button onClick={approveAllAndSubmit} disabled={pendingQ===0||execRunning}
                  style={{ padding:'9px 16px', borderRadius:'3px', border:'1px solid #00ff88', background: pendingQ===0||execRunning ? 'rgba(0,255,136,0.03)' : 'rgba(0,255,136,0.12)', color: pendingQ===0||execRunning ? '#555':'#00ff88', fontFamily:'monospace', fontSize:'9px', cursor: pendingQ===0||execRunning ? 'not-allowed':'pointer', letterSpacing:'0.08em' }}>
                  ⚡ APPROVE ALL + SUBMIT
                </button>
                <button onClick={executeApproved} disabled={approvedQ===0||execRunning}
                  style={{ padding:'9px 16px', borderRadius:'3px', border:'1px solid #a78bfa', background:'rgba(167,139,250,0.1)', color: approvedQ===0||execRunning ? '#555':'#a78bfa', fontFamily:'monospace', fontSize:'9px', cursor: approvedQ===0||execRunning ? 'not-allowed':'pointer', letterSpacing:'0.08em' }}>
                  ▶ SUBMIT APPROVED ({approvedQ})
                </button>
                {execRunning && (
                  <button onClick={stopExecutor}
                    style={{ padding:'9px 14px', borderRadius:'3px', border:'1px solid #ff4444', background:'rgba(255,68,68,0.1)', color:'#ff4444', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                    ■ STOP
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Right column — status */}
          <div>
            {status && (
              <div style={S.card}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'12px' }}>
                  <div style={S.label}>PIPELINE STATUS</div>
                  <span style={{ fontSize:'9px', color: running?'#00ff88':'rgba(255,255,255,0.2)', fontFamily:'monospace' }}>{running?'● RUNNING':'○ IDLE'}</span>
                </div>
                <div style={{ fontSize:'10px', color:'rgba(255,255,255,0.35)', marginBottom:'8px', letterSpacing:'0.1em' }}>{(status.stage||'idle').toUpperCase()}</div>
                <div style={{ height:'4px', background:'rgba(255,255,255,0.06)', borderRadius:'2px', marginBottom:'16px' }}>
                  <div style={{ height:'100%', width:`${pct}%`, background:'linear-gradient(90deg,#00d4ff,#00ff88)', borderRadius:'2px', transition:'width 0.5s' }} />
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'8px', marginBottom:'14px' }}>
                  {[
                    ['Jobs Found',   status.stats?.jobs_found||0,    '#00d4ff'],
                    ['Qualified',    status.stats?.jobs_qualified||0,'#ff9500'],
                    ['Proposals',    status.stats?.proposals_gen||0, '#00ff88'],
                    ['Cycles',       status.stats?.cycles||0,        '#a78bfa'],
                  ].map(([l,v,c]) => (
                    <div key={l} style={{ background:'rgba(0,10,20,0.6)', border:`1px solid ${c}22`, borderRadius:'3px', padding:'10px' }}>
                      <div style={{ fontSize:'8px', color:`${c}88`, letterSpacing:'0.15em', marginBottom:'4px' }}>{l}</div>
                      <div style={{ fontSize:'20px', fontWeight:'700', color:c, fontFamily:'sans-serif' }}>{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Mini live feed on control tab */}
            <div style={S.card}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'10px' }}>
                <div style={S.label}>LIVE FEED</div>
                <button onClick={clearFeed} style={{ fontSize:'8px', color:'rgba(255,255,255,0.25)', background:'none', border:'none', cursor:'pointer', fontFamily:'monospace' }}>CLEAR</button>
              </div>
              <div ref={feedRef} style={{ background:'rgba(0,4,8,0.9)', borderRadius:'3px', padding:'10px', height:'260px', overflowY:'auto', fontFamily:'monospace', fontSize:'9px' }}>
                {feed.length === 0 && <div style={{ color:'rgba(255,255,255,0.15)' }}>Waiting for activity…</div>}
                {feed.map((e, i) => (
                  <div key={i} style={{ lineHeight:'1.9', color: LEVEL_COLOR[e.level]||'rgba(0,212,255,0.5)' }}>
                    <span style={{ color:'rgba(255,255,255,0.2)', marginRight:'6px' }}>{e.ts}</span>
                    <span style={{ color:'rgba(255,255,255,0.35)', marginRight:'6px' }}>[{e.agent}]</span>
                    {e.msg}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── QUEUE TAB ── */}
      {tab==='queue' && (
        <div>
          <div style={{ display:'flex', gap:'8px', marginBottom:'16px', alignItems:'center', flexWrap:'wrap' }}>
            <button onClick={loadQueue} style={S.tabBtn(false)}>↺ REFRESH</button>
            {approvedQ > 0 && !execRunning && (
              <button onClick={executeApproved}
                style={{ padding:'5px 14px', borderRadius:'3px', border:'1px solid #00ff88', background:'rgba(0,255,136,0.1)', color:'#00ff88', cursor:'pointer', fontFamily:'monospace', fontSize:'9px', letterSpacing:'0.1em' }}>
                ▶ SUBMIT ALL APPROVED ({approvedQ})
              </button>
            )}
            {execRunning && (
              <button onClick={stopExecutor} style={{ padding:'5px 14px', borderRadius:'3px', border:'1px solid #ff4444', background:'rgba(255,68,68,0.1)', color:'#ff4444', cursor:'pointer', fontFamily:'monospace', fontSize:'9px' }}>■ STOP EXECUTOR</button>
            )}
            <button onClick={clearDone} style={{ padding:'5px 14px', borderRadius:'3px', border:'1px solid rgba(255,68,68,0.3)', background:'rgba(255,68,68,0.06)', color:'rgba(255,68,68,0.6)', cursor:'pointer', fontFamily:'monospace', fontSize:'9px' }}>CLEAR DONE</button>
            <span style={{ fontSize:'9px', color:'rgba(255,255,255,0.25)', fontFamily:'monospace', marginLeft:'auto' }}>
              {pendingQ} pending · {approvedQ} approved · {doneQ} done · {queue.filter(q=>q.status==='failed').length} failed
            </span>
          </div>

          {queue.length === 0 && (
            <div style={{ textAlign:'center', padding:'60px 20px', color:'rgba(255,255,255,0.2)', fontSize:'12px', fontFamily:'monospace' }}>
              Queue is empty.<br/>Run Auto Mode to generate proposals for review.
            </div>
          )}

          <div style={{ display:'flex', flexDirection:'column', gap:'10px' }}>
            {queue.map(q => {
              const payload  = q.payload || {}
              const app      = payload.application || ''
              const job      = payload.job || {}
              const isOpen   = expanded[q.id]
              const SC = { pending:'#ff9500', approved:'#00ff88', done:'#888', rejected:'#ff4444', failed:'#ff4444', executing:'#a78bfa' }
              const sc = SC[q.status] || '#888'

              return (
                <div key={q.id} style={{ borderRadius:'4px', background:'rgba(0,8,18,0.8)', border:`1px solid ${sc}22`, overflow:'hidden' }}>
                  {/* Header */}
                  <div style={{ padding:'12px 16px', display:'flex', alignItems:'center', gap:'10px', flexWrap:'wrap', cursor:'pointer' }} onClick={() => setExpanded(e=>({...e,[q.id]:!e[q.id]}))}>
                    <Badge label={q.status} color={sc} />
                    <Badge label={q.platform} color="#00d4ff" />
                    <span style={{ fontSize:'12px', fontWeight:'600', color:'#c4e4ef', flex:1 }}>{q.job_title}</span>
                    {q.status === 'executing' && <span style={{ fontSize:'9px', color:'#a78bfa', fontFamily:'monospace', animation:'pulse 1s infinite' }}>● SUBMITTING…</span>}
                    <span style={{ fontSize:'9px', color:'rgba(255,255,255,0.25)', fontFamily:'monospace' }}>{isOpen?'▲':'▼'}</span>
                  </div>

                  {/* Expanded proposal */}
                  {isOpen && (
                    <div style={{ padding:'0 16px 14px', borderTop:'1px solid rgba(255,255,255,0.05)' }}>
                      {app && (
                        <div style={{ background:'rgba(0,4,8,0.8)', padding:'12px', borderRadius:'3px', marginTop:'12px', marginBottom:'12px', fontSize:'11px', color:'rgba(255,255,255,0.55)', lineHeight:1.7, whiteSpace:'pre-wrap', maxHeight:'200px', overflowY:'auto' }}>
                          {app}
                        </div>
                      )}
                      <div style={{ display:'flex', gap:'8px', flexWrap:'wrap' }}>
                        {q.status === 'pending' && <>
                          {/* Approve + Playwright submit in one click */}
                          <button onClick={() => approveAndSubmit(q.id)}
                            style={{ padding:'7px 16px', borderRadius:'3px', border:'1px solid #00ff88', background:'rgba(0,255,136,0.12)', color:'#00ff88', fontFamily:'monospace', fontSize:'9px', cursor:'pointer', letterSpacing:'0.1em' }}>
                            ✓ APPROVE + SUBMIT
                          </button>
                          {/* Approve only (queue for batch submit later) */}
                          <button onClick={() => approveItem(q.id)}
                            style={{ padding:'7px 14px', borderRadius:'3px', border:'1px solid rgba(0,255,136,0.4)', background:'rgba(0,255,136,0.06)', color:'rgba(0,255,136,0.7)', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                            ✓ APPROVE ONLY
                          </button>
                          <button onClick={() => rejectItem(q.id)}
                            style={{ padding:'7px 14px', borderRadius:'3px', border:'1px solid rgba(255,68,68,0.4)', background:'rgba(255,68,68,0.07)', color:'rgba(255,68,68,0.7)', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                            ✗ REJECT
                          </button>
                        </>}
                        {q.status === 'approved' && !execRunning && (
                          <button onClick={() => { fetch(`${API}/automation/queue/${q.id}/execute`,{method:'POST'}); loadExecStatus() }}
                            style={{ padding:'7px 16px', borderRadius:'3px', border:'1px solid #a78bfa', background:'rgba(167,139,250,0.1)', color:'#a78bfa', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                            ▶ SUBMIT THIS ONE
                          </button>
                        )}
                        {app && (
                          <button onClick={() => navigator.clipboard?.writeText(app)}
                            style={{ padding:'7px 12px', borderRadius:'3px', border:'1px solid rgba(255,255,255,0.15)', background:'transparent', color:'rgba(255,255,255,0.35)', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                            ⎘ COPY PROPOSAL
                          </button>
                        )}
                        {job.link && (
                          <button onClick={() => window.open(job.link,'_blank')}
                            style={{ padding:'7px 12px', borderRadius:'3px', border:'1px solid rgba(0,212,255,0.25)', background:'transparent', color:'rgba(0,212,255,0.5)', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                            ↗ OPEN JOB
                          </button>
                        )}
                        {q.status === 'done' && <span style={{ fontSize:'10px', color:'#00ff88', fontFamily:'monospace', alignSelf:'center' }}>✓ BID SUBMITTED</span>}
                        {q.status === 'failed' && <span style={{ fontSize:'10px', color:'#ff4444', fontFamily:'monospace', alignSelf:'center' }}>✗ FAILED — check feed for details</span>}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── FEED TAB ── */}
      {tab==='feed' && (
        <div style={S.card}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'12px' }}>
            <div style={S.label}>LIVE AGENT FEED — REAL TIME</div>
            <button onClick={clearFeed} style={{ fontSize:'8px', color:'rgba(255,255,255,0.3)', background:'none', border:'1px solid rgba(255,255,255,0.1)', padding:'3px 10px', borderRadius:'3px', cursor:'pointer', fontFamily:'monospace' }}>CLEAR</button>
          </div>
          <div style={{ background:'rgba(0,4,8,0.95)', borderRadius:'3px', padding:'14px', height:'calc(100vh - 220px)', overflowY:'auto', fontFamily:'monospace', fontSize:'10px' }}>
            {feed.length === 0 && <div style={{ color:'rgba(255,255,255,0.15)' }}>No events yet. Start Auto Mode or submit a bid to see live activity.</div>}
            {feed.map((e, i) => (
              <div key={i} style={{ lineHeight:'2', borderBottom:'1px solid rgba(255,255,255,0.03)', paddingBottom:'1px' }}>
                <span style={{ color:'rgba(255,255,255,0.18)', marginRight:'8px', fontSize:'9px' }}>{e.ts}</span>
                <span style={{ marginRight:'8px', padding:'1px 6px', borderRadius:'2px', fontSize:'8px', background:`${LEVEL_COLOR[e.level]||'#00d4ff'}18`, color:LEVEL_COLOR[e.level]||'#00d4ff', border:`1px solid ${LEVEL_COLOR[e.level]||'#00d4ff'}33` }}>{e.agent}</span>
                <span style={{ color: LEVEL_COLOR[e.level]||'rgba(200,230,240,0.7)' }}>{e.msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
    </div>
  )
}
