import React, { useEffect, useState, useCallback } from 'react'
import { RefreshCw, TrendingUp, TrendingDown } from 'lucide-react'

const BACKEND = import.meta.env.VITE_BACKEND_URL || 'https://backend-production-daed.up.railway.app'

export default function ForeignFlowPage() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${BACKEND}/api/analytic/foreign-flow`)
      const json = await res.json()
      setData(json.data)
      setLastUpdate(new Date())
    } catch(e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])
  useEffect(() => { const iv = setInterval(fetchData, 120000); return () => clearInterval(iv) }, [fetchData])

  const summary = data?.summary || {}
  const stocks = data?.stocks || []
  const isNetBuy = summary.signal === 'NET BUY'

  return (
    <div style={{ padding:'16px 20px', maxWidth:1200, margin:'0 auto' }}>
      {/* Header */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
        <div>
          <h1 style={{ fontFamily:'monospace', fontSize:18, fontWeight:'bold', color:'#f1f5f9', margin:0 }}>
            🌏 Foreign Flow Dashboard
          </h1>
          <p style={{ fontFamily:'monospace', fontSize:11, color:'#64748b', margin:'2px 0 0' }}>
            {data?.period || '30 hari terakhir'} · {data?.universe || 'LQ45 Top 10'} · Broker Summary BEI
          </p>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          {lastUpdate && <span style={{ fontFamily:'monospace', fontSize:11, color:'#64748b' }}>Update: {lastUpdate.toLocaleTimeString('id-ID')}</span>}
          <button onClick={fetchData} disabled={loading} style={{ display:'flex', alignItems:'center', gap:6, padding:'6px 12px', background:'#1e293b', border:'1px solid #334155', borderRadius:6, color:'#94a3b8', cursor:'pointer', fontFamily:'monospace', fontSize:11 }}>
            <RefreshCw size={12} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }}/>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      {loading && !data && (
        <div style={{ textAlign:'center', padding:60, fontFamily:'monospace', color:'#64748b' }}>
          Mengambil data broker 10 saham LQ45... (~15 detik)
        </div>
      )}

      {data && <>
        {/* Summary Cards */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12, marginBottom:16 }}>
          {[
            { label:'TOTAL FOREIGN BUY', value:`${summary.total_foreign_buy?.toLocaleString('id-ID')} M`, color:'#22c55e' },
            { label:'TOTAL FOREIGN SELL', value:`${summary.total_foreign_sell?.toLocaleString('id-ID')} M`, color:'#ef4444' },
            { label:'NET FOREIGN', value:`${summary.total_net > 0 ? '+' : ''}${summary.total_net?.toLocaleString('id-ID')} M`, color: summary.total_net >= 0 ? '#22c55e' : '#ef4444' },
            { label:'SIGNAL', value: summary.signal, color: isNetBuy ? '#22c55e' : '#ef4444' },
          ].map((c,i) => (
            <div key={i} style={{ background:'#0f172a', border:`1px solid ${c.color}30`, borderRadius:10, padding:'14px 16px' }}>
              <div style={{ fontFamily:'monospace', fontSize:9, color:'#64748b', marginBottom:6 }}>{c.label}</div>
              <div style={{ fontFamily:'monospace', fontSize:16, fontWeight:'bold', color: c.color }}>{c.value}</div>
            </div>
          ))}
        </div>

        {/* Stock Table */}
        <div style={{ background:'#0f172a', border:'1px solid #1e293b', borderRadius:12, overflow:'hidden' }}>
          <div style={{ padding:'12px 16px', borderBottom:'1px solid #1e293b', fontFamily:'monospace', fontSize:11, color:'#64748b' }}>
            DETAIL PER SAHAM — Net Foreign Buy/Sell (Miliar Rupiah)
          </div>
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse' }}>
              <thead>
                <tr style={{ background:'#1e293b' }}>
                  {['SAHAM','SIGNAL','NET (M)','BUY (M)','SELL (M)','TOP BROKER ASING'].map(h => (
                    <th key={h} style={{ padding:'8px 12px', fontFamily:'monospace', fontSize:10, color:'#64748b', textAlign:'left', fontWeight:'normal' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stocks.map((s, i) => {
                  const isBuy = s.signal === 'BUY'
                  const color = isBuy ? '#22c55e' : s.signal === 'SELL' ? '#ef4444' : '#94a3b8'
                  return (
                    <tr key={s.ticker} style={{ borderBottom:'1px solid #1e293b', background: i%2===0 ? 'transparent' : '#0a0f1a' }}>
                      <td style={{ padding:'10px 12px', fontFamily:'monospace', fontSize:13, fontWeight:'bold', color:'#f1f5f9' }}>{s.ticker}</td>
                      <td style={{ padding:'10px 12px' }}>
                        <span style={{ display:'inline-flex', alignItems:'center', gap:4, padding:'2px 8px', borderRadius:4, background:`${color}20`, color, fontFamily:'monospace', fontSize:10, fontWeight:'bold' }}>
                          {isBuy ? <TrendingUp size={10}/> : <TrendingDown size={10}/>}
                          {s.signal}
                        </span>
                      </td>
                      <td style={{ padding:'10px 12px', fontFamily:'monospace', fontSize:12, color, fontWeight:'bold' }}>
                        {s.foreign_net > 0 ? '+' : ''}{s.foreign_net?.toFixed(2)}
                      </td>
                      <td style={{ padding:'10px 12px', fontFamily:'monospace', fontSize:12, color:'#86efac' }}>{s.foreign_buy?.toFixed(2)}</td>
                      <td style={{ padding:'10px 12px', fontFamily:'monospace', fontSize:12, color:'#fca5a5' }}>{s.foreign_sell?.toFixed(2)}</td>
                      <td style={{ padding:'10px 12px' }}>
                        <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
                          {s.top_brokers?.slice(0,3).map(b => (
                            <span key={b.broker} style={{ fontFamily:'monospace', fontSize:9, padding:'2px 6px', borderRadius:3, background: b.net_value > 0 ? '#052e16' : '#450a0a', color: b.net_value > 0 ? '#86efac' : '#fca5a5', border:`1px solid ${b.net_value > 0 ? '#166534' : '#991b1b'}` }}>
                              {b.broker} {b.net_value > 0 ? '+' : ''}{(b.net_value/1e9).toFixed(1)}M
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div style={{ marginTop:10, fontFamily:'monospace', fontSize:10, color:'#475569', textAlign:'center' }}>
          ⚠️ Data kumulatif 30 hari dari Broker Summary BEI. Broker asing: UBS, JP Morgan, Macquarie, Kim Eng, Deutsche, Morgan Stanley, DBS, Citi, Mirae.
        </div>
      </>}

      <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
    </div>
  )
}
