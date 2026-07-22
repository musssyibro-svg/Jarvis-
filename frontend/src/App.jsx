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
    <div style={{ display:'flex', flexDirection:'column', height:'100vh', overflow:'hidden', background:'#0a0e14' }}>
      {/* Top tab bar — plain, no animation */}
      <nav style={{ display:'flex', gap:'2px', padding:'0 12px', alignItems:'center', height:'46px', flexShrink:0,
        borderBottom:'1px solid rgba(255,255,255,0.07)', background:'#0d1219', zIndex:2 }}>
        <div style={{ display:'flex', alignItems:'center', gap:'8px', marginRight:'24px' }}>
          <div style={{ width:7, height:7, borderRadius:'50%', background:'#00d4ff' }}/>
          <span style={{ color:'#e8f4fa', fontSize:'14px', letterSpacing:'0.18em', fontWeight:700 }}>JARVIS</span>
        </div>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding:'6px 18px', border:'none', borderRadius:'6px', fontSize:'12px', letterSpacing:'0.04em',
            background: tab===t.id ? 'rgba(0,212,255,0.12)' : 'transparent',
            color: tab===t.id ? '#7df1ff' : 'rgba(255,255,255,0.5)',
            fontWeight: tab===t.id ? 600 : 400,
          }}>{t.label}</button>
        ))}
      </nav>

      {/* Active page — flex child that owns its own scrolling; never clips. */}
      <main style={{ flex:1, minHeight:0, overflow:'hidden', position:'relative' }}>
        <div style={{ height:'100%', overflow:'auto' }}><Active /></div>
      </main>
    </div>
  )
}
