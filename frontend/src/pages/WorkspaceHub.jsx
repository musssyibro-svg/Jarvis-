import { useState } from 'react'
import Workspace from './Workspace'
import Jobs      from './Jobs'
import Proposals from './Proposals'
import Messages  from './Messages'
import Analytics from './Analytics'
import Tasks     from './Tasks'
import Notes     from './Notes'
import AutoMode  from './AutoMode'
import Agents    from './Agents'

// V8.5: groups every freelance/job tool under the Workspace tab as subtabs.
// Existing page components are reused unchanged.
const SUBTABS = [
  { id: 'overview',  label: 'Overview',  Comp: Workspace },
  { id: 'jobs',      label: 'Jobs',      Comp: Jobs },
  { id: 'proposals', label: 'Proposals', Comp: Proposals },
  { id: 'messages',  label: 'Messages',  Comp: Messages },
  { id: 'automode',  label: 'Auto Mode', Comp: AutoMode },
  { id: 'agents',    label: 'Agents',    Comp: Agents },
  { id: 'analytics', label: 'Analytics', Comp: Analytics },
  { id: 'tasks',     label: 'Tasks',     Comp: Tasks },
  { id: 'notes',     label: 'Notes',     Comp: Notes },
]

export default function WorkspaceHub() {
  const [sub, setSub] = useState('overview')
  const Active = (SUBTABS.find(s => s.id === sub) || SUBTABS[0]).Comp

  return (
    <div style={{ height:'100%', display:'flex', flexDirection:'column' }}>
      <div style={{ display:'flex', gap:'2px', padding:'10px 16px', flexWrap:'wrap',
        borderBottom:'1px solid rgba(0,212,255,0.1)', background:'rgba(4,10,16,0.6)' }}>
        {SUBTABS.map(s => (
          <button key={s.id} onClick={() => setSub(s.id)} style={{
            padding:'6px 14px', border:'none', borderRadius:'3px', cursor:'pointer',
            fontFamily:'monospace', fontSize:'10px', letterSpacing:'0.1em',
            background: sub===s.id ? 'rgba(0,212,255,0.12)' : 'transparent',
            color: sub===s.id ? '#00d4ff' : 'rgba(255,255,255,0.4)',
          }}>{s.label}</button>
        ))}
      </div>
      <div style={{ flex:1, overflow:'auto' }}><Active /></div>
    </div>
  )
}
