import { useState } from 'react'
import Dashboard   from './pages/Dashboard'
import Settings    from './pages/Settings'
import Chat        from './pages/Chat'
import WorkspaceHub from './pages/WorkspaceHub'
import Agents       from './pages/Agents'
import JarvisCore   from './JarvisCore'

// Jarvis is a personal assistant first. Core (assistant hub) is the default.
// COMPUTER is PC control (desktop/vision/commander agents) — a core Jarvis
// capability, NOT a freelance feature. Freelance is one module among others.
const TABS = [
  { id: 'jarvis',    label: 'Core',       Comp: JarvisCore },
  { id: 'chat',      label: 'Chat',       Comp: Chat },
  { id: 'computer',  label: 'Computer',   Comp: Agents },
  { id: 'workspace', label: 'Freelance',  Comp: WorkspaceHub },
  { id: 'dashboard', label: 'Dashboard',  Comp: Dashboard },
  { id: 'settings',  label: 'Settings',   Comp: Settings },
]

export default function App() {
  const [tab, setTab] = useState('jarvis')   // Chat is the default entry point
  const Active = (TABS.find(t => t.id === tab) || TABS[0]).Comp

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100vh', overflow:'hidden' }}>
      {/* Animated accent hairline across the very top */}
      <div className="accent-strip" />
      {/* Top tab bar */}
      <nav style={{ display:'flex', gap:'2px', padding:'8px 12px', alignItems:'center',
        borderBottom:'1px solid rgba(0,212,255,0.15)',
        background:'linear-gradient(90deg, rgba(4,10,16,0.98), rgba(8,14,26,0.95), rgba(4,10,16,0.98))',
        backdropFilter:'blur(6px)', zIndex:2 }}>
        <div style={{ display:'flex', alignItems:'center', gap:'8px', marginRight:'24px' }}>
          <div style={{ width:9, height:9, borderRadius:'50%',
            background:'radial-gradient(circle, #7df9ff, #00d4ff)',
            boxShadow:'0 0 10px #00d4ff, 0 0 22px rgba(0,212,255,0.5)',
            animation:'pulseglow 2.5s ease-in-out infinite' }}/>
          <span className="hud-glow" style={{ color:'#00d4ff', fontFamily:'monospace', fontSize:'14px', letterSpacing:'0.2em', fontWeight:700 }}>JARVIS</span>
          <span style={{ color:'rgba(167,139,250,0.7)', fontFamily:'monospace', fontSize:'9px', letterSpacing:'0.25em', marginTop:2 }}>OS · V12</span>
        </div>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding:'8px 20px', border:'none', borderRadius:'6px 6px 0 0', cursor:'pointer',
            fontFamily:'monospace', fontSize:'11px', letterSpacing:'0.12em',
            background: tab===t.id
              ? 'linear-gradient(180deg, rgba(0,212,255,0.18), rgba(0,212,255,0.04))'
              : 'transparent',
            color: tab===t.id ? '#7df1ff' : 'rgba(255,255,255,0.45)',
            borderBottom: tab===t.id ? '2px solid #00d4ff' : '2px solid transparent',
            textShadow: tab===t.id ? '0 0 12px rgba(0,212,255,0.6)' : 'none',
            transition:'all 0.15s',
          }}>{t.label.toUpperCase()}</button>
        ))}
      </nav>

      {/* Active page */}
      <main style={{ flex:1, overflow:'auto', position:'relative' }}>
        <div style={{ position:'fixed', inset:0, pointerEvents:'none', zIndex:0,
          backgroundImage:`linear-gradient(rgba(0,212,255,0.025) 1px,transparent 1px),linear-gradient(90deg,rgba(0,212,255,0.025) 1px,transparent 1px)`,
          backgroundSize:'40px 40px' }}/>
        <div style={{ position:'relative', zIndex:1, height:'100%' }}><Active /></div>
      </main>
    </div>
  )
}
