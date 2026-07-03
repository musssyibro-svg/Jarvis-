import { useEffect, useState } from 'react'
import { StatCard, PageHeader, Btn, Badge } from '../components/UI'

import { API } from '../config.js'

const SvcRow = ({ label, ok }) => (
  <div style={{ display:'flex', alignItems:'center', gap:'10px', padding:'8px 0', borderBottom:'1px solid rgba(255,255,255,0.04)', fontSize:'11px' }}>
    <span style={{ width:'6px', height:'6px', borderRadius:'50%', flexShrink:0, background: ok?'#00ff88':'#ff4444', boxShadow:`0 0 6px ${ok?'#00ff88':'#ff4444'}` }}/>
    <span style={{ color:'rgba(255,255,255,0.4)', flex:1, letterSpacing:'0.1em' }}>{label}</span>
    <span style={{ fontSize:'9px', color: ok?'#00ff88':'#ff4444', letterSpacing:'0.15em' }}>{ok?'ONLINE':'OFFLINE'}</span>
  </div>
)

export default function Dashboard() {
  const [sys, setSys]     = useState({ cpu:0, ram:0, disk:0 })
  const [today, setToday] = useState(null)
  const [auto, setAuto]   = useState(null)
  const [online, setOnline] = useState(false)

  useEffect(() => {
    const load = async () => {
      try { const r = await fetch(`${API}/stats`); if(r.ok) setSys(await r.json()) } catch{}
      try { const r = await fetch(`${API}/health`); setOnline(r.ok) } catch{ setOnline(false) }
      try { const r = await fetch(`${API}/automation/today-stats`); if(r.ok) setToday(await r.json()) } catch{}
      try { const r = await fetch(`${API}/automation/status`); if(r.ok) setAuto(await r.json()) } catch{}
    }
    load()
    const t = setInterval(load, 6000)
    return () => clearInterval(t)
  }, [])

  return (
    <div style={{ padding:'28px', overflowY:'auto', height:'100%' }}>
      <PageHeader breadcrumb="COMMAND CENTER" title="⬡ LIVE AGENT STATUS" />

      {/* System */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:'10px', marginBottom:'12px' }}>
        <StatCard label="CPU" value={`${sys.cpu}%`} color="#00d4ff"/>
        <StatCard label="RAM" value={`${sys.ram}%`} color="#00ff88"/>
        <StatCard label="DISK" value={`${sys.disk}%`} color="#ff9500"/>
      </div>

      {/* Today stats */}
      {today && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'10px', marginBottom:'12px' }}>
          <StatCard label="JOBS TODAY"    value={today.jobs_today}      color="#00d4ff"/>
          <StatCard label="APPS QUEUED"   value={today.apps_generated}  color="#00ff88"/>
          <StatCard label="REPLIES TODAY" value={today.replies_today}   color="#ff9500"/>
          <StatCard label="PROJECTS WON"  value={today.projects_won}    color="#ff9500"/>
        </div>
      )}
      {today && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:'10px', marginBottom:'12px' }}>
          <StatCard label="CW TASKS AVAIL" value={today.cw_tasks_avail} color="#00d4ff" sub="Clickworker"/>
          <StatCard label="ZD TASKS AVAIL" value={today.zd_tasks_avail} color="#00ff88" sub="Zuodao"/>
          <StatCard label="PROPOSALS SENT" value={today.proposals_sent} color="#ff9500" sub="All time"/>
        </div>
      )}

      {/* Active platforms */}
      {today?.active_platforms?.length > 0 && (
        <div style={{ border:'1px solid rgba(0,212,255,0.1)', borderRadius:'4px', padding:'14px 18px', background:'rgba(0,10,20,0.7)', marginBottom:'12px' }}>
          <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'10px' }}>ACTIVE PLATFORMS</div>
          <div style={{ display:'flex', gap:'6px', flexWrap:'wrap' }}>
            {today.active_platforms.map(p => <Badge key={p} label={p} color="#00ff88"/>)}
          </div>
        </div>
      )}

      {/* Auto mode status */}
      {auto && (
        <div style={{ border:`1px solid ${auto.running?'rgba(0,255,136,0.3)':'rgba(0,212,255,0.1)'}`, borderRadius:'4px', padding:'14px 18px', background:'rgba(0,10,20,0.7)', marginBottom:'12px' }}>
          <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'8px', display:'flex', justifyContent:'space-between' }}>
            <span>AUTO MODE</span>
            <span style={{ color: auto.running?'#00ff88':'rgba(255,255,255,0.3)' }}>{auto.running?'● RUNNING':'○ IDLE'}</span>
          </div>
          <div style={{ fontSize:'10px', color:'rgba(255,255,255,0.4)', marginBottom:'6px' }}>{auto.stage}</div>
          <div style={{ height:'3px', background:'rgba(255,255,255,0.05)', borderRadius:'2px' }}>
            <div style={{ height:'100%', width:`${auto.progress}%`, background:'linear-gradient(90deg,#00d4ff,#00ff88)', borderRadius:'2px', transition:'width 0.5s' }}/>
          </div>
          {auto.log?.length > 0 && (
            <div style={{ marginTop:'8px', fontSize:'9px', color:'rgba(0,212,255,0.4)', fontFamily:'monospace' }}>
              {auto.log.slice(-3).map((l,i) => <div key={i}>{l}</div>)}
            </div>
          )}
        </div>
      )}

      {/* Service status */}
      <div style={{ border:'1px solid rgba(0,212,255,0.1)', borderRadius:'4px', padding:'14px 18px', background:'rgba(0,10,20,0.7)', marginBottom:'12px' }}>
        <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'10px' }}>SERVICES</div>
        <SvcRow label="FastAPI Backend :8000" ok={online}/>
        <SvcRow label="Ollama / DeepSeek-R1"  ok={online}/>
        <SvcRow label="Job Scanner"           ok={online}/>
        <SvcRow label="Automation Engine"     ok={online}/>
      </div>

      {/* Startup */}
      <div style={{ border:'1px solid rgba(255,255,255,0.05)', borderRadius:'4px', padding:'14px 18px', background:'rgba(0,8,16,0.6)', fontSize:'10px', color:'rgba(255,255,255,0.25)', lineHeight:'2', letterSpacing:'0.08em' }}>
        <div style={{ color:'rgba(0,212,255,0.4)', marginBottom:'6px', letterSpacing:'0.2em', fontSize:'9px' }}>STARTUP</div>
        <div>1. <span style={{color:'#00ff88'}}>ollama serve</span></div>
        <div>2. <span style={{color:'#00ff88'}}>cd backend && uvicorn main:app --reload --port 8000</span></div>
        <div>3. <span style={{color:'#00ff88'}}>cd frontend && npm run dev</span></div>
        <div>4. <span style={{color:'#00ff88'}}>http://localhost:5173</span></div>
      </div>
    </div>
  )
}
