import { useState, useEffect } from 'react'
import { PageHeader, Btn } from '../components/UI'

import { API } from '../config.js'

export default function Tasks() {
  const [tasks, setTasks] = useState([])
  const [title, setTitle] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => { load() }, [])

  const load = async () => {
    try {
      const r = await fetch(`${API}/tasks`)
      if (r.ok) setTasks((await r.json()).tasks || [])
    } catch {}
  }

  const add = async () => {
    if (!title.trim()) return
    await fetch(`${API}/tasks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, note }) })
    setTitle(''); setNote(''); load()
  }

  const complete = async (id) => { await fetch(`${API}/tasks/${id}/done`, { method: 'PUT' }); load() }
  const del = async (id) => { await fetch(`${API}/tasks/${id}`, { method: 'DELETE' }); load() }

  const pending = tasks.filter(t => !t.done)
  const done    = tasks.filter(t => t.done)

  return (
    <div style={{ padding: '28px', overflowY: 'auto', height: '100%' }}>
      <PageHeader breadcrumb="TASKS" title="☑ TASK LIST" />

      <div style={{ border: '1px solid rgba(0,212,255,0.15)', borderRadius: '4px', padding: '16px', background: 'rgba(0,10,20,0.7)', marginBottom: '20px' }}>
        <input value={title} onChange={e => setTitle(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="Task title…"
          style={{ width: '100%', background: 'transparent', border: '1px solid rgba(0,212,255,0.2)', outline: 'none', color: '#c8e8f0', padding: '8px 10px', fontSize: '12px', fontFamily: 'Courier New,monospace', borderRadius: '3px', marginBottom: '8px' }} />
        <div style={{ display: 'flex', gap: '8px' }}>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Note (optional)…"
            style={{ flex: 1, background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', outline: 'none', color: 'rgba(255,255,255,0.5)', padding: '7px 10px', fontSize: '11px', fontFamily: 'Courier New,monospace', borderRadius: '3px' }} />
          <Btn onClick={add} variant="primary">+ ADD</Btn>
        </div>
      </div>

      {pending.length === 0 && <div style={{ color: 'rgba(255,255,255,0.2)', fontSize: '11px', marginBottom: '16px' }}>No pending tasks.</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '20px' }}>
        {pending.map(t => (
          <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '11px 14px', borderRadius: '3px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <button onClick={() => complete(t.id)} style={{ width: '16px', height: '16px', borderRadius: '3px', border: '1px solid rgba(0,212,255,0.4)', background: 'transparent', cursor: 'pointer', flexShrink: 0 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '12px', color: '#c4e4ef' }}>{t.title}</div>
              {t.note && <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.3)', marginTop: '2px' }}>{t.note}</div>}
            </div>
            <Btn onClick={() => del(t.id)} variant="danger" small>✕</Btn>
          </div>
        ))}
      </div>

      {done.length > 0 && (
        <>
          <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.2)', letterSpacing: '0.2em', marginBottom: '8px' }}>COMPLETED</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {done.map(t => (
              <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 14px', borderRadius: '3px', background: 'rgba(0,255,136,0.03)', border: '1px solid rgba(0,255,136,0.07)', opacity: 0.6 }}>
                <span style={{ color: '#00ff88', fontSize: '12px' }}>✓</span>
                <span style={{ flex: 1, fontSize: '11px', color: 'rgba(255,255,255,0.3)', textDecoration: 'line-through' }}>{t.title}</span>
                <Btn onClick={() => del(t.id)} variant="danger" small>✕</Btn>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
