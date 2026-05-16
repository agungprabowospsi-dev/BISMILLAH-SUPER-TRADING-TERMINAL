import React, { useState, useEffect } from 'react'

const BACKEND = 'https://backend-production-daed.up.railway.app'

const CHECKS = [
  { key:'backend', label:'API', endpoint:'/health', ok: d => d?.status==='ok'||d?.returncode===0 },
  { key:'data', label:'DB', endpoint:'/api/analytic/data/status', ok: d => d?.status==='ok' },
  { key:'kb', label:'KB', endpoint:'/api/kb/documents', ok: d => d?.success&&d?.documents?.length>0 },
  { key:'regime', label:'Regime', endpoint:'/api/analytic/market-regime', ok: d => !!(d?.regime||d?.status==='ok') },
  { key:'foreign', label:'Flow', endpoint:'/api/analytic/foreign-flow', ok: d => d?.status==='ok'||Array.isArray(d) },
]

export default function SystemHealthGauge() {
  const [results, setResults] = useState({})
  const [loading, setLoading] = useState(true)

  const runAll = async () => {
    const out = {}
    await Promise.all(CHECKS.map(async c => {
      try {
        const r = await fetch(BACKEND + c.endpoint)
        const d = await r.json()
        out[c.key] = c.ok(d)
      } catch { out[c.key] = false }
    }))
    setResults(out)
    setLoading(false)
  }

  useEffect(() => {
    runAll()
    const iv = setInterval(runAll, 5000)
    return () => clearInterval(iv)
  }, [])

  const total = CHECKS.length
  const okCount = CHECKS.filter(c => results[c.key]).length
  const score = loading ? 50 : Math.round((okCount / total) * 100)

  // Gauge arc SVG
  const R = 70
  const cx = 90, cy = 90
  const startAngle = 180
  const endAngle = 0
  const toRad = deg => (deg * Math.PI) / 180
  const arcX = (deg) => cx + R * Math.cos(toRad(deg))
  const arcY = (deg) => cy + R * Math.sin(toRad(deg))

  // Background arc (gray)
  const bgPath = `M ${arcX(180)} ${arcY(180)} A ${R} ${R} 0 0 1 ${arcX(0)} ${arcY(0)}`

  // Colored arc segments: red 180-120, yellow 120-60, green 60-0
  const seg1 = `M ${arcX(180)} ${arcY(180)} A ${R} ${R} 0 0 1 ${arcX(120)} ${arcY(120)}`
  const seg2 = `M ${arcX(120)} ${arcY(120)} A ${R} ${R} 0 0 1 ${arcX(60)} ${arcY(60)}`
  const seg3 = `M ${arcX(60)} ${arcY(60)} A ${R} ${R} 0 0 1 ${arcX(0)} ${arcY(0)}`

  // Needle: score 0-100 maps to 180-0 degrees
  const needleAngle = 180 - (score / 100) * 180
  const needleLen = 55
  const nx = cx + needleLen * Math.cos(toRad(needleAngle))
  const ny = cy + needleLen * Math.sin(toRad(needleAngle))

  const color = score >= 80 ? '#22c55e' : score >= 50 ? '#eab308' : '#ef4444'
  const label = score >= 80 ? 'SEHAT' : score >= 50 ? 'PERHATIAN' : 'BERMASALAH'

  return (
    <div style={{
      background:'#fff', borderRadius:12, padding:'16px 20px',
      border:`1px solid ${color}40`, boxShadow:'0 2px 8px rgba(0,0,0,0.06)',
      display:'flex', alignItems:'center', gap:20, marginBottom:16
    }}>
      {/* GAUGE SVG */}
      <svg width={180} height={100} style={{flexShrink:0}}>
        {/* BG arc */}
        <path d={bgPath} fill='none' stroke='#e2e8f0' strokeWidth={14} strokeLinecap='round'/>
        {/* Colored segments */}
        <path d={seg1} fill='none' stroke='#ef4444' strokeWidth={14} strokeLinecap='butt'/>
        <path d={seg2} fill='none' stroke='#eab308' strokeWidth={14} strokeLinecap='butt'/>
        <path d={seg3} fill='none' stroke='#22c55e' strokeWidth={14} strokeLinecap='butt'/>
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth={3} strokeLinecap='round'/>
        <circle cx={cx} cy={cy} r={5} fill={color}/>
        {/* Score text */}
        <text x={cx} y={cy-10} textAnchor='middle' fontSize={22} fontWeight='bold' fill={color} fontFamily='monospace'>
          {loading ? '...' : score}
        </text>
        <text x={cx} y={cy+8} textAnchor='middle' fontSize={9} fill='#94a3b8' fontFamily='monospace'>HEALTH SCORE</text>
        {/* Labels */}
        <text x={16} y={cy+20} fontSize={8} fill='#ef4444' fontFamily='monospace'>KRITIS</text>
        <text x={148} y={cy+20} fontSize={8} fill='#22c55e' fontFamily='monospace'>SEHAT</text>
        {/* Status label */}
        <text x={cx} y={cy+28} textAnchor='middle' fontSize={10} fontWeight='bold' fill={color} fontFamily='monospace'>
          {loading ? 'CHECKING...' : label}
        </text>
      </svg>

      {/* COMPONENT DOTS */}
      <div style={{flex:1}}>
        <div style={{fontFamily:'monospace',fontSize:11,color:'#64748b',marginBottom:8}}>
          KOMPONEN SISTEM — {okCount}/{total} sehat
        </div>
        <div style={{display:'flex',flexDirection:'column',gap:6}}>
          {CHECKS.map(c => {
            const ok = results[c.key]
            const col = loading ? '#94a3b8' : ok ? '#22c55e' : '#ef4444'
            return (
              <div key={c.key} style={{display:'flex',alignItems:'center',gap:8}}>
                <span style={{width:8,height:8,borderRadius:'50%',background:col,display:'inline-block',flexShrink:0}}/>
                <span style={{fontFamily:'monospace',fontSize:11,color:'#475569'}}>{c.label}</span>
                <span style={{fontFamily:'monospace',fontSize:10,color:col,marginLeft:'auto'}}>
                  {loading ? '...' : ok ? 'OK' : 'FAIL'}
                </span>
              </div>
            )
          })}
        </div>
        <div style={{fontFamily:'monospace',fontSize:9,color:'#cbd5e1',marginTop:8}}>
          Auto refresh 5 detik
        </div>
      </div>
    </div>
  )
}