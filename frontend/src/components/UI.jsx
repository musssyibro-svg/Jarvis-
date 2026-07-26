// components/UI.jsx — shared micro-components
//
// Colours go through ../colors so a caller passing rgba() or a css var can't
// silently produce an invalid declaration (which renders as a white blank).
import { tint } from '../colors'

export const Badge = ({ label, color = '#00d4ff' }) => (
  <span style={{
    fontSize: '9px', fontFamily: 'monospace', letterSpacing: '0.12em',
    padding: '2px 7px', borderRadius: '2px', textTransform: 'uppercase',
    border: `1px solid ${color}`, color,
    background: tint(color, 0.07),
  }}>{label}</span>
)

export const StatCard = ({ label, value, sub, color = '#00d4ff' }) => (
  <div style={{
    border: `1px solid ${tint(color, 0.16)}`, background: 'rgba(0,10,22,0.75)',
    padding: '20px', borderRadius: '4px', position: 'relative', overflow: 'hidden',
  }}>
    <div style={{ fontSize: '9px', color: tint(color, 0.55), letterSpacing: '0.2em', marginBottom: '8px' }}>
      {label}
    </div>
    <div style={{
      fontSize: '30px', fontWeight: '700', color, fontFamily: 'sans-serif',
      textShadow: `0 0 18px ${tint(color, 0.33)}`,
    }}>{value}</div>
    {sub && <div style={{ fontSize: '9px', color: 'rgba(255,255,255,0.25)', marginTop: '5px' }}>{sub}</div>}
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0, height: '2px',
      background: `linear-gradient(90deg,transparent,${color},transparent)`, opacity: 0.35,
    }} />
  </div>
)

export const Ring = ({ score = 80, size = 44 }) => {
  const c = score >= 90 ? '#00ff88' : score >= 80 ? '#00d4ff' : score >= 70 ? '#ff9500' : '#ff4444'
  const r = size / 2 - 4
  const circ = 2 * Math.PI * r
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="3" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={c} strokeWidth="3"
          strokeDasharray={`${(score/100)*circ} ${circ}`} strokeLinecap="round"
          transform={`rotate(-90 ${size/2} ${size/2})`}
          style={{ filter: `drop-shadow(0 0 4px ${c})` }} />
      </svg>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: '10px', fontWeight: '700', color: c,
        fontFamily: 'monospace',
      }}>{score}</div>
    </div>
  )
}

export const Modal = ({ title, children, onClose }) => (
  <div style={{
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 1000,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  }}>
    <div style={{
      background: '#040e18', border: '1px solid rgba(0,212,255,0.35)',
      borderRadius: '6px', padding: '24px', width: '600px', maxWidth: '95vw',
      maxHeight: '85vh', overflowY: 'auto', position: 'relative',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: '16px',
      }}>
        <div style={{ fontSize: '12px', color: '#00d4ff', letterSpacing: '0.15em' }}>{title}</div>
        <button onClick={onClose} style={{
          background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)',
          cursor: 'pointer', fontSize: '16px',
        }}>✕</button>
      </div>
      {children}
    </div>
  </div>
)

export const Btn = ({ children, onClick, disabled, variant = 'primary', small }) => {
  const colors = {
    primary: { bg: 'rgba(0,212,255,0.12)', border: '#00d4ff', color: '#00d4ff' },
    success: { bg: 'rgba(0,255,136,0.1)', border: '#00ff88', color: '#00ff88' },
    danger:  { bg: 'rgba(255,68,68,0.1)',  border: '#ff4444', color: '#ff4444' },
    ghost:   { bg: 'transparent',           border: 'rgba(255,255,255,0.12)', color: 'rgba(255,255,255,0.45)' },
  }
  const c = colors[variant] || colors.primary
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: small ? '4px 10px' : '9px 16px',
      fontSize: small ? '9px' : '10px',
      letterSpacing: '0.14em',
      fontFamily: 'Courier New, monospace',
      cursor: disabled ? 'not-allowed' : 'pointer',
      background: disabled ? 'rgba(255,255,255,0.03)' : c.bg,
      border: `1px solid ${disabled ? 'rgba(255,255,255,0.08)' : c.border}`,
      color: disabled ? 'rgba(255,255,255,0.2)' : c.color,
      borderRadius: '3px',
      transition: 'all 0.2s',
    }}>{children}</button>
  )
}

export const PageHeader = ({ breadcrumb, title }) => (
  <div style={{ marginBottom: '22px' }}>
    <div style={{ fontSize: '9px', color: 'rgba(0,212,255,0.5)', letterSpacing: '0.3em', marginBottom: '4px' }}>
      JARVIS // {breadcrumb}
    </div>
    <h1 style={{
      fontSize: '20px', color: '#00d4ff', letterSpacing: '0.1em',
      textShadow: '0 0 20px rgba(0,212,255,0.4)', fontFamily: 'sans-serif',
    }}>{title}</h1>
  </div>
)
