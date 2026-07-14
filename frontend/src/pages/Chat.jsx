import { useState, useRef, useEffect } from 'react'
import { PageHeader, Btn } from '../components/UI'

import { API } from '../config.js'

const CHIPS = [
  'open notepad and type hello',
  "what's on my screen?",
  'remember for mistore: check supplier prices weekly',
  'plan project mistore to launch the store',
]

export default function Chat() {
  const [msgs, setMsgs] = useState([
    { role: 'jarvis', text: 'JARVIS ONLINE. Your PC, files, brain, plans and freelancing — what do you need?' }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  // V8: stable session id persisted in localStorage so history survives refresh
  const [sessionId] = useState(() => {
    try {
      let s = localStorage.getItem('jarvis_session_id')
      if (!s) { s = `s_${Date.now()}`; localStorage.setItem('jarvis_session_id', s) }
      return s
    } catch { return `s_${Date.now()}` }
  })
  const endRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  // V8: restore prior conversation from backend SQLite on mount
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/chat/history/${sessionId}`)
        if (!r.ok) return
        const d = await r.json()
        const hist = (d.messages || []).map(m => ({
          role: m.role === 'assistant' ? 'jarvis' : (m.role === 'user' ? 'user' : m.role),
          text: m.content,
        }))
        if (hist.length > 0) setMsgs(hist)
      } catch {}
    })()
  }, [sessionId])

  const send = async (text) => {
    if (!text?.trim() || loading) return
    setMsgs(p => [...p, { role: 'user', text }])
    setInput('')
    setLoading(true)
    try {
      const r = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      })
      const d = await r.json()
      setMsgs(p => [...p, { role: 'jarvis', text: d.response }])
    } catch {
      setMsgs(p => [...p, { role: 'jarvis', text: 'Connection error. Is the backend running on port 8000?' }])
    }
    setLoading(false)
  }

  const clearMem = async () => {
    try { await fetch(`${API}/memory/clear/${sessionId}`, { method: 'POST' }) } catch {}
    setMsgs([{ role: 'jarvis', text: 'Memory cleared.' }])
  }

  return (
    <div style={{ padding: '28px', height: '100%', display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <PageHeader breadcrumb="AI TERMINAL" title="◉ AI TERMINAL" />
        <Btn onClick={clearMem} variant="danger" small>CLEAR MEM</Btn>
      </div>

      {msgs.length <= 1 && (
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {CHIPS.map(s => (
            <button key={s} onClick={() => send(s)} style={{
              padding: '5px 10px', fontSize: '9px', cursor: 'pointer',
              background: 'rgba(0,212,255,0.06)', border: '1px solid rgba(0,212,255,0.2)',
              color: 'rgba(0,212,255,0.6)', borderRadius: '2px', letterSpacing: '0.1em',
              fontFamily: 'Courier New,monospace',
            }}>{s}</button>
          ))}
        </div>
      )}

      <div style={{ flex: 1, overflowY: 'auto', padding: '16px', background: 'rgba(0,5,10,0.8)', border: '1px solid rgba(0,212,255,0.1)', borderRadius: '4px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {msgs.map((m, i) => (
          <div key={i} style={{ display: 'flex', gap: '10px', flexDirection: m.role === 'user' ? 'row-reverse' : 'row', animation: 'fadeIn 0.2s ease' }}>
            <div style={{ width: '28px', height: '28px', borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: '700', background: m.role === 'jarvis' ? 'rgba(0,212,255,0.13)' : 'rgba(255,255,255,0.06)', border: `1px solid ${m.role === 'jarvis' ? 'rgba(0,212,255,0.4)' : 'rgba(255,255,255,0.15)'}`, color: m.role === 'jarvis' ? '#00d4ff' : 'rgba(255,255,255,0.45)' }}>
              {m.role === 'jarvis' ? 'J' : 'U'}
            </div>
            <div style={{ maxWidth: '76%', padding: '10px 14px', borderRadius: '4px', fontSize: '12px', lineHeight: '1.75', whiteSpace: 'pre-wrap', background: m.role === 'jarvis' ? 'rgba(0,212,255,0.05)' : 'rgba(255,255,255,0.04)', border: `1px solid ${m.role === 'jarvis' ? 'rgba(0,212,255,0.18)' : 'rgba(255,255,255,0.08)'}`, color: m.role === 'jarvis' ? '#c8e8f0' : 'rgba(255,255,255,0.65)' }}>
              <div style={{ fontSize: '8px', letterSpacing: '0.2em', marginBottom: '5px', color: m.role === 'jarvis' ? 'rgba(0,212,255,0.45)' : 'rgba(255,255,255,0.2)' }}>
                {m.role === 'jarvis' ? 'JARVIS' : 'YOU'}
              </div>
              {m.text}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', gap: '5px', paddingLeft: '38px', alignItems: 'center' }}>
            {[0, 1, 2].map(i => (
              <div key={i} style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#00d4ff', animation: `pulseglow 1s ease-in-out ${i * 0.18}s infinite` }} />
            ))}
            <span style={{ fontSize: '9px', color: 'rgba(0,212,255,0.4)', marginLeft: '6px', letterSpacing: '0.15em' }}>JARVIS THINKING...</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div style={{ display: 'flex', gap: '8px' }}>
        <textarea value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
          rows={2} placeholder="Type a message… (Enter to send, Shift+Enter new line)"
          style={{ flex: 1, background: 'rgba(0,10,20,0.8)', border: '1px solid rgba(0,212,255,0.18)', outline: 'none', color: '#c8e8f0', padding: '12px', fontSize: '12px', fontFamily: 'Courier New,monospace', resize: 'none', borderRadius: '3px' }} />
        <button onClick={() => send(input)} disabled={loading} style={{ width: '80px', background: loading ? 'rgba(0,212,255,0.04)' : 'rgba(0,212,255,0.12)', border: '1px solid rgba(0,212,255,0.35)', color: '#00d4ff', cursor: loading ? 'not-allowed' : 'pointer', fontSize: '10px', letterSpacing: '0.15em', borderRadius: '3px' }}>
          {loading ? '...' : 'SEND'}
        </button>
      </div>
    </div>
  )
}
