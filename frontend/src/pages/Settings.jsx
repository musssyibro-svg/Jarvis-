import { useState, useEffect } from 'react'
import { PageHeader, Btn } from '../components/UI'

import { API } from '../config.js'

const Field = ({ label, hint, value, onChange, type = 'text' }) => (
  <div style={{ marginBottom: '16px' }}>
    <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.6)', letterSpacing: '0.15em', marginBottom: '5px' }}>{label}</div>
    {hint && <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.25)', marginBottom: '5px' }}>{hint}</div>}
    <input type={type} value={value} onChange={e => onChange(e.target.value)}
      style={{ width: '100%', background: 'rgba(0,10,20,0.8)', border: '1px solid rgba(0,212,255,0.2)', outline: 'none', color: '#c8e8f0', padding: '9px 12px', fontSize: '12px', fontFamily: 'Courier New,monospace', borderRadius: '3px' }} />
  </div>
)

export default function Settings() {
  const [saved, setSaved] = useState(false)
  const [cfg, setCfg] = useState({
    your_name: 'Ibrahim',
    your_skills: 'Python, automation, web scraping, AI integration, FastAPI',
    ollama_model: 'deepseek-r1:latest',
    ollama_fast_model: 'qwen:latest',
    freelancer_token: '',
  })

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch(`${API}/settings`)
        if (r.ok) {
          const { settings } = await r.json()
          const map = {}
          settings.forEach(s => { map[s.key] = s.value })
          setCfg(c => ({ ...c, ...map }))
        }
      } catch {}
    }
    load()
  }, [])

  const save = async () => {
    for (const [key, value] of Object.entries(cfg)) {
      await fetch(`${API}/settings/${key}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      }).catch(() => {})
    }
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const set = (key) => (val) => setCfg(c => ({ ...c, [key]: val }))

  return (
    <div style={{ padding: '28px', overflowY: 'auto', height: '100%', maxWidth: '600px' }}>
      <PageHeader breadcrumb="SETTINGS" title="⚙ SETTINGS" />

      <div style={{ border: '1px solid rgba(0,212,255,0.12)', borderRadius: '4px', padding: '20px', background: 'rgba(0,10,20,0.7)', marginBottom: '16px' }}>
        <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.5)', letterSpacing: '0.2em', marginBottom: '16px' }}>PROFILE</div>
        <Field label="YOUR NAME" value={cfg.your_name} onChange={set('your_name')} hint="Used in proposals sign-off" />
        <Field label="YOUR SKILLS" value={cfg.your_skills} onChange={set('your_skills')} hint="Comma-separated, used in proposals" />
      </div>

      <div style={{ border: '1px solid rgba(0,212,255,0.12)', borderRadius: '4px', padding: '20px', background: 'rgba(0,10,20,0.7)', marginBottom: '16px' }}>
        <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.5)', letterSpacing: '0.2em', marginBottom: '16px' }}>AI MODELS (OLLAMA)</div>
        <Field label="REASONING MODEL" value={cfg.ollama_model} onChange={set('ollama_model')} hint="Used for proposal generation (deepseek-r1:latest recommended)" />
        <Field label="FAST MODEL" value={cfg.ollama_fast_model} onChange={set('ollama_fast_model')} hint="Used for quick tasks like reply drafts (qwen:latest)" />
      </div>

      <div style={{ border: '1px solid rgba(0,212,255,0.12)', borderRadius: '4px', padding: '20px', background: 'rgba(0,10,20,0.7)', marginBottom: '20px' }}>
        <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.5)', letterSpacing: '0.2em', marginBottom: '16px' }}>FREELANCER API</div>
        <Field label="OAUTH TOKEN" value={cfg.freelancer_token} onChange={set('freelancer_token')} type="password" hint="Get from freelancer.com/developers — enables direct API job fetching" />
      </div>

      <Btn onClick={save} variant={saved ? 'success' : 'primary'}>{saved ? '✓ SAVED' : 'SAVE SETTINGS'}</Btn>
    </div>
  )
}
