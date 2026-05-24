import React from 'react'
import clsx from 'clsx'

export function ScoreGauge({ score=0, size=80, label }) {
  const pct = Math.max(0, Math.min(100, score))
  const color = pct>=70?'#00FF88':pct>=45?'#FFB800':'#FF3355'
  const c = 2*Math.PI*28
  const dash = (pct/100)*c
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} viewBox="0 0 64 64">
        <circle cx="32" cy="32" r="28" fill="none" stroke="#1E2D45" strokeWidth="4"/>
        <circle cx="32" cy="32" r="28" fill="none" stroke={color} strokeWidth="4"
          strokeDasharray={`${dash} ${c}`} strokeLinecap="round"
          transform="rotate(-90 32 32)"
          style={{filter:`drop-shadow(0 0 4px ${color}40)`,transition:'stroke-dasharray 0.6s ease'}}/>
        <text x="32" y="36" textAnchor="middle" fontSize="13" fontWeight="700" fill={color} fontFamily="JetBrains Mono">
          {Math.round(pct)}
        </text>
      </svg>
      {label && <span className="label-xs text-center">{label}</span>}
    </div>
  )
}

export function ScoreBar({ label, score=0 }) {
  const pct = Math.max(0,Math.min(100,score))
  const color = pct>=70?'bg-accent-green':pct>=45?'bg-accent-gold':'bg-accent-red'
  return (
    <div className="space-y-1">
      <div className="flex justify-between items-center">
        <span className="text-xs text-slate-400 font-mono">{label}</span>
        <span className="text-xs font-mono font-semibold text-white">{Math.round(pct)}</span>
      </div>
      <div className="score-bar">
        <div className={clsx('h-full rounded-full transition-all duration-700',color)} style={{width:`${pct}%`}}/>
      </div>
    </div>
  )
}

export function SignalBadge({ signal }) {
  if(!signal) return null
  const s = String(signal).toUpperCase()
  if(s.includes('BUY')||s.includes('LONG')||s.includes('ENTRY')) return <span className="badge-buy">{s}</span>
  if(s.includes('SELL')||s.includes('SHORT')||s.includes('EXIT')) return <span className="badge-sell">{s}</span>
  return <span className="badge-hold">{s}</span>
}

export function ConfidenceBar({ value=0 }) {
  const color = value>=70?'#00FF88':value>=45?'#FFB800':'#FF3355'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-border-dim rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700"
          style={{width:`${value}%`,background:color,boxShadow:`0 0 8px ${color}60`}}/>
      </div>
      <span className="font-mono text-xs font-bold" style={{color}}>{Math.round(value)}%</span>
    </div>
  )
}

export function LoadingSpinner({ message='Analyzing...' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4">
      <div className="relative w-16 h-16">
        <div className="absolute inset-0 border-2 border-border-dim rounded-full"/>
        <div className="absolute inset-0 border-2 border-t-accent-green rounded-full animate-spin"/>
      </div>
      <div className="text-center">
        <p className="font-mono text-sm text-accent-green">{message}</p>
        <p className="font-mono text-xs text-slate-600 mt-1">35 engines processing...</p>
      </div>
    </div>
  )
}

export function ErrorBox({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center gap-4 py-12">
      <div className="w-12 h-12 rounded-full border border-accent-red/30 bg-accent-red/5 flex items-center justify-center">
        <span className="text-accent-red text-xl">!</span>
      </div>
      <p className="font-mono text-sm text-accent-red text-center">{message}</p>
      {onRetry && <button onClick={onRetry} className="btn-ghost text-xs">Retry</button>}
    </div>
  )
}
