import { useState, useEffect } from 'react'
import { Badge, Btn, PageHeader, Modal } from '../components/UI'

import { API } from '../config.js'

export default function Messages() {
  const [messages, setMessages] = useState([])
  const [syncing, setSyncing] = useState(false)
  const [selected, setSelected] = useState(null)
  const [regenerating, setRegenerating] = useState(null)
  const [unreadOnly, setUnreadOnly] = useState(false)

  useEffect(() => { load() }, [unreadOnly])

  const load = async () => {
    try {
      const r = await fetch(`${API}/messages/?unread_only=${unreadOnly}&limit=50`)
      if (r.ok) {
        const d = await r.json()
        setMessages(d.messages || [])
      }
    } catch {}
  }

  const syncInbox = async () => {
    setSyncing(true)
    try {
      await fetch(`${API}/messages/sync`, { method: 'POST' })
      setTimeout(() => { load(); setSyncing(false) }, 4000)
    } catch { setSyncing(false) }
  }

  const markRead = async (mid) => {
    await fetch(`${API}/messages/${mid}/mark-read`, { method: 'POST' })
    load()
  }

  const regenerateReply = async (mid) => {
    setRegenerating(mid)
    try {
      const r = await fetch(`${API}/messages/${mid}/regenerate-reply`, { method: 'POST' })
      if (r.ok) load()
    } catch {}
    setRegenerating(null)
  }

  const deleteMsg = async (mid) => {
    await fetch(`${API}/messages/${mid}`, { method: 'DELETE' })
    setSelected(null)
    load()
  }

  const unread = messages.filter(m => !m.is_read).length

  return (
    <div style={{ padding: '28px', overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px', flexWrap: 'wrap', gap: '10px' }}>
        <PageHeader breadcrumb="MESSAGES" title="✉ INBOX MONITOR" />
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          {unread > 0 && <Badge label={`${unread} UNREAD`} color="#ff9500" />}
          <Btn onClick={() => setUnreadOnly(!unreadOnly)} variant={unreadOnly ? 'primary' : 'ghost'} small>
            {unreadOnly ? 'SHOW ALL' : 'UNREAD ONLY'}
          </Btn>
          <Btn onClick={syncInbox} disabled={syncing}>
            {syncing ? '⟳ SYNCING…' : '⟳ SYNC INBOX'}
          </Btn>
        </div>
      </div>

      {messages.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px', color: 'rgba(255,255,255,0.18)', fontSize: '11px', lineHeight: 2 }}>
          NO MESSAGES<br />
          <span style={{ fontSize: '9px' }}>Click SYNC INBOX to fetch messages from Freelancer (requires login in browser-profile)</span>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {messages.map(m => {
          const isSelected = selected?.id === m.id
          return (
            <div key={m.id} style={{
              padding: '14px 16px', borderRadius: '4px', cursor: 'pointer',
              background: isSelected ? 'rgba(0,212,255,0.06)' : m.is_read ? 'rgba(255,255,255,0.02)' : 'rgba(0,212,255,0.04)',
              border: `1px solid ${isSelected ? '#00d4ff' : m.is_read ? 'rgba(255,255,255,0.07)' : 'rgba(0,212,255,0.2)'}`,
              transition: 'all 0.15s',
            }} onClick={() => setSelected(isSelected ? null : m)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', gap: '6px', marginBottom: '5px', alignItems: 'center' }}>
                    {!m.is_read && <Badge label="UNREAD" color="#ff9500" />}
                    <span style={{ fontSize: '11px', fontWeight: '600', color: '#c4e4ef' }}>{m.sender}</span>
                    <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.25)', letterSpacing: '0.1em' }}>
                      {m.received_at?.slice(0, 16)}
                    </span>
                  </div>
                  <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.45)', lineHeight: 1.5, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: isSelected ? 999 : 2, WebkitBoxOrient: 'vertical' }}>
                    {m.message_preview}
                  </div>
                </div>
              </div>

              {isSelected && (
                <div style={{ marginTop: '14px' }}>
                  {m.reply_draft && (
                    <div style={{ marginBottom: '12px' }}>
                      <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.5)', letterSpacing: '0.15em', marginBottom: '6px' }}>AI REPLY DRAFT</div>
                      <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)', lineHeight: 1.75, whiteSpace: 'pre-wrap', background: 'rgba(0,10,20,0.6)', padding: '10px', borderRadius: '3px', border: '1px solid rgba(0,212,255,0.15)' }}>
                        {m.reply_draft}
                      </div>
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {m.reply_draft && (
                      <Btn onClick={() => navigator.clipboard?.writeText(m.reply_draft)} variant="success" small>COPY REPLY</Btn>
                    )}
                    {m.thread_url && (
                      <Btn onClick={() => window.open(m.thread_url, '_blank')} variant="primary" small>OPEN THREAD ↗</Btn>
                    )}
                    {!m.is_read && (
                      <Btn onClick={() => markRead(m.id)} variant="ghost" small>MARK READ</Btn>
                    )}
                    <Btn onClick={() => regenerateReply(m.id)} disabled={regenerating === m.id} variant="ghost" small>
                      {regenerating === m.id ? '⟳ REGENERATING…' : '↺ REGEN REPLY'}
                    </Btn>
                    <Btn onClick={() => deleteMsg(m.id)} variant="danger" small>DELETE</Btn>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
