import React, { useEffect, useState } from 'react'

const BACKEND = import.meta.env.VITE_BACKEND_URL || 'https://backend-production-daed.up.railway.app'

const VERDICT_STYLE = {
  PROCEED: { bg: '#f0fdf4', border: '#16a34a', text: '#15803d', label: '✅ PROCEED' },
  CAUTION: { bg: '#fffbeb', border: '#d97706', text: '#b45309', label: '⚠️ CAUTION' },
  SKIP:    { bg: '#fef2f2', border: '#dc2626', text: '#dc2626', label: '🚫 SKIP' },
}

const SIG_COLOR = { BULLISH:'#4ade80', NEUTRAL_POSITIVE:'#22d3ee', NEUTRAL:'#94a3b8', BEARISH:'#f87171', ERROR:'#64748b', 'N/A':'#64748b' }
const ENTRY_COLOR = { IDEAL:'#4ade80', CONSERVATIVE:'#22d3ee', WAIT:'#fbbf24', INVALIDATED:'#f87171', OVERBOUGHT:'#f87171', ERROR:'#64748b', 'N/A':'#64748b' }
const DIV_COLOR = { CLEAR:'#4ade80', BULLISH_DIV:'#86efac', HIDDEN_BULL:'#22d3ee', BEARISH_WARN:'#f87171', HIDDEN_BEAR:'#fb923c' }

function Row({ label, value, color }) {
  return (
    <div style={{ display:'flex', justifyContent:'space-between', padding:'4px 0', borderBottom:'1px solid #1e293b' }}>
      <span style={{ fontSize:11, color:'#475569' }}>{label}</span>
      <span style={{ fontSize:11, fontFamily:'monospace', color: color || '#e2e8f0' }}>{value}</span>
    </div>
  )
}

function Sparkline({ history }) {
  if (!history?.length) return null
  const max = Math.max(...history.map(Math.abs), 1)
  return (
    <div style={{ display:'flex', alignItems:'flex-end', gap:2, height:24, marginTop:4 }}>
      {history.map((v, i) => (
        <div key={i} style={{ flex:1, display:'flex', flexDirection:'column', justifyContent:'flex-end' }}>
          <div style={{
            background: v > 0 ? '#16a34a' : '#dc2626',
            borderRadius:2,
            height: `${Math.max(Math.round(Math.abs(v)/max*100), 8)}%`,
            opacity: 0.8
          }} />
        </div>
      ))}
    </div>
  )
}

