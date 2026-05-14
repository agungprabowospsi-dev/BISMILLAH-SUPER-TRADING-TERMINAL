import React, { useEffect, useState, useCallback } from 'react'
import { RefreshCw, TrendingUp, TrendingDown, Minus } from 'lucide-react'

const BACKEND = import.meta.env.VITE_BACKEND_URL || 'https://backend-production-daed.up.railway.app'

const REGIME_CONFIG = {
  'STRONG BULL': { color: '#22c55e', bg: '#052e16', label: 'STRONG BULL', score: 90 },
  'BULL':        { color: '#86efac', bg: '#14532d', label: 'BULL',        score: 70 },
  'SIDEWAYS':    { color: '#fbbf24', bg: '#1c1917', label: 'SIDEWAYS',    score: 50 },
  'BEAR':        { color: '#f87171', bg: '#450a0a', label: 'BEAR',        score: 30 },
  'STRONG BEAR': { color: '#ef4444', bg: '#3b0606', label: 'STRONG BEAR', score: 10 },
}

const SEKTORAL_LABEL = {
  IDXBASIC:'Basic Mat',IDXCYC:'Cons Cyc',IDXNONCYC:'Cons Non-Cyc',
  IDXENERGY:'Energy',IDXFINANCE:'Finance',IDXHEALTH:'Health',
  IDXINDUST:'Industrial',IDXINFRA:'Infra',IDXPROPERT:'Property',
  IDXTECHNO:'Tech',IDXTRANS:'Transport'
}

const INDEX_LABELS = {
  IHSG:'IHSG',LQ45:'LQ45',IDX30:'IDX30',IDXG30:'IDXG30',
  IDXESGL:'IDXESGL',IDXSMC:'SMC',IDXBUMN:'BUMN',IDXHIDIV:'HiDiv',IDXVESTA:'VESTA'
}

