import React, { useState, useEffect } from 'react'

const BACKEND = 'https://backend-production-daed.up.railway.app'

const CHECKS = [
  { key:'backend', label:'API', endpoint:'/health', ok: d => d?.status==='ok'||d?.returncode===0 },
  { key:'data', label:'DB', endpoint:'/api/analytic/data/status', ok: d => d?.status==='ok' },
  { key:'kb', label:'KB', endpoint:'/api/kb/documents', ok: d => d?.success&&d?.documents?.length>0 },
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
  const color = score >= 80 ? '#22c55e' : score >= 50 ? '#eab308' : '#ef4444'
  const label = score >= 80 ? 'SEHAT' : score >= 50 ? 'PERHATIAN' : 'BERMASALAH'

  // SVG half-circle gauge
  // ViewBox 0 0 200 110, center 100,100, radius 80
  const r = 80
  const cx = 100, cy = 100
  // circumference of half circle = PI * r
  const circ = Math.PI * r

  // Needle angle: score 0=180deg(left), 100=0deg(right)
  const toRad = d => d * Math.PI / 180
  const angle = 180 - (score / 100) * 180
  const nx = cx + 65 * Math.cos(toRad(angle))
  const ny = cy + 65 * Math.sin(toRad(angle))

  return (
    <div style={{
      background:'#fff', borderRadius:12, padding:'16px 20px',
      border:`1px solid ${color}50`,
      boxShadow:'0 2px 8px rgba(0,0,0,0.06)',
      display:'flex', alignItems:'center', gap:20, marginBottom:16
    }}>
      <svg viewBox='0 0 200 110' width='200' height='110' style={{flexShrink:0}}>
        {/* 3 colored arc segments using strokeDasharray on half-circle */}
        {/* Red: 0 to 33% */}
        <path d={`M ${cx-r} ${cy} A ${r} ${r} 0 0 1 ${cx+r} ${cy}`}
          fill='none' stroke='#e2e8f0' strokeWidth='16' strokeLinecap='round'/>
        {/* Red segment */}
        <path d={`M ${cx-r} ${cy} A ${r} ${r} 0 0 1 ${cx+r} ${cy}`}
          fill='none' stroke='#ef4444' strokeWidth='14'
          strokeDasharray={`${circ*0.33} ${circ}`}
          strokeDashoffset='0' strokeLinecap='butt'/>
        {/* Yellow segment */}
        <path d={`M ${cx-r} ${cy} A ${r} ${r} 0 0 1 ${cx+r} ${cy}`}
          fill='none' stroke='#eab308' strokeWidth='14'
          strokeDasharray={`${circ*0.34} ${circ}`}
          strokeDashoffset={`${-circ*0.33}`} strokeLinecap='butt'/>
        {/* Green segment */}
        <path d={`M ${cx-r} ${cy} A ${r} ${r} 0 0 1 ${cx+r} ${cy}`}
          fill='none' stroke='#22c55e' strokeWidth='14'
          strokeDasharray={`${circ*0.33} ${circ}`}
          strokeDashoffset={`${-circ*0.67}`} strokeLinecap='butt'/>
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth='3' strokeLinecap='round'/>
        <circle cx={cx} cy={cy} r='6' fill={color}/>
        <circle cx={cx} cy={cy} r='3' fill='white'/>
        {/* Score */}
        <text x={cx} y={cy-20} textAnchor='middle' fontSize='24' fontWeight='bold' fill={color} fontFamily='monospace'>{loading?'...':score}</text>
        <text x={cx} y={cy-6} textAnchor='middle' fontSize='8' fill='#94a3b8' fontFamily='monospace'>HEALTH SCORE</text>
        <text x={cx} y={cy+16} textAnchor='middle' fontSize='10' fontWeight='bold' fill={color} fontFamily='monospace'>{loading?'CHECKING...':label}</text>
        <text x='12' y={cy+16} fontSize='8' fill='#ef4444' fontFamily='monospace'>KRITIS</text>
        <text x='154' y={cy+16} fontSize='8' fill='#22c55e' fontFamily='monospace'>SEHAT</text>
      </svg>

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

              </div>
            )
          })}
        </div>
        <div style={{fontFamily:'monospace',fontSize:9,color:'#cbd5e1',marginTop:8}}>Auto refresh 5 detik</div>
      </div>
    </div>
  )
}