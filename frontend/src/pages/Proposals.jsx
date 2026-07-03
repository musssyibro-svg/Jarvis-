import { useState, useEffect } from 'react'
import { Badge, Ring, Btn, PageHeader, Modal } from '../components/UI'

import { API } from '../config.js'

const STATUS_COLORS = {
  draft: '#888',
  sent: '#00d4ff',
  verifying: '#ff9500',
  accepted: '#00ff88',
  working: '#ff9500',
  done: '#00ff88',
  submitted: '#00ff88',
  rejected: '#ff4444',
  manual_required: '#ff9500',
  not_awarded_yet: '#888',
  not_logged_in: '#ff4444',
}

const ALL_STATUSES = ['draft','sent','verifying','accepted','working','done','submitted','rejected','manual_required','not_awarded_yet','not_logged_in']

export default function Proposals() {
  const [proposals, setProposals] = useState([])
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState(null)
  const [working, setWorking] = useState(null)
  const [workResult, setWorkResult] = useState(null)
  const [showWork, setShowWork] = useState(false)

  useEffect(() => { load() }, [])

  const load = async () => {
    try {
      const r = await fetch(`${API}/proposals/`)
      if (r.ok) {
        const d = await r.json()
        setProposals(d.proposals || [])
      }
    } catch {}
  }

  const updateStatus = async (pid, status, extra = {}) => {
    try {
      await fetch(`${API}/proposals/${pid}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, ...extra }),
      })
      load()
    } catch {}
  }

  const autoWork = async (pid) => {
    setWorking(pid)
    try {
      const r = await fetch(`${API}/proposals/${pid}/work`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setWorkResult(d)
        setShowWork(true)
        load()
      }
    } catch {}
    setWorking(null)
  }

  const deleteProposal = async (pid) => {
    await fetch(`${API}/proposals/${pid}`, { method: 'DELETE' })
    setSelected(null)
    load()
  }

  const filtered = filter === 'all' ? proposals : proposals.filter(p => p.status === filter)

  return (
    <div style={{ padding: '28px', overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px', flexWrap: 'wrap', gap: '10px' }}>
        <PageHeader breadcrumb="PROPOSALS" title="◈ PROPOSAL TRACKER" />
        <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
          {['all', 'draft', 'sent', 'accepted', 'done', 'rejected'].map(s => (
            <Btn key={s} onClick={() => setFilter(s)} variant={filter === s ? 'primary' : 'ghost'} small>
              {s.toUpperCase()}
            </Btn>
          ))}
        </div>
      </div>

      {filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px', color: 'rgba(255,255,255,0.18)', fontSize: '11px', lineHeight: 2 }}>
          NO PROPOSALS YET<br />
          <span style={{ fontSize: '9px' }}>Go to Job Scanner → select a job → Generate Proposal</span>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {filtered.map(p => {
          const col = STATUS_COLORS[p.status] || '#888'
          const isSelected = selected?.id === p.id
          return (
            <div key={p.id} style={{
              padding: '14px 16px', borderRadius: '4px', cursor: 'pointer',
              background: isSelected ? 'rgba(0,212,255,0.06)' : 'rgba(255,255,255,0.02)',
              border: `1px solid ${isSelected ? '#00d4ff' : 'rgba(255,255,255,0.07)'}`,
              transition: 'all 0.15s',
            }} onClick={() => setSelected(isSelected ? null : p)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', gap: '6px', marginBottom: '5px', flexWrap: 'wrap', alignItems: 'center' }}>
                    <Badge label={p.status} color={col} />
                    <Badge label={p.platform} color="#00d4ff" />
                    {p.budget && <Badge label={p.budget} color="#00ff88" />}
                    {p.confidence > 0 && <Badge label={`${p.confidence}% conf`} color="#ff9500" />}
                    {p.can_auto_work ? <Badge label="AUTO-WORKABLE" color="#ff9500" /> : null}
                  </div>
                  <div style={{ fontSize: '13px', fontWeight: '600', color: '#c4e4ef', marginBottom: '3px' }}>
                    {p.job_title}
                  </div>
                  <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.25)', letterSpacing: '0.1em' }}>
                    {p.created_at?.slice(0, 10)} · {p.work_type || 'unknown type'}
                    {p.got_reply ? ' · ✓ REPLIED' : ''}
                    {p.won ? ' · 🏆 WON' : ''}
                  </div>
                </div>
                <Ring score={p.confidence || 0} size={36} />
              </div>

              {isSelected && (
                <div style={{ marginTop: '14px' }}>
                  {p.proposal_text && (
                    <div style={{ marginBottom: '12px' }}>
                      <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.5)', letterSpacing: '0.15em', marginBottom: '6px' }}>PROPOSAL TEXT</div>
                      <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.55)', lineHeight: 1.75, whiteSpace: 'pre-wrap', background: 'rgba(0,10,20,0.6)', padding: '10px', borderRadius: '3px', border: '1px solid rgba(0,212,255,0.1)' }}>
                        {p.proposal_text}
                      </div>
                    </div>
                  )}

                  {p.work_output && (
                    <div style={{ marginBottom: '12px' }}>
                      <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.5)', letterSpacing: '0.15em', marginBottom: '6px' }}>WORK OUTPUT</div>
                      <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.55)', lineHeight: 1.75, whiteSpace: 'pre-wrap', background: 'rgba(0,10,20,0.6)', padding: '10px', borderRadius: '3px', border: '1px solid rgba(0,255,136,0.1)', maxHeight: '160px', overflowY: 'auto' }}>
                        {p.work_output}
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {p.status === 'draft' && (
                      <Btn onClick={() => updateStatus(p.id, 'sent')} variant="primary" small>MARK SENT</Btn>
                    )}
                    {p.status === 'sent' && (
                      <>
                        <Btn onClick={() => updateStatus(p.id, 'accepted', { got_reply: true })} variant="success" small>✓ ACCEPTED</Btn>
                        <Btn onClick={() => updateStatus(p.id, 'rejected', { got_reply: true })} variant="danger" small>✗ REJECTED</Btn>
                        <Btn onClick={() => updateStatus(p.id, 'not_awarded_yet', { got_reply: true })} variant="ghost" small>NOT AWARDED YET</Btn>
                      </>
                    )}
                    {p.status === 'accepted' && (
                      <Btn onClick={() => autoWork(p.id)} disabled={working === p.id} variant="success" small>
                        {working === p.id ? '⟳ WORKING…' : '▶ AUTO-WORK'}
                      </Btn>
                    )}
                    {(p.status === 'done' || p.status === 'manual_required') && (
                      <Btn onClick={() => fetch(`${API}/proposals/${p.id}/submit`, { method: 'POST' }).then(load)} variant="success" small>✓ MARK SUBMITTED</Btn>
                    )}
                    {p.status === 'submitted' && (
                      <>
                        <Btn onClick={() => updateStatus(p.id, 'submitted', { won: true })} variant="success" small>🏆 WON</Btn>
                      </>
                    )}
                    {p.proposal_text && (
                      <Btn onClick={() => navigator.clipboard?.writeText(p.proposal_text)} variant="ghost" small>COPY TEXT</Btn>
                    )}
                    {p.job_link && (
                      <Btn onClick={() => window.open(p.job_link, '_blank')} variant="ghost" small>OPEN JOB ↗</Btn>
                    )}
                    <Btn onClick={() => deleteProposal(p.id)} variant="danger" small>DELETE</Btn>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {showWork && workResult && (
        <Modal title="AUTO-WORK RESULT" onClose={() => setShowWork(false)}>
          <div style={{ marginBottom: '10px' }}>
            <Badge label={workResult.workable ? 'COMPLETED BY AI' : 'MANUAL REQUIRED'} color={workResult.workable ? '#00ff88' : '#ff9500'} />
          </div>
          <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', marginBottom: '12px' }}>{workResult.message}</p>
          {workResult.proposal?.work_output && (
            <textarea readOnly value={workResult.proposal.work_output} style={{
              width: '100%', minHeight: '200px', background: 'rgba(0,10,20,0.8)',
              border: '1px solid rgba(0,212,255,0.2)', outline: 'none', color: '#c8e8f0',
              padding: '12px', fontSize: '12px', lineHeight: 1.75, resize: 'vertical',
              borderRadius: '3px', fontFamily: 'sans-serif',
            }} />
          )}
          <div style={{ marginTop: '12px', display: 'flex', gap: '8px' }}>
            {workResult.proposal?.work_output && (
              <Btn onClick={() => { navigator.clipboard?.writeText(workResult.proposal.work_output); setShowWork(false) }} variant="success">COPY WORK</Btn>
            )}
            <Btn onClick={() => setShowWork(false)} variant="ghost">CLOSE</Btn>
          </div>
        </Modal>
      )}
    </div>
  )
}