function GaugeMeter({ score, regime }) {
  const cfg = REGIME_CONFIG[regime] || REGIME_CONFIG['SIDEWAYS']
  const angle = -135 + (score / 100) * 270
  const r = 80, cx = 100, cy = 100
  const polarToXY = (deg, radius) => {
    const rad = (deg - 90) * Math.PI / 180
    return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) }
  }
  const arcPath = (startDeg, endDeg, radius) => {
    const s = polarToXY(startDeg, radius), e = polarToXY(endDeg, radius)
    const large = endDeg - startDeg > 180 ? 1 : 0
    return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`
  }
  const needle = polarToXY(angle, 60)
  return (
    <div style={{ display:'flex', flexDirection:'column', alignItems:'center' }}>
      <svg width="200" height="160" viewBox="0 0 200 160">
        <path d={arcPath(-135, 135, r)} fill="none" stroke="#334155" strokeWidth="16" strokeLinecap="round"/>
        <path d={arcPath(-135, -45, r)} fill="none" stroke="#ef4444" strokeWidth="16" strokeLinecap="round" opacity="0.6"/>
        <path d={arcPath(-45, 45, r)} fill="none" stroke="#fbbf24" strokeWidth="16" strokeLinecap="round" opacity="0.6"/>
        <path d={arcPath(45, 135, r)} fill="none" stroke="#22c55e" strokeWidth="16" strokeLinecap="round" opacity="0.6"/>
        <line x1={cx} y1={cy} x2={needle.x} y2={needle.y} stroke={cfg.color} strokeWidth="3" strokeLinecap="round"/>
        <circle cx={cx} cy={cy} r="6" fill={cfg.color}/>
        <text x={cx} y={cy+30} textAnchor="middle" fill={cfg.color} fontSize="22" fontWeight="bold" fontFamily="monospace">{score}</text>
        <text x={cx} y={cy+46} textAnchor="middle" fill="#94a3b8" fontSize="9" fontFamily="monospace">BULL SCORE</text>
        <text x="20" y="148" fill="#ef4444" fontSize="8" fontFamily="monospace">BEAR</text>
        <text x="87" y="148" fill="#fbbf24" fontSize="8" fontFamily="monospace">SIDE</text>
        <text x="158" y="148" fill="#22c55e" fontSize="8" fontFamily="monospace">BULL</text>
      </svg>
      <div style={{ marginTop:-8, padding:'4px 16px', borderRadius:6, background:cfg.bg, border:`1px solid ${cfg.color}`, color:cfg.color, fontFamily:'monospace', fontWeight:'bold', fontSize:14, letterSpacing:2 }}>
        {cfg.label}
      </div>
    </div>
  )
}

function BreadthBar({ positive=0, negative=0, neutral=0 }) {
  const total = positive + negative + neutral || 1
  const pct = v => Math.round(v/total*100)
  return (
    <div>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
        <span style={{ color:'#22c55e', fontFamily:'monospace', fontSize:12 }}>▲ {positive} ({pct(positive)}%)</span>
        <span style={{ color:'#64748b', fontFamily:'monospace', fontSize:12 }}>— {neutral}</span>
        <span style={{ color:'#ef4444', fontFamily:'monospace', fontSize:12 }}>▼ {negative} ({pct(negative)}%)</span>
      </div>
      <div style={{ display:'flex', height:10, borderRadius:5, overflow:'hidden', background:'#f8fafc' }}>
        <div style={{ width:`${pct(positive)}%`, background:'#22c55e' }}/>
        <div style={{ width:`${pct(neutral)}%`, background:'#64748b' }}/>
        <div style={{ width:`${pct(negative)}%`, background:'#ef4444' }}/>
      </div>
    </div>
  )
}

function IndexCard({ code, data }) {
  const label = INDEX_LABELS[code] || code
  const chg = data?.change_pct || 0
  const close = data?.close || 0
  const color = chg > 0 ? '#22c55e' : chg < 0 ? '#ef4444' : '#64748b'
  const Icon = chg > 0 ? TrendingUp : chg < 0 ? TrendingDown : Minus
  return (
    <div style={{ background:'#f8fafc', border:'1px solid #334155', borderRadius:8, padding:'10px 12px', display:'flex', flexDirection:'column', gap:4 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <span style={{ fontFamily:'monospace', fontSize:11, color:'#64748b', fontWeight:'bold' }}>{label}</span>
        <Icon size={12} color={color}/>
      </div>
      <div style={{ fontFamily:'monospace', fontSize:14, fontWeight:'bold', color:'#1e293b' }}>
        {close > 0 ? close.toFixed(2) : '—'}
      </div>
      <div style={{ fontFamily:'monospace', fontSize:11, color }}>
        {chg !== 0 ? `${chg > 0 ? '+' : ''}${chg.toFixed(2)}%` : 'TUTUP'}
      </div>
    </div>
  )
}

function SektoralHeatmap({ sektoral }) {
  if (!sektoral) return null
  return (
    <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(100px,1fr))', gap:6 }}>
      {Object.entries(sektoral).map(([code, d]) => {
        const chg = d?.change_pct || 0
        const intensity = Math.min(Math.abs(chg) / 3, 1)
        const bg = chg > 0 ? `rgba(34,197,94,${0.1+intensity*0.5})` : chg < 0 ? `rgba(239,68,68,${0.1+intensity*0.5})` : 'rgba(71,85,105,0.3)'
        const color = chg > 0 ? '#86efac' : chg < 0 ? '#fca5a5' : '#64748b'
        return (
          <div key={code} style={{ background:bg, border:`1px solid ${color}30`, borderRadius:6, padding:'8px 6px', textAlign:'center' }}>
            <div style={{ fontFamily:'monospace', fontSize:9, color:'#64748b', marginBottom:2 }}>{SEKTORAL_LABEL[code]||code}</div>
            <div style={{ fontFamily:'monospace', fontSize:12, fontWeight:'bold', color }}>
              {chg !== 0 ? `${chg>0?'+':''}${chg.toFixed(1)}%` : '—'}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function MarketRegimePage() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [countdown, setCountdown] = useState(60)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${BACKEND}/api/analytic/market-regime`)
      const json = await res.json()
      setData(json.data)
      setLastUpdate(new Date())
      setCountdown(60)
    } catch(e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])
  useEffect(() => { const iv = setInterval(fetchData, 60000); return () => clearInterval(iv) }, [fetchData])
  useEffect(() => { const iv = setInterval(() => setCountdown(c => c > 0 ? c-1 : 60), 1000); return () => clearInterval(iv) }, [])

  const regime = data?._regime || 'SIDEWAYS'
  const breadth = data?._breadth || {}
  const lq45Change = data?._lq45_change || 0
  const sektoral = data?._sektoral || {}
  const cfg = REGIME_CONFIG[regime] || REGIME_CONFIG['SIDEWAYS']
  const bullScore = cfg.score
  const indexKeys = data ? Object.keys(data).filter(k => !k.startsWith('_')) : []

  return (
    <div style={{ padding:'16px 20px', maxWidth:1200, margin:'0 auto' }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
        <div>
          <h1 style={{ fontFamily:'monospace', fontSize:18, fontWeight:'bold', color:'#1e293b', margin:0 }}>📊 Market Regime Engine</h1>
          <p style={{ fontFamily:'monospace', fontSize:11, color:'#64748b', margin:'2px 0 0' }}>20 Index IDX · Real-time Analysis</p>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <span style={{ fontFamily:'monospace', fontSize:11, color:'#64748b' }}>Refresh dalam {countdown}s</span>
          {lastUpdate && <span style={{ fontFamily:'monospace', fontSize:11, color:'#64748b' }}>Update: {lastUpdate.toLocaleTimeString('id-ID')}</span>}
          <button onClick={fetchData} disabled={loading} style={{ display:'flex', alignItems:'center', gap:6, padding:'6px 12px', background:'#f8fafc', border:'1px solid #334155', borderRadius:6, color:'#64748b', cursor:'pointer', fontFamily:'monospace', fontSize:11 }}>
            <RefreshCw size={12} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }}/>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'240px 1fr', gap:16, marginBottom:16 }}>
        <div style={{ background:'#ffffff', border:`1px solid ${cfg.color}40`, borderRadius:12, padding:20, display:'flex', flexDirection:'column', alignItems:'center', gap:12 }}>
          <GaugeMeter score={bullScore} regime={regime}/>
          <div style={{ width:'100%' }}>
            <div style={{ fontFamily:'monospace', fontSize:10, color:'#64748b', marginBottom:4 }}>LQ45 CHANGE</div>
            <div style={{ fontFamily:'monospace', fontSize:16, fontWeight:'bold', color: lq45Change >= 0 ? '#22c55e' : '#ef4444' }}>
              {lq45Change >= 0 ? '+' : ''}{lq45Change.toFixed(2)}%
            </div>
          </div>
        </div>
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          <div style={{ background:'#ffffff', border:'1px solid #f8fafc', borderRadius:12, padding:16 }}>
            <div style={{ fontFamily:'monospace', fontSize:11, color:'#64748b', marginBottom:10, display:'flex', justifyContent:'space-between' }}>
              <span>MARKET BREADTH (LQ45)</span>
              <span style={{ color: breadth.breadth_ratio > 0 ? '#22c55e' : '#ef4444' }}>Ratio: {((breadth.breadth_ratio||0)*100).toFixed(0)}%</span>
            </div>
            <BreadthBar positive={breadth.positive} negative={breadth.negative} neutral={breadth.neutral}/>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(110px,1fr))', gap:8 }}>
            {indexKeys.map(code => <IndexCard key={code} code={code} data={data[code]}/>)}
          </div>
        </div>
      </div>

      <div style={{ background:'#ffffff', border:'1px solid #f8fafc', borderRadius:12, padding:16 }}>
        <div style={{ fontFamily:'monospace', fontSize:11, color:'#64748b', marginBottom:12 }}>SEKTORAL HEATMAP (11 Sektor IDX)</div>
        <SektoralHeatmap sektoral={sektoral}/>
        {Object.keys(sektoral).length === 0 && (
          <div style={{ fontFamily:'monospace', fontSize:12, color:'#64748b', textAlign:'center', padding:20 }}>Pasar tutup — data sektoral tidak tersedia</div>
        )}
      </div>
      <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
    </div>
  )
}
