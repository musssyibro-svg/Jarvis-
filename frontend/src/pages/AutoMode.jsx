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
  card:    { border:'1px solid rgba(0,212,255,0.15)', borderRadius:'4px', padding:'13px', background:'rgba(0,10,20,0.75)', marginBottom:'9px' },
  label:   { fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'9px' },
  inp:     { width:'100%', background:'rgba(0,10,20,0.8)', border:'1px solid rgba(0,212,255,0.2)', outline:'none', color:'#c8e8f0', padding:'7px 10px', fontSize:'11px', fontFamily:'monospace', borderRadius:'3px', boxSizing:'border-box' },
  tabBtn:  (active) => ({ padding:'5px 14px', borderRadius:'3px', border:`1px solid ${active?'#00d4ff':'rgba(255,255,255,0.1)'}`, background:active?'rgba(0,212,255,0.1)':'transparent', color:active?'#00d4ff':'rgba(255,255,255,0.35)', cursor:'pointer', fontFamily:'monospace', fontSize:'9px', letterSpacing:'0.1em' }),
}

export default function AutoMode() {
  const [tab,         setTab]        = useState('control')
  const [status,      setStatus]     = useState(null)
  const [execStatus,  setExecStatus] = useState(null)
  const [queue,       setQueue]      = useState([])
  const [feed,        setFeed]       = useState([])
  const [selected,    setSelected]   = useState(['hubstaff','remoteok','weworkremotely','peopleperhour'])
  const [yourName,    setYourName]   = useState('Ibrahim')
  const [yourSkills,  setYourSkills] = useState('Python, automation, web scraping, AI integration, FastAPI')
  const [hourlyRate,  setHourlyRate] = useState('15')
  const [portfolio,   setPortfolio]  = useState('')
  const [autoSubmit,  setAutoSubmit] = useState(false)
  const [profileSaved,setProfileSaved]= useState(false)
  const [sessions,    setSessions]   = useState([])
  const [sessBusy,    setSessBusy]   = useState(false)
  const [vaultForm,   setVaultForm]  = useState({ platform:'freelancer', username:'', password:'' })
  const [vaultMsg,    setVaultMsg]   = useState('')
  const [income,      setIncome]     = useState(null)
  const [intervalMin, setIntervalMin]= useState(20)
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
    const poll = () => { loadStatus(); loadQueue(); loadExecStatus(); loadIncome() }
    poll()
    const t = setInterval(poll, 6000)
    return () => clearInterval(t)
  }, [])

  // Load the persistent profile + platform login status once on mount
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/automation/profile`)
        if (r.ok) {
          const p = await r.json()
          if (p.name)        setYourName(p.name)
          if (p.skills)      setYourSkills(p.skills)
          if (p.hourly_rate) setHourlyRate(String(p.hourly_rate))
          if (p.portfolio)   setPortfolio(p.portfolio)
          setAutoSubmit(!!p.auto_submit)
        }
      } catch {}
      loadSessions(false)
    })()
  }, [])

  const loadSessions = async (refresh) => {
    setSessBusy(true)
    try {
      const r = await fetch(`${API}/sessions/status${refresh?'?refresh=1':''}`)
      if (r.ok) setSessions((await r.json()).platforms || [])
    } catch {} finally { setSessBusy(false) }
  }

  const openLogin = async (pid) => {
    try {
      const r = await fetch(`${API}/sessions/open-login/${pid}`, {method:'POST'})
      const d = await r.json()
      setVaultMsg(d.message || d.error || '')
    } catch(e) { setVaultMsg(String(e)) }
  }

  const saveVault = async () => {
    if (!vaultForm.username || !vaultForm.password) { setVaultMsg('Enter username and password'); return }
    try {
      const r = await fetch(`${API}/sessions/vault`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(vaultForm)
      })
      const d = await r.json()
      setVaultMsg(r.ok ? `Saved ✓ (encrypted locally as ${d.username})` : (d.detail||'failed'))
      if (r.ok) setVaultForm(f => ({...f, password:''}))
    } catch(e) { setVaultMsg(String(e)) }
  }

  const saveProfile = async () => {
    try {
      await fetch(`${API}/automation/profile`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ name:yourName, skills:yourSkills, hourly_rate:hourlyRate,
                               portfolio, auto_submit:autoSubmit })
      })
      setProfileSaved(true); setTimeout(()=>setProfileSaved(false), 2000)
    } catch {}
  }

  const loadStatus     = async () => { try { const r = await fetch(`${API}/orchestrator/status`); if (r.ok) setStatus(await r.json()) } catch {} }
  const loadIncome     = async () => { try { const r = await fetch(`${API}/automation/income/status`); if (r.ok) { const d = await r.json(); setIncome(d); if (d.interval_min) setIntervalMin(d.interval_min) } } catch {} }
  const toggleIncome   = async () => {
    if (income?.enabled) { await fetch(`${API}/automation/income/stop`, {method:'POST'}) }
    else { await fetch(`${API}/automation/income/start`, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ interval_min: Number(intervalMin)||20, platforms: selected }) }) }
    loadIncome()
  }
  const incomeRunNow   = async () => { await fetch(`${API}/automation/income/run-now`, {method:'POST'}); loadIncome() }
  const loadExecStatus = async () => { try { const r = await fetch(`${API}/automation/executor/status`); if (r.ok) setExecStatus(await r.json()) } catch {} }
  const loadQueue      = async () => {
    try {
      const r = await fetch(`${API}/automation/queue?limit=100`)
      if (r.ok) setQueue((await r.json()).queue || [])
    } catch {}
  }

  // ── Actions ────────────────────────────────────────────────────────────────
  const startPipeline = async () => {
    await saveProfile()   // scan always uses the freshest profile
    await fetch(`${API}/orchestrator/start`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ platforms:selected, your_name:yourName, your_skills:yourSkills, max_per_platform:15, min_score:30, max_generate:10 })
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
  const readyQ       = queue.filter(q => q.status === 'ready').length
  const needsLoginQ  = queue.filter(q => q.status === 'needs_login').length

  return (
    <div style={S.page}>
      {/* ── Header ── */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'20px', flexWrap:'wrap', gap:'10px' }}>
        <div>
          <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.4)', letterSpacing:'0.2em', marginBottom:'4px' }}>AUTONOMOUS FREELANCE</div>
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
            {/* Platform login sessions */}
            <div style={{...S.card, borderColor:'rgba(167,139,250,0.3)'}}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <div style={{...S.label, color:'rgba(167,139,250,0.6)'}}>STEP 0 — PLATFORM LOGINS</div>
                <button onClick={()=>loadSessions(true)} disabled={sessBusy}
                  style={{ fontSize:'8px', color:'#a78bfa', background:'none', border:'1px solid rgba(167,139,250,0.3)', padding:'3px 10px', borderRadius:'3px', cursor:'pointer', fontFamily:'monospace' }}>
                  {sessBusy ? '⟳ CHECKING…' : '↺ RE-CHECK'}
                </button>
              </div>
              <p style={{ fontSize:'10px', color:'rgba(255,255,255,0.35)', lineHeight:1.6, margin:'8px 0 10px' }}>
                Log in <strong style={{color:'#a78bfa'}}>once</strong> per platform — Jarvis keeps the session in its own
                browser profile and reuses it for form-filling and bid submission. Credentials you save
                below are <strong style={{color:'#a78bfa'}}>encrypted on this PC</strong> and only used to pre-fill login forms.
              </p>
              <div style={{ display:'flex', flexWrap:'wrap', gap:'6px', marginBottom:'10px' }}>
                {sessions.length===0 && <span style={{ fontSize:'9px', color:'rgba(255,255,255,0.25)', fontFamily:'monospace' }}>{sessBusy?'Checking sessions…':'No status yet — press RE-CHECK'}</span>}
                {sessions.map(s => {
                  const c = s.logged_in===true ? '#00ff88' : s.logged_in===false ? '#ff4444' : '#ff9500'
                  return (
                    <div key={s.platform} style={{ display:'flex', alignItems:'center', gap:'6px', border:`1px solid ${c}44`, background:`${c}0d`, borderRadius:'3px', padding:'5px 8px' }}>
                      <span style={{ width:6, height:6, borderRadius:'50%', background:c, boxShadow:`0 0 5px ${c}` }} />
                      <span style={{ fontSize:'9px', color:'#c8e8f0', fontFamily:'monospace' }}>{s.label}</span>
                      <span style={{ fontSize:'8px', color:c, fontFamily:'monospace' }}>
                        {s.logged_in===true ? 'LOGGED IN' : s.logged_in===false ? 'LOGGED OUT' : '?'}
                      </span>
                      {s.logged_in!==true && (
                        <button onClick={()=>openLogin(s.platform)}
                          style={{ fontSize:'8px', color:'#a78bfa', background:'none', border:'1px solid rgba(167,139,250,0.4)', borderRadius:'2px', padding:'2px 6px', cursor:'pointer', fontFamily:'monospace' }}>
                          LOGIN
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
              <div style={{ borderTop:'1px solid rgba(167,139,250,0.15)', paddingTop:'10px' }}>
                <div style={{ fontSize:'8px', color:'rgba(167,139,250,0.5)', letterSpacing:'0.15em', marginBottom:'6px' }}>CREDENTIAL VAULT (LOCAL, ENCRYPTED)</div>
                <div style={{ display:'flex', gap:'6px', flexWrap:'wrap' }}>
                  <select value={vaultForm.platform} onChange={e=>setVaultForm(f=>({...f,platform:e.target.value}))}
                    style={{...S.inp, width:'130px', cursor:'pointer'}}>
                    {['freelancer','upwork','fiverr','peopleperhour','hubstaff','contra','wellfound'].map(p=><option key={p} value={p}>{p}</option>)}
                  </select>
                  <input value={vaultForm.username} onChange={e=>setVaultForm(f=>({...f,username:e.target.value}))}
                    placeholder="email / username" style={{...S.inp, flex:1, minWidth:'120px'}} />
                  <input type="password" value={vaultForm.password} onChange={e=>setVaultForm(f=>({...f,password:e.target.value}))}
                    placeholder="password" style={{...S.inp, flex:1, minWidth:'100px'}} />
                  <button onClick={saveVault}
                    style={{ padding:'6px 12px', borderRadius:'3px', border:'1px solid #a78bfa', background:'rgba(167,139,250,0.12)', color:'#a78bfa', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                    🔐 SAVE
                  </button>
                </div>
                {vaultMsg && <div style={{ fontSize:'9px', color:'#a78bfa', marginTop:'6px', fontFamily:'monospace' }}>{vaultMsg}</div>}
              </div>
            </div>

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

            {/* Profile — persisted; feeds every proposal the LLM writes */}
            <div style={S.card}>
              <div style={S.label}>STEP 2 — YOUR PROFILE (SAVED &amp; USED IN EVERY PROPOSAL)</div>
              <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr', gap:'8px', marginBottom:'10px' }}>
                <div>
                  <div style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'5px' }}>YOUR NAME</div>
                  <input value={yourName} onChange={e=>setYourName(e.target.value)} style={S.inp} />
                </div>
                <div>
                  <div style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'5px' }}>RATE ($/HR)</div>
                  <input value={hourlyRate} onChange={e=>setHourlyRate(e.target.value)} style={S.inp} />
                </div>
              </div>
              <div style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'5px' }}>YOUR SKILLS</div>
              <textarea value={yourSkills} onChange={e=>setYourSkills(e.target.value)} rows={2} style={{...S.inp, resize:'vertical', marginBottom:'10px'}} />
              <div style={{ fontSize:'9px', color:'rgba(255,255,255,0.3)', marginBottom:'5px' }}>PORTFOLIO / PAST WORK HIGHLIGHTS</div>
              <textarea value={portfolio} onChange={e=>setPortfolio(e.target.value)} rows={2} style={{...S.inp, resize:'vertical', marginBottom:'10px'}}
                placeholder="e.g. Built a price-monitoring scraper handling 50k pages/day; automated invoice pipeline for a retail store…" />
              <div style={{ display:'flex', alignItems:'center', gap:'10px', flexWrap:'wrap' }}>
                <button onClick={saveProfile}
                  style={{ padding:'7px 16px', borderRadius:'3px', border:'1px solid #00d4ff', background:'rgba(0,212,255,0.1)', color: profileSaved?'#00ff88':'#00d4ff', fontFamily:'monospace', fontSize:'9px', cursor:'pointer', letterSpacing:'0.08em' }}>
                  {profileSaved ? '✓ SAVED' : '💾 SAVE PROFILE'}
                </button>
                <label style={{ display:'flex', alignItems:'center', gap:'6px', fontSize:'10px', color: autoSubmit?'#ff9500':'rgba(255,255,255,0.4)', cursor:'pointer' }}>
                  <input type="checkbox" checked={autoSubmit} onChange={e=>setAutoSubmit(e.target.checked)} style={{ accentColor:'#ff9500' }} />
                  Full auto-submit (skip the approve click — Jarvis bids on its own)
                </label>
              </div>
            </div>

            {/* Start/Stop pipeline */}
            <div style={S.card}>
              <div style={S.label}>STEP 3 — SCAN & GENERATE</div>
              <p style={{ fontSize:'11px', color:'rgba(255,255,255,0.4)', lineHeight:1.6, marginBottom:'12px' }}>
                Full pipeline: <strong style={{color:'#00d4ff'}}>scan</strong> → <strong style={{color:'#ff9500'}}>score &amp; drop bad fits</strong> → <strong style={{color:'#00ff88'}}>write a proposal for every good job</strong> → queue.
                Drafts appear in the <strong style={{color:'#ff9500'}}>QUEUE</strong> tab — one click submits them through your logged-in browser.
                {autoSubmit ? ' Auto-submit is ON: Jarvis will bid without asking.' : ' Nothing is submitted until you say yes.'}
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

            {/* Income Engine — the always-on loop */}
            <div style={{...S.card, borderColor: income?.enabled ? 'rgba(0,255,136,0.5)' : 'rgba(255,149,0,0.3)',
                         boxShadow: income?.enabled ? '0 0 20px rgba(0,255,136,0.12)' : 'none' }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <div style={{...S.label, color: income?.enabled ? '#00ff88' : '#ff9500'}}>
                  ⚙ INCOME ENGINE {income?.enabled ? '— RUNNING 24/7' : '— OFF'}
                </div>
                <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                  <span style={{ width:8, height:8, borderRadius:'50%',
                    background: income?.enabled ? '#00ff88' : 'rgba(255,255,255,0.2)',
                    boxShadow: income?.enabled ? '0 0 8px #00ff88' : 'none',
                    animation: income?.enabled ? 'pulse 1.6s infinite' : 'none' }} />
                </div>
              </div>
              <p style={{ fontSize:'11px', color:'rgba(255,255,255,0.4)', lineHeight:1.6, margin:'6px 0 12px' }}>
                No button-pressing. Jarvis loops <strong style={{color:'#00d4ff'}}>scan → score → draft → queue</strong> every
                few minutes on the platforms you're logged into, ranks jobs by fit &amp; pay, and drops bad matches.
                {autoSubmit ? ' Auto-submit is ON — it also bids for you.' : ' Approve from the Queue when you\'re ready.'}
              </p>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:'8px', marginBottom:'12px' }}>
                {[['CYCLES', income?.cycles ?? 0, '#00ff88'],
                  ['EVERY', `${income?.interval_min ?? intervalMin}m`, '#00d4ff'],
                  ['STATUS', income?.enabled ? 'LIVE' : 'idle', income?.enabled ? '#00ff88' : '#888']].map(([l,v,c]) => (
                  <div key={l} style={{ background:'rgba(0,10,20,0.6)', border:`1px solid ${c}22`, borderRadius:'3px', padding:'9px', textAlign:'center' }}>
                    <div style={{ fontSize:'8px', color:`${c}99`, letterSpacing:'0.15em', marginBottom:'3px' }}>{l}</div>
                    <div style={{ fontSize:'17px', fontWeight:'700', color:c }}>{v}</div>
                  </div>
                ))}
              </div>
              <div style={{ display:'flex', gap:'8px', alignItems:'center', flexWrap:'wrap' }}>
                <button onClick={toggleIncome}
                  style={{ padding:'9px 18px', borderRadius:'3px',
                    border:`1px solid ${income?.enabled ? '#ff4444' : '#00ff88'}`,
                    background: income?.enabled ? 'rgba(255,68,68,0.1)' : 'rgba(0,255,136,0.12)',
                    color: income?.enabled ? '#ff4444' : '#00ff88',
                    fontFamily:'monospace', fontSize:'10px', cursor:'pointer', letterSpacing:'0.1em' }}>
                  {income?.enabled ? '■ STOP ENGINE' : '▶ START EARNING (24/7)'}
                </button>
                {income?.enabled && (
                  <button onClick={incomeRunNow}
                    style={{ padding:'9px 14px', borderRadius:'3px', border:'1px solid #00d4ff', background:'rgba(0,212,255,0.1)', color:'#00d4ff', fontFamily:'monospace', fontSize:'9px', cursor:'pointer' }}>
                    ⚡ RUN CYCLE NOW
                  </button>
                )}
                <label style={{ display:'flex', alignItems:'center', gap:6, fontSize:'10px', color:'rgba(255,255,255,0.4)' }}>
                  every
                  <input type="number" min="2" value={intervalMin} onChange={e=>setIntervalMin(e.target.value)}
                    style={{...S.inp, width:'54px', padding:'5px'}} />
                  min
                </label>
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
              {(readyQ>0 || needsLoginQ>0) && (
                <div style={{ marginTop:'10px', fontSize:'10px', lineHeight:1.6, color:'rgba(255,255,255,0.5)' }}>
                  {readyQ>0 && <div style={{ color:'#00d4ff' }}>↗ {readyQ} proposal(s) are <strong>ready to apply externally</strong> — those platforms (RemoteOK, WWR, Remote.co) are job boards with no on-site bidding. Open each from the Queue and apply via its link. They didn't fail; there's just nothing to auto-submit there.</div>}
                  {needsLoginQ>0 && <div style={{ color:'#ff9500' }}>🔐 {needsLoginQ} need you logged in to that platform first (STEP 0 above), then re-submit.</div>}
                  <div style={{ color:'rgba(255,255,255,0.4)', marginTop:4 }}>To actually auto-submit bids, scan a <strong>bid platform</strong> (Freelancer / PeoplePerHour / Upwork) you're logged into.</div>
                </div>
              )}
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
              const SC = { pending:'#ff9500', approved:'#00ff88', done:'#888', rejected:'#ff4444', failed:'#ff4444', executing:'#a78bfa', ready:'#00d4ff', needs_login:'#ff9500' }
              const sc = SC[q.status] || '#888'

              return (
                <div key={q.id} style={{ borderRadius:'4px', background:'rgba(0,8,18,0.8)', border:`1px solid ${sc}22`, overflow:'hidden' }}>
                  {/* Header */}
                  <div style={{ padding:'12px 16px', display:'flex', alignItems:'center', gap:'10px', flexWrap:'wrap', cursor:'pointer' }} onClick={() => setExpanded(e=>({...e,[q.id]:!e[q.id]}))}>
                    <Badge label={q.status} color={sc} />
                    <Badge label={q.platform} color="#00d4ff" />
                    {job.job_type && job.job_type !== 'other' && <Badge label={job.job_type} color="#a78bfa" />}
                    {job.est_pay > 0 && <Badge label={`~$${job.est_pay}`} color="#00ff88" />}
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
                        {q.status === 'ready' && <span style={{ fontSize:'10px', color:'#00d4ff', fontFamily:'monospace', alignSelf:'center' }}>↗ APPLY VIA JOB LINK (job board — no on-site bidding)</span>}
                        {q.status === 'needs_login' && <span style={{ fontSize:'10px', color:'#ff9500', fontFamily:'monospace', alignSelf:'center' }}>🔐 LOG IN TO {String(q.platform).toUpperCase()} THEN RE-SUBMIT</span>}
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
