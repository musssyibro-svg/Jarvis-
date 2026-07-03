import { useState, useEffect } from 'react'
import { Badge, Ring, Btn, PageHeader, Modal } from '../components/UI'

import { API } from '../config.js'

export default function Jobs() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('Idle')
  const [selected, setSelected] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [generatedProposal, setGeneratedProposal] = useState(null)
  const [showModal, setShowModal] = useState(false)

  useEffect(() => { loadJobs() }, [])

  const loadJobs = async () => {
    try {
      const r = await fetch(`${API}/scraper/jobs`)
      if (r.ok) {
        const d = await r.json()
        setJobs(d.jobs || [])
      }
    } catch {}
  }

  const startScrape = async () => {
    setLoading(true)
    setStatus('Scanning…')
    try {
      await fetch(`${API}/scraper/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_jobs: 20 }),
      })
      // Poll status
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`${API}/scraper/status`)
          const s = await r.json()
          setStatus(s.message || '')
          if (!s.running) {
            clearInterval(poll)
            setLoading(false)
            loadJobs()
          }
        } catch { clearInterval(poll); setLoading(false) }
      }, 1500)
    } catch { setLoading(false) }
  }

  const generateProposal = async (job) => {
    setGenerating(true)
    setGeneratedProposal(null)
    try {
      const r = await fetch(`${API}/proposals/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: job.id,
          job_title: job.title,
          job_description: job.description,
          budget: job.budget,
          platform: job.platform,
          skills: job.skills || [],
          job_link: job.link || '',
        }),
      })
      if (r.ok) {
        const d = await r.json()
        setGeneratedProposal(d)
        setShowModal(true)
      }
    } catch {}
    setGenerating(false)
  }

  return (
    <div style={{ padding: '28px', overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px', flexWrap: 'wrap', gap: '10px' }}>
        <PageHeader breadcrumb="JOB SCANNER" title="◎ OPPORTUNITY SCANNER" />
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em' }}>{status}</span>
          <Btn onClick={startScrape} disabled={loading}>{loading ? '⟳ SCANNING…' : '⟳ SCAN NOW'}</Btn>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(380px,1fr))', gap: '10px' }}>
        {jobs.length === 0 && !loading && (
          <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: '60px', color: 'rgba(255,255,255,0.18)', fontSize: '11px', lineHeight: 2 }}>
            NO JOBS LOADED<br />
            <span style={{ fontSize: '9px' }}>Click SCAN NOW to fetch live jobs from Freelancer.com</span>
          </div>
        )}
        {jobs.map(job => (
          <div key={job.id} onClick={() => setSelected(job === selected ? null : job)} style={{
            padding: '14px', borderRadius: '4px', cursor: 'pointer', transition: 'all 0.15s',
            background: selected?.id === job.id ? 'rgba(0,212,255,0.07)' : 'rgba(255,255,255,0.02)',
            border: `1px solid ${selected?.id === job.id ? '#00d4ff' : 'rgba(255,255,255,0.07)'}`,
          }}>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
              <Ring score={job.score || 75} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: '6px', marginBottom: '5px', flexWrap: 'wrap' }}>
                  <Badge label={job.platform} color="#00d4ff" />
                  {job.budget && <Badge label={job.budget} color="#00ff88" />}
                </div>
                <div style={{ fontSize: '13px', fontWeight: '600', color: '#c4e4ef', marginBottom: '4px', lineHeight: 1.3 }}>
                  {job.title}
                </div>
                <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.35)', lineHeight: 1.5, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                  {job.description}
                </div>
                {job.skills?.length > 0 && (
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '6px' }}>
                    {job.skills.map(s => <Badge key={s} label={s} color="rgba(255,255,255,0.3)" />)}
                  </div>
                )}
              </div>
            </div>
            {selected?.id === job.id && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <Btn onClick={() => generateProposal(job)} disabled={generating} variant="primary">
                  {generating ? '⟳ GENERATING…' : '✦ GENERATE PROPOSAL'}
                </Btn>
                {job.link && (
                  <Btn onClick={() => window.open(job.link, '_blank')} variant="ghost" small>OPEN JOB ↗</Btn>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {showModal && generatedProposal && (
        <Modal title={`PROPOSAL — ${generatedProposal.job_title}`} onClose={() => setShowModal(false)}>
          <div style={{ marginBottom: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <Badge label={`Confidence: ${generatedProposal.confidence}%`} color="#00ff88" />
            <Badge label={generatedProposal.work_type || 'other'} color="#00d4ff" />
            {generatedProposal.can_auto_work && <Badge label="AUTO-WORKABLE" color="#ff9500" />}
          </div>
          <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.3)', marginBottom: '8px', letterSpacing: '0.1em' }}>
            {generatedProposal.work_reason}
          </div>
          <textarea readOnly value={generatedProposal.proposal_text || ''} style={{
            width: '100%', minHeight: '200px', background: 'rgba(0,10,20,0.8)',
            border: '1px solid rgba(0,212,255,0.2)', outline: 'none', color: '#c8e8f0',
            padding: '12px', fontSize: '12px', fontFamily: 'sans-serif',
            lineHeight: 1.75, resize: 'vertical', borderRadius: '3px',
          }} />
          <div style={{ marginTop: '12px', display: 'flex', gap: '8px' }}>
            <Btn onClick={() => { navigator.clipboard?.writeText(generatedProposal.proposal_text); setShowModal(false) }} variant="success">
              COPY &amp; CLOSE
            </Btn>
            <Btn onClick={() => setShowModal(false)} variant="ghost">CLOSE</Btn>
          </div>
        </Modal>
      )}
    </div>
  )
}