function PriceLadder({ kama }) {
  if (!kama?.current_price) return null
  const { lower3, lower2, lower1, basis, upper1, upper3, current_price } = kama
  const levels = [
    { label:'Upper3', price: upper3, bg:'#fee2e2' },
    { label:'Upper1', price: upper1, bg:'#fecaca' },
    { label:'Basis',  price: basis,  bg:'#f1f5f9' },
    { label:'▶ Harga', price: current_price, bg:'#bfdbfe', bold:true },
    { label:'L1 ✓',  price: lower1, bg:'#dcfce7' },
    { label:'L2',    price: lower2, bg:'#bbf7d0' },
    { label:'L3 ✗',  price: lower3, bg:'#fee2e2' },
  ].sort((a,b) => b.price - a.price)

  return (
    <div style={{ marginTop:6, display:'flex', flexDirection:'column', gap:1 }}>
      {levels.map(({ label, price, bg, bold }) => (
        <div key={label} style={{ display:'flex', justifyContent:'space-between', padding:'2px 6px', borderRadius:3, background:bg }}>
          <span style={{ fontSize:10, color: bold ? '#1e40af' : '#374151', fontWeight: bold ? 700 : 400 }}>{label}</span>
          <span style={{ fontSize:10, fontFamily:'monospace', color: bold ? '#1e40af' : '#111827', fontWeight: bold ? 700 : 400 }}>
            {price?.toLocaleString('id-ID')}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function EnrichmentPanel({ ticker }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!ticker) return
    let cancelled = false
    setLoading(true); setData(null); setError(null)
    fetch(`${BACKEND}/api/enrich/${ticker}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch(e => { if (!cancelled) { setError(e.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [ticker])

  const box = { background:'#ffffff', border:'1px solid #e2e8f0', borderRadius:8, padding:12, marginBottom:8 }
  const sectionTitle = { fontSize:10, fontWeight:700, letterSpacing:2, textTransform:'uppercase', color:'#475569', marginBottom:6 }

  if (!ticker) return null

  if (loading) return (
    <div style={{ ...box, textAlign:'center', padding:24 }}>
      <div style={{ color:'#475569', fontSize:12 }}>⚡ Loading enrichment...</div>
    </div>
  )

  if (error || !data) return (
    <div style={{ ...box }}>
      <div style={{ fontSize:10, color:'#475569' }}>⚡ Enrichment unavailable</div>
    </div>
  )

  const { smart_mfi: mfi, kama_bands: kama, lele_exhaustion: lele, divergence: div, summary, bandar_context: ctx } = data
  const vs = VERDICT_STYLE[summary?.verdict] || VERDICT_STYLE.CAUTION

  return (
    <div>
      {/* Header */}
      <div style={{ ...box }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
          <span style={{ fontSize:11, fontWeight:700, letterSpacing:2, color:'#475569', textTransform:'uppercase' }}>⚡ Enrichment Layer</span>
          <span style={{ fontSize:10, fontFamily:'monospace', color:'#1e293b' }}>{ticker}</span>
        </div>

        {/* Bandar context badges */}
        <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:8 }}>
          <span style={{ padding:'2px 8px', borderRadius:4, background:'#f8fafc', fontSize:10, fontFamily:'monospace', color:'#fbbf24' }}>
            Score: {ctx?.bandar_score}
          </span>
          <span style={{ padding:'2px 8px', borderRadius:4, background:'#f8fafc', fontSize:10, fontFamily:'monospace', color:'#374151' }}>
            {ctx?.signal_tier}
          </span>
          {ctx?.phase_2b_active && (
            <span style={{ padding:'2px 8px', borderRadius:4, background:'#052e16', fontSize:10, fontFamily:'monospace', color:'#4ade80' }}>
              2B AKTIF
            </span>
          )}
        </div>

        {/* Verdict */}
        <div style={{ border:`1px solid ${vs.border}`, background:vs.bg, borderRadius:6, padding:'8px 12px' }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <span style={{ fontSize:14, fontWeight:900, color:vs.text }}>{vs.label}</span>
            <span style={{ fontSize:10, fontFamily:'monospace', color:'#374151' }}>{summary?.confidence}</span>
          </div>
          <div style={{ display:'flex', gap:12, marginTop:4, fontSize:10, color:'#475569' }}>
            <span>🟢 {summary?.bullish_count}/4 bullish</span>
            <span>🔴 {summary?.warning_count} warning</span>
          </div>
          {summary?.entry_zone && (
            <div style={{ marginTop:4, fontSize:10, fontFamily:'monospace', color:'#4ade80' }}>
              Entry: {summary.entry_zone}
            </div>
          )}
          {summary?.rag_insight && (
            <div style={{ marginTop:6, padding:'4px 8px', background:'#ffffff', borderRadius:4, borderLeft:'2px solid #0369a1', fontSize:10, color:'#374151', fontStyle:'italic' }}>
              📚 {summary.rag_insight}
            </div>
          )}
        </div>
      </div>

      {/* Smart MFI */}
      <div style={{ ...box }}>
        <div style={sectionTitle}>💧 Smart MFI</div>
        <Row label="Signal" value={mfi?.signal} color={SIG_COLOR[mfi?.signal]} />
        <Row label="Value" value={`${mfi?.value > 0 ? '+' : ''}${mfi?.value}`} color={mfi?.value > 0 ? '#4ade80' : '#f87171'} />
        <Row label="Above Threshold" value={mfi?.above_thresh ? 'YA' : 'TIDAK'} color={mfi?.above_thresh ? '#4ade80' : '#64748b'} />
        <Sparkline history={mfi?.mfi_history} />
        <div style={{ fontSize:10, color:'#475569', marginTop:6, fontStyle:'italic', lineHeight:1.4 }}>{mfi?.interpretation}</div>
      </div>

      {/* KAMA Bands */}
      <div style={{ ...box }}>
        <div style={sectionTitle}>📐 KAMA Bands</div>
        <Row label="Entry Signal" value={kama?.entry_signal} color={ENTRY_COLOR[kama?.entry_signal]} />
        <Row label="Zone" value={kama?.price_zone} />
        <Row label="Band Width" value={`${kama?.band_width_pct}%`} />
        <PriceLadder kama={kama} />
        <div style={{ fontSize:10, color:'#475569', marginTop:6, fontStyle:'italic', lineHeight:1.4 }}>{kama?.interpretation}</div>
      </div>

      {/* Lele Exhaustion */}
      <div style={{ ...box }}>
        <div style={sectionTitle}>🔋 Lele Exhaustion</div>
        <Row label="Status" value={lele?.detected ? `TERDETEKSI (${lele?.severity})` : 'TIDAK'} color={lele?.detected ? '#f87171' : '#4ade80'} />
        <Row label="Momentum Count" value={lele?.count} />
        <Row label="TP Strategy" value={lele?.tp_signal} color={lele?.tp_signal === 'TAKE_PARTIAL' ? '#fbbf24' : lele?.tp_signal === 'HOLD' ? '#4ade80' : '#64748b'} />
        <div style={{ fontSize:10, color:'#475569', marginTop:6, fontStyle:'italic', lineHeight:1.4 }}>{lele?.interpretation}</div>
      </div>

      {/* Divergence */}
      <div style={{ ...box }}>
        <div style={sectionTitle}>〰️ Divergence</div>
        <Row label="State" value={div?.state} color={DIV_COLOR[div?.state]} />
        {div?.div_type && <Row label="Type" value={div?.div_type} />}
        {div?.bars_ago > 0 && <Row label="Bars Ago" value={`${div?.bars_ago} bar lalu`} />}
        <Row label="SL Action" value={div?.sl_action} color={div?.sl_action === 'SKIP_ENTRY' ? '#f87171' : div?.sl_action === 'TIGHTEN' ? '#fbbf24' : '#4ade80'} />
        <Row label="Oscillator" value={`${div?.oscillator_val > 0 ? '+' : ''}${div?.oscillator_val}`} color={div?.oscillator_val > 0 ? '#4ade80' : '#f87171'} />
        <div style={{ fontSize:10, color:'#475569', marginTop:6, fontStyle:'italic', lineHeight:1.4 }}>{div?.interpretation}</div>
      </div>

      {/* ── PHASE 2 ENRICHMENT ── */}
      {data?.phase2 && (
        <div>
          {/* Phase 2 Header */}
          <div style={{ fontSize:10, fontWeight:700, color:'#7c3aed', fontFamily:'monospace',
            letterSpacing:'0.1em', marginBottom:6, marginTop:4,
            borderTop:'1px solid #334155', paddingTop:8 }}>
            ⚡ PHASE 2 ENRICHMENT
          </div>

          {/* Phase 2 Verdict Banner */}
          <div style={{
            padding:'6px 10px', borderRadius:6, marginBottom:8,
            background: data.phase2.phase2_verdict === 'STRONG_BUY' ? '#052e16' :
                        data.phase2.phase2_verdict === 'BUY' ? '#052e16' :
                        data.phase2.phase2_verdict === 'AVOID' ? '#450a0a' :
                        data.phase2.phase2_verdict === 'REDUCE' ? '#431407' : '#1e293b',
            border: `1px solid ${
                        data.phase2.phase2_verdict === 'STRONG_BUY' ? '#16a34a' :
                        data.phase2.phase2_verdict === 'BUY' ? '#4ade80' :
                        data.phase2.phase2_verdict === 'AVOID' ? '#ef4444' :
                        data.phase2.phase2_verdict === 'REDUCE' ? '#f97316' : '#334155'}`,
          }}>
            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
              <span style={{ fontSize:12, fontWeight:700, fontFamily:'monospace',
                color: data.phase2.phase2_verdict === 'STRONG_BUY' ? '#4ade80' :
                       data.phase2.phase2_verdict === 'BUY' ? '#4ade80' :
                       data.phase2.phase2_verdict === 'AVOID' ? '#f87171' :
                       data.phase2.phase2_verdict === 'REDUCE' ? '#fb923c' : '#94a3b8'
              }}>
                {data.phase2.phase2_verdict === 'STRONG_BUY' ? '🟢 STRONG BUY' :
                 data.phase2.phase2_verdict === 'BUY' ? '🟢 BUY' :
                 data.phase2.phase2_verdict === 'AVOID' ? '🔴 AVOID' :
                 data.phase2.phase2_verdict === 'REDUCE' ? '🟠 REDUCE' : '🟡 HOLD'}
              </span>
              <span style={{ fontSize:10, color:'#94a3b8', fontFamily:'monospace' }}>
                {data.phase2.phase2_confidence?.toFixed(0)}% confidence
              </span>
            </div>
            <div style={{ fontSize:9, color:'#64748b', fontFamily:'monospace', marginTop:3 }}>
              {data.phase2.phase2_summary}
            </div>
          </div>

          {/* Wyckoff Card */}
          <div style={{ ...box, borderLeft:'2px solid #7c3aed' }}>
            <div style={sectionTitle}>🌊 Wyckoff Phase</div>
            <Row label="Phase" value={data.phase2.wyckoff?.phase}
              color={data.phase2.wyckoff?.phase === 'ACCUMULATION' ? '#4ade80' :
                     data.phase2.wyckoff?.phase === 'MARKUP' ? '#4ade80' :
                     data.phase2.wyckoff?.phase === 'DISTRIBUTION' ? '#f87171' :
                     data.phase2.wyckoff?.phase === 'MARKDOWN' ? '#f87171' :
                     data.phase2.wyckoff?.phase === 'REACCUMULATION' ? '#fbbf24' : '#94a3b8'} />
            <Row label="Event" value={data.phase2.wyckoff?.sub_event} />
            <Row label="Implication" value={data.phase2.wyckoff?.implication}
              color={data.phase2.wyckoff?.implication === 'BUY' ? '#4ade80' :
                     data.phase2.wyckoff?.implication === 'EXIT' ? '#f87171' :
                     data.phase2.wyckoff?.implication === 'REDUCE' ? '#fb923c' : '#94a3b8'} />
            <Row label="Confidence" value={`${data.phase2.wyckoff?.confidence?.toFixed(0)}%`} />
            <Row label="Support" value={`Rp ${data.phase2.wyckoff?.support_level?.toLocaleString('id-ID')}`} />
            <Row label="Resistance" value={`Rp ${data.phase2.wyckoff?.resistance_level?.toLocaleString('id-ID')}`} />
            {data.phase2.wyckoff?.is_spring && (
              <div style={{ fontSize:10, color:'#4ade80', marginTop:4, fontWeight:700 }}>✅ SPRING DETECTED</div>
            )}
            {data.phase2.wyckoff?.is_sos && (
              <div style={{ fontSize:10, color:'#4ade80', marginTop:4, fontWeight:700 }}>✅ SIGN OF STRENGTH</div>
            )}
            {data.phase2.wyckoff?.is_upthrust && (
              <div style={{ fontSize:10, color:'#f87171', marginTop:4, fontWeight:700 }}>⚠️ UPTHRUST DETECTED</div>
            )}
            <div style={{ fontSize:10, color:'#475569', marginTop:6, fontStyle:'italic' }}>
              {data.phase2.wyckoff?.phase_label}
            </div>
          </div>

          {/* Weinstein Card */}
          <div style={{ ...box, borderLeft:'2px solid #0ea5e9' }}>
            <div style={sectionTitle}>📊 Weinstein Stage</div>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:6 }}>
              <div style={{
                width:36, height:36, borderRadius:'50%', display:'flex',
                alignItems:'center', justifyContent:'center', fontWeight:700,
                fontSize:16, fontFamily:'monospace',
                background: data.phase2.weinstein?.stage === 2 ? '#052e16' :
                            data.phase2.weinstein?.stage === 4 ? '#450a0a' :
                            data.phase2.weinstein?.stage === 1 ? '#1e293b' : '#431407',
                border: `2px solid ${
                            data.phase2.weinstein?.stage === 2 ? '#4ade80' :
                            data.phase2.weinstein?.stage === 4 ? '#f87171' :
                            data.phase2.weinstein?.stage === 1 ? '#64748b' : '#f97316'}`,
                color: data.phase2.weinstein?.stage === 2 ? '#4ade80' :
                       data.phase2.weinstein?.stage === 4 ? '#f87171' :
                       data.phase2.weinstein?.stage === 1 ? '#94a3b8' : '#fb923c',
              }}>
                {data.phase2.weinstein?.stage}
              </div>
              <div>
                <div style={{ fontSize:11, fontWeight:700, fontFamily:'monospace',
                  color: data.phase2.weinstein?.stage === 2 ? '#4ade80' :
                         data.phase2.weinstein?.stage === 4 ? '#f87171' :
                         data.phase2.weinstein?.stage === 1 ? '#94a3b8' : '#fb923c' }}>
                  {data.phase2.weinstein?.stage_name}
                </div>
                <div style={{ fontSize:9, color:'#64748b', fontFamily:'monospace' }}>
                  {data.phase2.weinstein?.weeks_in_stage} candle di stage ini
                </div>
              </div>
            </div>
            <Row label="MA30" value={`Rp ${data.phase2.weinstein?.ma30?.toLocaleString('id-ID')}`} />
            <Row label="Price vs MA" value={data.phase2.weinstein?.price_vs_ma}
              color={data.phase2.weinstein?.price_vs_ma === 'ABOVE' ? '#4ade80' :
                     data.phase2.weinstein?.price_vs_ma === 'BELOW' ? '#f87171' : '#fbbf24'} />
            <Row label="MA Slope" value={data.phase2.weinstein?.ma_slope}
              color={data.phase2.weinstein?.ma_slope === 'RISING' ? '#4ade80' :
                     data.phase2.weinstein?.ma_slope === 'FALLING' ? '#f87171' : '#fbbf24'} />
            <Row label="Vol Confirm" value={data.phase2.weinstein?.volume_confirmation ? 'YA ✅' : 'TIDAK'}
              color={data.phase2.weinstein?.volume_confirmation ? '#4ade80' : '#64748b'} />
            {data.phase2.weinstein?.breakout_detected && (
              <div style={{ fontSize:10, color:'#4ade80', marginTop:4, fontWeight:700 }}>🚀 BREAKOUT DETECTED!</div>
            )}
            {data.phase2.weinstein?.breakdown_detected && (
              <div style={{ fontSize:10, color:'#f87171', marginTop:4, fontWeight:700 }}>⚠️ BREAKDOWN DETECTED!</div>
            )}
          </div>

          {/* VSA Card */}
          <div style={{ ...box, borderLeft:'2px solid #f59e0b' }}>
            <div style={sectionTitle}>📈 VSA Signal</div>
            <Row label="Signal" value={data.phase2.vsa?.signal}
              color={['STOPPING_VOLUME','NO_SUPPLY','TEST'].includes(data.phase2.vsa?.signal) ? '#4ade80' :
                     ['UP_THRUST','NO_DEMAND'].includes(data.phase2.vsa?.signal) ? '#f87171' :
                     data.phase2.vsa?.signal === 'EFFORT_VS_RESULT' ? '#fbbf24' : '#94a3b8'} />
            <Row label="Background" value={data.phase2.vsa?.background}
              color={data.phase2.vsa?.background === 'BULLISH' ? '#4ade80' :
                     data.phase2.vsa?.background === 'BEARISH' ? '#f87171' : '#94a3b8'} />
            <Row label="Strength" value={data.phase2.vsa?.strength} />
            <Row label="Vol Ratio" value={`${data.phase2.vsa?.vol_ratio?.toFixed(2)}x`}
              color={data.phase2.vsa?.vol_ratio >= 1.5 ? '#4ade80' :
                     data.phase2.vsa?.vol_ratio < 0.6 ? '#f87171' : '#94a3b8'} />
            <Row label="Spread Ratio" value={`${data.phase2.vsa?.spread_ratio?.toFixed(2)}x`} />
            {data.phase2.vsa?.tradeable && (
              <div style={{ fontSize:10, color:'#4ade80', marginTop:4, fontWeight:700 }}>✅ TRADEABLE SIGNAL</div>
            )}
            {data.phase2.vsa?.description && (
              <div style={{ fontSize:10, color:'#475569', marginTop:6, fontStyle:'italic', lineHeight:1.4 }}>
                {data.phase2.vsa.description}
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{ fontSize:9, color:'#1e293b', fontFamily:'monospace', textAlign:'right' }}>
        {data?.timestamp ? new Date(data.timestamp).toLocaleTimeString('id-ID') : ''}
      </div>
    </div>
  )
}
