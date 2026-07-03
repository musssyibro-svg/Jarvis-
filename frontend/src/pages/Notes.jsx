import { useState, useEffect } from 'react'
import { PageHeader, Btn } from '../components/UI'

import { API } from '../config.js'

export default function Notes() {
  const [notes, setNotes] = useState([])
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [expanded, setExpanded] = useState(null)

  useEffect(() => { load() }, [])

  const load = async () => {
    try {
      const r = await fetch(`${API}/notes`)
      if (r.ok) setNotes((await r.json()).notes || [])
    } catch {}
  }

  const add = async () => {
    if (!title.trim()) return
    await fetch(`${API}/notes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, body }) })
    setTitle(''); setBody(''); load()
  }

  const del = async (id) => { await fetch(`${API}/notes/${id}`, { method: 'DELETE' }); load() }

  return (
    <div style={{ padding: '28px', overflowY: 'auto', height: '100%' }}>
      <PageHeader breadcrumb="NOTES" title="✎ NOTES" />

      <div style={{ border: '1px solid rgba(0,212,255,0.15)', borderRadius: '4px', padding: '16px', background: 'rgba(0,10,20,0.7)', marginBottom: '20px' }}>
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Note title…"
          style={{ width: '100%', background: 'transparent', border: '1px solid rgba(0,212,255,0.2)', outline: 'none', color: '#c8e8f0', padding: '8px 10px', fontSize: '12px', fontFamily: 'Courier New,monospace', borderRadius: '3px', marginBottom: '8px' }} />
        <textarea value={body} onChange={e => setBody(e.target.value)} placeholder="Content… (optional)" rows={3}
          style={{ width: '100%', background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', outline: 'none', color: 'rgba(255,255,255,0.6)', padding: '8px 10px', fontSize: '11px', fontFamily: 'Courier New,monospace', resize: 'vertical', borderRadius: '3px', marginBottom: '8px' }} />
        <Btn onClick={add} variant="primary">+ ADD NOTE</Btn>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: '10px' }}>
        {notes.map(n => (
          <div key={n.id} style={{ padding: '14px', borderRadius: '4px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)', cursor: 'pointer' }} onClick={() => setExpanded(expanded === n.id ? null : n.id)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ fontSize: '12px', fontWeight: '600', color: '#c4e4ef', flex: 1 }}>{n.title}</div>
              <Btn onClick={e => { e.stopPropagation(); del(n.id) }} variant="danger" small>✕</Btn>
            </div>
            <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.2)', marginTop: '4px', letterSpacing: '0.1em' }}>{n.created_at?.slice(0, 10)}</div>
            {expanded === n.id && n.body && (
              <div style={{ marginTop: '10px', fontSize: '11px', color: 'rgba(255,255,255,0.5)', lineHeight: 1.7, whiteSpace: 'pre-wrap', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '10px' }}>
                {n.body}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
