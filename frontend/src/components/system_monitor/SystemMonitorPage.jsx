import React, { useState, useEffect } from 'react'

const BACKEND = 'https://backend-production-daed.up.railway.app'

const CHECKS = [
  { key:'backend', label:'Backend API', endpoint:'/health', ok: d => d?.status==='ok'||d?.returncode===0 },
  { key:'data', label:'PostgreSQL Data', endpoint:'/api/analytic/data/status', ok: d => d?.status==='ok' },
  { key:'kb', label:'Knowledge Base (12 buku)', endpoint:'/api/kb/documents', ok: d => d?.success&&d?.documents?.length>0 },
  { key:'regime', label:'Market Regime Engine', endpoint:'/api/analytic/market-regime', ok: d => !!(d?.regime||d?.status==='ok') },
  { key:'foreign', label:'Foreign Flow Engine', endpoint:'/api/analytic/foreign-flow', ok: d => d?.status==='ok'||Array.isArray(d) },
]

function dot(color, pulse=false) {
  return { width:10, height:10, borderRadius:'50%', background:color,
    display:'inline-block', flexShrink:0,
    animation: pulse ? 'pulse 2s infinite' : 'none' }
}

export default function SystemMonitorPage() {
  const [results, setResults] = useState({})
  const [loading, setLoading] = useState(false)
  const [lastCheck, setLastCheck] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const runAll = async () => {
    setLoading(true)
    const out = {}
    await Promise.all(CHECKS.map(async c => {
      const t0 = Date.now()
      try {
        const r = await fetch(BACKEND + c.endpoint)
        const d = await r.json()
        out[c.key] = { ok: c.ok(d), data: d, ms: Date.now()-t0 }
      } catch(e) {
        out[c.key] = { ok: false, error: e.message, ms: Date.now()-t0 }
      }
    }))
    setResults(out)
    setLastCheck(new Date().toLocaleTimeString('id-ID'))
    setLoading(false)
  }

  useEffect(() => { runAll() }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const iv = setInterval(runAll, 30000)
    return () => clearInterval(iv)
  }, [autoRefresh])

  const total = CHECKS.length
  const ok = CHECKS.filter(c => results[c.key]?.ok).length
  const overall = ok === total ? 'green' : ok >= total/2 ? 'yellow' : 'red'
  const overallColor = overall==='green'?'#22c55e':overall==='yellow'?'#eab308':'#ef4444'
  const overallLabel = overall==='green'?'SEHAT':overall==='yellow'?'PERLU PERHATIAN':'BERMASALAH'

  return (
    <div style={{padding:'24px', maxWidth:900, margin:'0 auto'}}>
      <div style={{marginBottom:24}}>
        <h2 style={{fontFamily:'monospace',fontSize:18,fontWeight:'bold',color:'#1e293b',margin:0}}>
          SYSTEM MONITOR
        </h2>
        <div style={{fontFamily:'monospace',fontSize:11,color:'#94a3b8',marginTop:4}}>
          Real-time health check seluruh komponen sistem
        </div>
      </div>

      {/* OVERALL STATUS */}
      <div style={{
        padding:'20px 24px', borderRadius:12, marginBottom:24,
        border:`2px solid ${overallColor}40`,
        background:`${overallColor}10`,
        display:'flex', alignItems:'center', gap:16
      }}>
        <span style={dot(overallColor, overall==='green')}/>
        <div>
          <div style={{fontFamily:'monospace',fontSize:20,fontWeight:'bold',color:overallColor}}>
            {loading ? 'MEMERIKSA...' : overallLabel}
          </div>
          <div style={{fontFamily:'monospace',fontSize:11,color:'#64748b',marginTop:2}}>
            {ok}/{total} komponen sehat {lastCheck ? `· Last check: ${lastCheck}` : ''}
          </div>
        </div>
        <div style={{marginLeft:'auto',display:'flex',gap:8}}>
          <button onClick={runAll} disabled={loading} style={{
            fontFamily:'monospace',fontSize:11,padding:'6px 16px',borderRadius:6,
            border:'1px solid #334155',background:'#1e293b',color:'#e2e8f0',cursor:'pointer'
          }}>{loading?'...':'⟳ Refresh'}</button>
          <button onClick={()=>setAutoRefresh(a=>!a)} style={{
            fontFamily:'monospace',fontSize:11,padding:'6px 16px',borderRadius:6,
            border:`1px solid ${autoRefresh?'#22c55e':'#334155'}`,
            background:autoRefresh?'#22c55e20':'transparent',
            color:autoRefresh?'#22c55e':'#64748b',cursor:'pointer'
          }}>{autoRefresh?'Auto ON':'Auto OFF'}</button>
        </div>
      </div>

      {/* COMPONENT LIST */}
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        {CHECKS.map(c => {
          const r = results[c.key]
          const isOk = r?.ok
          const color = loading ? '#94a3b8' : isOk===undefined ? '#94a3b8' : isOk ? '#22c55e' : '#ef4444'
          const label = loading ? 'MEMERIKSA...' : isOk===undefined ? 'BELUM DICEK' : isOk ? 'SEHAT' : 'BERMASALAH'
          return (
            <div key={c.key} style={{
              padding:'14px 18px', borderRadius:8,
              border:`1px solid ${color}30`,
              background:`${color}08`,
              display:'flex', alignItems:'center', gap:12
            }}>
              <span style={dot(color)}/>
              <div style={{flex:1}}>
                <div style={{fontFamily:'monospace',fontSize:13,fontWeight:'600',color:'#1e293b'}}>
                  {c.label}
                </div>
                {r?.error && (
                  <div style={{fontFamily:'monospace',fontSize:10,color:'#ef4444',marginTop:2}}>
                    {r.error}
                  </div>
                )}
                {c.key==='data' && r?.data?.tickers && (
                  <div style={{fontFamily:'monospace',fontSize:10,color:'#64748b',marginTop:2}}>
                    {r.data.total_tickers} tickers tersimpan
                  </div>
                )}
                {c.key==='kb' && r?.data && (
                  <div style={{fontFamily:'monospace',fontSize:10,color:'#64748b',marginTop:2}}>
                    {r.data?.documents?.length || 0} buku tersedia
                  </div>
                )}
                {c.key==='regime' && r?.data?.regime && (
                  <div style={{fontFamily:'monospace',fontSize:10,color:'#64748b',marginTop:2}}>
                    Regime: {r.data.regime}
                  </div>
                )}
              </div>
              <div style={{textAlign:'right'}}>
                <div style={{fontFamily:'monospace',fontSize:11,fontWeight:'bold',color}}>
                  {label}
                </div>
                {r?.ms && (
                  <div style={{fontFamily:'monospace',fontSize:10,color:'#94a3b8'}}>
                    {r.ms}ms
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* INFO */}
      <div style={{marginTop:20,padding:'12px 16px',borderRadius:8,background:'#f8fafc',border:'1px solid #e2e8f0'}}>
        <div style={{fontFamily:'monospace',fontSize:10,color:'#94a3b8'}}>
          ● SEHAT = komponen berfungsi normal &nbsp;&nbsp;
          ● PERLU PERHATIAN = sebagian komponen bermasalah &nbsp;&nbsp;
          ● BERMASALAH = mayoritas komponen gagal
        </div>
      </div>
    </div>
  )
}