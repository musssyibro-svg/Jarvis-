import { useState, useEffect } from 'react'
import { StatCard, Badge, PageHeader } from '../components/UI'

import { API } from '../config.js'

const Bar = ({ label, value, color='#00d4ff' }) => (
  <div style={{ marginBottom:'14px' }}>
    <div style={{ display:'flex', justifyContent:'space-between', marginBottom:'4px', fontSize:'10px', letterSpacing:'0.12em' }}>
      <span style={{ color:'rgba(255,255,255,0.4)' }}>{label}</span>
      <span style={{ color, fontWeight:'700' }}>{value}%</span>
    </div>
    <div style={{ height:'4px', background:'rgba(255,255,255,0.05)', borderRadius:'2px', overflow:'hidden' }}>
      <div style={{ height:'100%', width:`${Math.min(value,100)}%`, background:`linear-gradient(90deg,${color}77,${color})`, borderRadius:'2px', transition:'width 0.6s ease' }}/>
    </div>
  </div>
)

export default function Analytics() {
  const [data, setData] = useState(null)
  const [period, setPeriod] = useState('all_time')

  useEffect(() => {
    const load = async () => {
      try { const r = await fetch(`${API}/analytics/`); if(r.ok) setData(await r.json()) } catch{}
    }
    load(); const t = setInterval(load, 15000); return () => clearInterval(t)
  }, [])

  if(!data) return <div style={{ padding:'28px' }}><PageHeader breadcrumb="ANALYTICS" title="▲ ANALYTICS"/><div style={{ color:'rgba(255,255,255,0.2)', fontSize:'11px' }}>Loading…</div></div>

  const a = data[period] || data.all_time
  const recs = data.recommendations || []

  return (
    <div style={{ padding:'28px', overflowY:'auto', height:'100%' }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:'20px', flexWrap:'wrap', gap:'10px' }}>
        <PageHeader breadcrumb="ANALYTICS" title="▲ PERFORMANCE ANALYTICS" />
        <div style={{ display:'flex', gap:'6px' }}>
          {[['all_time','ALL TIME'],['last_30_days','30 DAYS'],['last_7_days','7 DAYS']].map(([k,l]) => (
            <button key={k} onClick={()=>setPeriod(k)} style={{ padding:'5px 10px', fontSize:'9px', cursor:'pointer', background:period===k?'rgba(0,212,255,0.13)':'transparent', border:`1px solid ${period===k?'#00d4ff':'rgba(255,255,255,0.1)'}`, color:period===k?'#00d4ff':'rgba(255,255,255,0.35)', borderRadius:'2px', letterSpacing:'0.13em', fontFamily:'monospace' }}>{l}</button>
          ))}
        </div>
      </div>

      {/* Freelance proposals */}
      <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'8px' }}>FREELANCE PROPOSALS</div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'10px', marginBottom:'14px' }}>
        <StatCard label="SENT"      value={a.proposals_sent}   color="#00d4ff"/>
        <StatCard label="REPLIES"   value={a.replies_received} color="#00ff88"/>
        <StatCard label="WON"       value={a.projects_won}     color="#ff9500"/>
        <StatCard label="WIN RATE"  value={`${a.win_rate}%`}   color="#ff9500"/>
      </div>

      {/* Hubstaff */}
      <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'8px' }}>HUBSTAFF APPLICATIONS</div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'10px', marginBottom:'14px' }}>
        <StatCard label="SENT"       value={a.hs_sent||0}      color="#00d4ff"/>
        <StatCard label="REPLIED"    value={a.hs_replied||0}   color="#00ff88"/>
        <StatCard label="HIRED"      value={a.hs_hired||0}     color="#ff9500"/>
        <StatCard label="TOTAL APPS" value={a.hs_applications||0} color="#888"/>
      </div>

      {/* Microtasks */}
      <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'8px' }}>MICROTASKS</div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:'10px', marginBottom:'14px' }}>
        <StatCard label="CW TASKS DONE" value={a.cw_tasks_done||0}    color="#00d4ff"/>
        <StatCard label="CW EARNED"     value={`$${a.cw_earned||0}`}  color="#00ff88"/>
        <StatCard label="ZD SUBMITTED"  value={a.zd_submissions||0}   color="#ff9500"/>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'12px', marginBottom:'14px' }}>
        <div style={{ border:'1px solid rgba(0,212,255,0.1)', borderRadius:'4px', padding:'16px 20px', background:'rgba(0,10,20,0.7)' }}>
          <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'14px' }}>OVERALL RATES</div>
          <Bar label="RESPONSE RATE"      value={a.response_rate||0}         color="#00d4ff"/>
          <Bar label="WIN RATE"           value={a.win_rate||0}              color="#00ff88"/>
          <Bar label="REPLY → WIN"        value={a.reply_to_win_rate||0}     color="#ff9500"/>
          <Bar label="OVERALL RESP. RATE" value={a.overall_response_rate||0} color="#00d4ff"/>
        </div>
        <div style={{ border:'1px solid rgba(0,212,255,0.1)', borderRadius:'4px', padding:'16px 20px', background:'rgba(0,10,20,0.7)' }}>
          <div style={{ fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'14px' }}>STATUS BREAKDOWN</div>
          <div style={{ display:'flex', gap:'5px', flexWrap:'wrap' }}>
            {Object.entries(a.status_breakdown||{}).map(([s,c]) => (
              <div key={s} style={{ fontSize:'10px', padding:'4px 8px', borderRadius:'3px', background:'rgba(0,212,255,0.07)', border:'1px solid rgba(0,212,255,0.12)', color:'#a8d8ea' }}>
                {s}: <strong style={{ color:'#00d4ff' }}>{c}</strong>
              </div>
            ))}
          </div>
          <div style={{ marginTop:'14px', fontSize:'9px', color:'rgba(0,212,255,0.5)', letterSpacing:'0.2em', marginBottom:'8px' }}>ALL APPLICATIONS</div>
          <div style={{ fontSize:'28px', fontWeight:'700', color:'#00d4ff', fontFamily:'sans-serif' }}>{a.all_applications||0}</div>
        </div>
      </div>

      <div style={{ border:'1px solid rgba(0,255,136,0.15)', borderRadius:'4px', padding:'16px 20px', background:'rgba(0,20,10,0.5)' }}>
        <div style={{ fontSize:'9px', color:'rgba(0,255,136,0.5)', letterSpacing:'0.2em', marginBottom:'12px' }}>◉ AI RECOMMENDATIONS</div>
        {recs.map((r,i) => (
          <div key={i} style={{ fontSize:'11px', color:'rgba(255,255,255,0.55)', lineHeight:1.7, padding:'6px 0', borderBottom: i<recs.length-1?'1px solid rgba(255,255,255,0.04)':'none' }}>→ {r}</div>
        ))}
      </div>
    </div>
  )
}
