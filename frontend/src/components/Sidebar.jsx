import { useEffect, useState } from 'react'
import { API } from '../config.js'

const NAV = [
  { id:'dashboard',   icon:'⬡', label:'DASHBOARD',   group:'main' },
  { id:'chat',        icon:'◉', label:'AI TERMINAL',  group:'main' },
  { id:'agents',      icon:'⬢', label:'AGENTS',       group:'main', highlight:true },
  { id:'automode',    icon:'⟳', label:'AUTONOMOUS',   group:'main', highlight:true },
  { id:'workspace',   icon:'▦', label:'WORKSPACE',    group:'work' },
  { id:'jobs',        icon:'◎', label:'JOB SCANNER',  group:'work' },
  { id:'proposals',   icon:'◈', label:'PROPOSALS',    group:'work' },
  { id:'messages',    icon:'✉', label:'MESSAGES',     group:'work' },
  { id:'analytics',   icon:'▲', label:'ANALYTICS',    group:'data' },
  { id:'tasks',       icon:'☑', label:'TASKS',        group:'data' },
  { id:'notes',       icon:'✎', label:'NOTES',        group:'data' },
  { id:'settings',    icon:'⚙', label:'SETTINGS',     group:'data' },
]

export default function Sidebar({ tab, setTab }) {
  const [clock,   setClock]    = useState(new Date())
  const [online,  setOnline]   = useState(null)
  const [running, setRunning]  = useState(false)
  const [pending, setPending]  = useState(0)

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const ping = async () => {
      try { const r = await fetch(`${API}/health`); setOnline(r.ok) } catch { setOnline(false) }
      try {
        const r = await fetch(`${API}/orchestrator/status`)
        if(r.ok) { const d = await r.json(); setRunning(d.running) }
      } catch{}
      try {
        const r = await fetch(`${API}/automation/queue?limit=100`)
        if(r.ok) { const d = await r.json(); setPending((d.queue||[]).filter(q=>q.status==='pending').length) }
      } catch{}
    }
    ping(); const t = setInterval(ping, 6000); return () => clearInterval(t)
  }, [])

  const dotColor = online===null?'#ff9500':online?'#00ff88':'#ff4444'

  return (
    <aside style={{ width:'210px', flexShrink:0, display:'flex', flexDirection:'column', borderRight:'1px solid rgba(0,212,255,0.15)', background:'rgba(0,4,10,0.97)' }}>
      <div style={{ padding:'20px 20px 16px', borderBottom:'1px solid rgba(0,212,255,0.1)' }}>
        <div style={{ fontSize:'8px', color:'rgba(0,212,255,0.4)', letterSpacing:'0.35em', marginBottom:'5px' }}>STARK INDUSTRIES</div>
        <div className="hud-glow" style={{ fontSize:'26px', fontWeight:'700', color:'#00d4ff', letterSpacing:'0.12em', fontFamily:'sans-serif' }}>JARVIS</div>
        <div style={{ fontSize:'8px', color:'rgba(255,255,255,0.2)', letterSpacing:'0.2em' }}>v3 // AUTONOMOUS AI</div>
      </div>

      <div style={{ padding:'10px 20px', borderBottom:'1px solid rgba(0,212,255,0.07)', fontSize:'9px' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'6px', marginBottom:'3px' }}>
          <span style={{ width:'5px', height:'5px', borderRadius:'50%', background:dotColor, boxShadow:`0 0 6px ${dotColor}`, flexShrink:0 }}/>
          <span style={{ color:dotColor, letterSpacing:'0.1em', fontSize:'8px' }}>
            {online===null?'CONNECTING':online?'BACKEND ONLINE':'OFFLINE'}
          </span>
        </div>
        {running && (
          <div style={{ display:'flex', alignItems:'center', gap:'5px', marginBottom:'3px' }}>
            <span style={{ width:'5px', height:'5px', borderRadius:'50%', background:'#00ff88', animation:'pulseglow 1s ease-in-out infinite' }}/>
            <span style={{ color:'#00ff88', fontSize:'8px', letterSpacing:'0.1em' }}>PIPELINE RUNNING</span>
          </div>
        )}
        {pending > 0 && (
          <div style={{ color:'#ff9500', fontSize:'8px', letterSpacing:'0.1em' }}>● {pending} AWAITING APPROVAL</div>
        )}
        <div style={{ color:'rgba(255,255,255,0.18)', marginTop:'2px' }}>{clock.toLocaleTimeString('en-GB')}</div>
      </div>

      <nav style={{ flex:1, padding:'8px', display:'flex', flexDirection:'column', gap:'2px', overflowY:'auto' }}>
        {NAV.map(n => {
          const active = tab===n.id
          const c = n.highlight ? '#00ff88' : '#00d4ff'
          return (
            <button key={n.id} onClick={()=>setTab(n.id)} style={{
              width:'100%', padding:'9px 12px', textAlign:'left', cursor:'pointer',
              fontSize:'10px', letterSpacing:'0.12em', fontFamily:'Courier New,monospace',
              transition:'all 0.15s',
              background: active?`${c}18`:'transparent',
              border: `1px solid ${active?c:'transparent'}`,
              color: active?c:n.highlight?'rgba(0,255,136,0.5)':'rgba(255,255,255,0.33)',
              borderRadius:'3px',
            }}>
              {n.icon} {active?'▶ ':''}{n.label}
              {n.id==='workspace' && running && <span style={{ float:'right', color:'#00ff88', fontSize:'8px' }}>●</span>}
              {n.id==='workspace' && pending>0 && !running && <span style={{ float:'right', color:'#ff9500', fontSize:'8px' }}>●{pending}</span>}
            </button>
          )
        })}
      </nav>

      <div style={{ padding:'10px 20px', fontSize:'8px', color:'rgba(255,255,255,0.1)', letterSpacing:'0.1em', borderTop:'1px solid rgba(0,212,255,0.07)' }}>
        DEEPSEEK-R1 · QWEN · OLLAMA
      </div>
    </aside>
  )
}
