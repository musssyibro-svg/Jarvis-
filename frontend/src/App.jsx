import { useState } from 'react'
import Dashboard   from './pages/Dashboard'
import Settings    from './pages/Settings'
import Chat        from './pages/Chat'
import WorkspaceHub from './pages/WorkspaceHub'
import JarvisCore   from './JarvisCore'

// V8.5: four top-level tabs only. Chat is default. All freelance/job tools
// live as subtabs inside Workspace (WorkspaceHub).
const TABS = [
  { id: 'jarvis',    label: 'Core',      Comp: JarvisCore },
  { id: 'chat',      label: 'Chat',      Comp: Chat },
  { id: 'workspace', label: 'Workspace', Comp: WorkspaceHub },
  { id: 'dashboard', label: 'Dashboard', Comp: Dashboard },
  { id: 'settings',  label: 'Settings',  Comp: Settings },
]

export default function App() {
  const [tab, setTab] = useState('jarvis')   // Chat is the default entry point
  const Active = (TABS.find(t => t.id === tab) || TABS[0]).Comp

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100vh', background:'#040a10', overflow:'hidden' }}>
      {/* Top tab bar */}
      <nav style={{ display:'flex', gap:'2px', padding:'8px 12px', borderBottom:'1px solid rgba(0,212,255,0.15)', background:'rgba(4,10,16,0.95)', zIndex:2 }}>
        <div style={{ display:'flex', alignItems:'center', gap:'8px', marginRight:'24px' }}>
          <div style={{ width:8, height:8, borderRadius:'50%', background:'#00d4ff', boxShadow:'0 0 8px #00d4ff' }}/>
          <span style={{ color:'#00d4ff', fontFamily:'monospace', fontSize:'13px', letterSpacing:'0.15em', fontWeight:600 }}>JARVIS OS</span>
        </div>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding:'8px 20px', border:'none', borderRadius:'4px', cursor:'pointer',
            fontFamily:'monospace', fontSize:'11px', letterSpacing:'0.12em',
            background: tab===t.id ? 'rgba(0,212,255,0.15)' : 'transparent',
            color: tab===t.id ? '#00d4ff' : 'rgba(255,255,255,0.45)',
            borderBottom: tab===t.id ? '2px solid #00d4ff' : '2px solid transparent',
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
