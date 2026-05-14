import React, { useState, useEffect, useRef } from 'react'
import { BarChart2, ChevronRight, RefreshCw, ArrowRight } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { analyzeStock } from '../../utils/api'
import { ScoreGauge, ScoreBar, SignalBadge, LoadingSpinner, ErrorBox, ConfidenceBar } from '../shared/ScoreComponents'
import clsx from 'clsx'

const MODES = ['SWING','DAYTRADING','SCALPING']
const GROUPS = [
  {key:'group1',label:'Market Structure',color:'#0EA5FF'},
  {key:'group2',label:'Smart Money',color:'#00FF88'},
  {key:'group3',label:'Execution Layer',color:'#FFB800'},
  {key:'group4',label:'Decision Control',color:'#8B5CF6'},
]

export default function AnalyticPage() {
  const { analyticTicker, setAnalyticTicker, analyticMode, setAnalyticMode,
    analyticResult, setAnalyticResult, analyticLoading, setAnalyticLoading,
    analyticError, setAnalyticError, sendToMonitoring } = useStore()
  const [activeGroup, setActiveGroup] = useState('group1')
  const [marketCtx, setMarketCtx] = useState(null)
  const lastAutoAnalyzeRef = useRef('')

  const handleAnalyze = async () => {
    if(!analyticTicker.trim()) return
    setAnalyticLoading(true); setAnalyticError(null); setAnalyticResult(null); setMarketCtx(null)
    try {
      const res = await analyzeStock(analyticTicker.toUpperCase().trim(), analyticMode)
      setAnalyticResult(res)
      // Fetch market context 4 box
      try {
        const ctx = await fetch(`${import.meta.env.VITE_BACKEND_URL || 'https://backend-production-daed.up.railway.app'}/api/analytic/market-context/${analyticTicker.toUpperCase().trim()}`)
        const ctxData = await ctx.json()
        setMarketCtx(ctxData)
      } catch(e) { console.log('market ctx error:', e) }
    } catch(e) {
      setAnalyticError(e?.response?.data?.detail || e.message || 'Gagal menganalisis')
    } finally { setAnalyticLoading(false) }
  }

  useEffect(() => {
    const ticker = analyticTicker?.trim()?.toUpperCase()
    if (!ticker) return
    if (lastAutoAnalyzeRef.current === ticker) return
    lastAutoAnalyzeRef.current = ticker
    handleAnalyze()
  }, [analyticTicker])

  const r = analyticResult
  // Backend returns engines as array [{engine, score, signal, ...}]
  // Convert to object {engineName: {score, signal, ...}} for UI
  const enginesRaw = r?.engines?.engines || r?.engine_scores || []
  const engines = Array.isArray(enginesRaw)
    ? Object.fromEntries(enginesRaw.map(e => [e.engine, e]))
    : enginesRaw

  const engineList = Array.isArray(enginesRaw) ? enginesRaw : Object.entries(enginesRaw || {}).map(([engine, data]) => ({ engine, ...(typeof data === 'object' ? data : { score: data }) }))
  const bullishEngines = engineList.filter(e => String(e.signal || '').toLowerCase().includes('bullish') || Number(e.score || 0) >= 70)
  const bearishEngines = engineList.filter(e => String(e.signal || '').toLowerCase().includes('bearish') || Number(e.score || 0) <= 40)
  const neutralEngines = engineList.filter(e => !bullishEngines.includes(e) && !bearishEngines.includes(e))
  const topBullishEngines = [...bullishEngines].sort((a,b) => Number(b.score || 0) - Number(a.score || 0)).slice(0, 6)
  const topRiskEngines = [...bearishEngines, ...neutralEngines.filter(e => Number(e.score || 0) < 55)]
    .sort((a,b) => Number(a.score || 0) - Number(b.score || 0))
    .slice(0, 6)
  const groupScores = r?.engines?.group_scores || {}
  const confidenceDrivers = [
    ['Market Structure', groupScores.market_structure],
    ['Smart Money', groupScores.smart_money],
    ['Execution', groupScores.execution],
    ['Decision Control', groupScores.decision],
  ].filter(([,v]) => v !== undefined && v !== null)

  const decisionTree = {
    whyBuy: [
      Number(r?.score || r?.composite_score || 0) >= 60 && `Composite score valid di atas 60`,
      bullishEngines.length >= 2 && `${bullishEngines.length} engine memberi konfirmasi bullish`,
      Number(groupScores.market_structure || 0) >= 60 && `Market structure mendukung`,
      Number(groupScores.smart_money || 0) >= 60 && `Smart money flow mendukung`,
      r?.signal && `Signal utama: ${String(r.signal).toUpperCase()}`,
    ].filter(Boolean),
    whyNotFullSize: [
      Number(r?.rr_ratio || r?.risk_reward || 0) > 0 && Number(r?.rr_ratio || r?.risk_reward || 0) < 2 && `Risk reward belum ideal untuk full size`,
      topRiskEngines.length > 0 && `${topRiskEngines.length} engine masih lemah / berisiko`,
      Number(groupScores.execution || 0) < 60 && `Execution layer belum cukup kuat`,
      Number(groupScores.decision || 0) < 60 && `Decision control masih perlu konfirmasi`,
    ].filter(Boolean),
  }

  const groupEngineKeys = {
    group1:['price_action','trend','support','volume','relative_vol','multi_time','order_block','break_order','fair_value','liquidity'],
    group2:['bandarmology','inventory','flow','intraday','foreign'],
    group3:['quant','orderbook','relative_strength','fibonacci','pattern','sector','macro_market','macro_econ','geopolit','news','insider','probability','trading_setup'],
    group4:['risk','scorecard','ai_conf','rotation','alert','liquidity_qual'],
  }

  const getGroupEngines = (grp) =>
    Object.entries(engines).filter(([k]) =>
      groupEngineKeys[grp]?.some(gk => k.toLowerCase().includes(gk.substring(0,6))))

  // Hitung group score dari engines
  const calcGroupScore = (grp) => {
    const grpEngines = getGroupEngines(grp)
    if (!grpEngines.length) return 0
    const avg = grpEngines.reduce((sum,[,v]) => sum + (typeof v==='object'?(v.score??50):(v??50)), 0) / grpEngines.length
    return Math.round(avg)
  }

  return (
    <div className="p-4 lg:p-6 max-w-7xl mx-auto animate-fade-in">
      <div className="mb-6">
        <h1 className="font-display font-bold text-2xl text-white tracking-wide">ANALYTIC TOOL</h1>
        <p className="text-slate-500 text-sm font-mono mt-0.5">Deep analysis 34 engines · Multi-timeframe · AI trading decision</p>
      </div>

      <div className="card p-4 mb-5">
        <div className="flex flex-wrap gap-3 items-center">
          <input type="text" value={analyticTicker}
            onChange={(e) => setAnalyticTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key==='Enter' && handleAnalyze()}
            placeholder="TICKER (e.g. BBCA)" maxLength={10}
            className="w-40 bg-white border border-slate-300 rounded px-3 py-2 font-mono text-sm text-slate-900 placeholder-slate-400 focus:border-accent-green focus:outline-none uppercase"/>
          <div className="flex gap-1.5">
            {MODES.map(m => (
              <button key={m} onClick={() => setAnalyticMode(m)}
                className={clsx('px-3 py-2 rounded border text-xs font-mono font-semibold uppercase tracking-wider transition-all duration-200',
                  analyticMode===m?'border-accent-green bg-accent-green/10 text-accent-green':'border-border-dim text-slate-500 hover:text-slate-300')}>
                {m}
              </button>
            ))}
          </div>
          <button onClick={handleAnalyze} disabled={analyticLoading||!analyticTicker.trim()}
            className="btn-primary flex items-center gap-2 disabled:opacity-50">
            {analyticLoading?<RefreshCw className="w-4 h-4 animate-spin"/>:<BarChart2 className="w-4 h-4"/>}
            {analyticLoading?'Analyzing...':'Analyze'}
          </button>
        </div>
      </div>

      {/* 4 BOX MARKET CONTEXT */}
      {marketCtx && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          {/* Box 1: Price */}
          <div className="card p-3">
            <div className="label-xs mb-2">📈 HARGA</div>
            <div className="font-mono font-bold text-lg text-slate-900">Rp {marketCtx.price?.last?.toLocaleString('id-ID')}</div>
            <div className={`font-mono text-sm font-semibold ${marketCtx.price?.change >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {marketCtx.price?.change >= 0 ? '+' : ''}{marketCtx.price?.change?.toLocaleString('id-ID')} ({marketCtx.price?.change_pct}%)
            </div>
            <div className="text-xs text-slate-500 mt-1">
              H: {marketCtx.price?.high?.toLocaleString('id-ID')} | L: {marketCtx.price?.low?.toLocaleString('id-ID')}
            </div>
            <div className="text-xs text-slate-500">Open: {marketCtx.price?.open?.toLocaleString('id-ID')}</div>
          </div>
          {/* Box 2: Volume */}
          <div className="card p-3">
            <div className="label-xs mb-2">📊 VOLUME</div>
            <div className="font-mono font-bold text-lg text-slate-900">{(marketCtx.volume?.last_volume/1000000).toFixed(1)}M</div>
            <div className={`font-mono text-sm font-semibold ${
              marketCtx.volume?.signal === 'HIGH' ? 'text-green-600' :
              marketCtx.volume?.signal === 'MEDIUM' ? 'text-amber-600' : 'text-slate-500'}`}>
              RVOL: {marketCtx.volume?.rvol}x — {marketCtx.volume?.signal}
            </div>
            <div className="text-xs text-slate-500 mt-1">Avg 20d: {(marketCtx.volume?.avg_volume_20/1000000).toFixed(1)}M</div>
            <div className="text-xs text-slate-500">Trend: {marketCtx.volume?.vol_trend}</div>
          </div>
          {/* Box 3: Company */}
          <div className="card p-3">
            <div className="label-xs mb-2">🏢 PERUSAHAAN</div>
            <div className="font-mono font-bold text-sm text-slate-900 truncate">{marketCtx.company?.name}</div>
            <div className="text-xs text-slate-600 mt-1">{marketCtx.company?.sector}</div>
            <div className="text-xs text-slate-500">{marketCtx.company?.subsector}</div>
            <div className="text-xs text-slate-400 mt-1 truncate">{marketCtx.company?.activity}</div>
          </div>
          {/* Box 4: Technical */}
          <div className="card p-3">
            <div className="label-xs mb-2">📉 TECHNICAL</div>
            <div className={`font-mono font-bold text-sm ${
              marketCtx.technical?.trend === 'UPTREND' ? 'text-green-600' :
              marketCtx.technical?.trend === 'DOWNTREND' ? 'text-red-600' : 'text-amber-600'}`}>
              {marketCtx.technical?.trend}
            </div>
            <div className="text-xs text-slate-500 mt-1">52w High: {marketCtx.technical?.['52w_high']?.toLocaleString('id-ID')}</div>
            <div className="text-xs text-slate-500">52w Low: {marketCtx.technical?.['52w_low']?.toLocaleString('id-ID')}</div>
            <div className="text-xs text-slate-500">MA20: {marketCtx.technical?.ma20?.toLocaleString('id-ID')}</div>
            <div className="text-xs text-slate-500">MA50: {marketCtx.technical?.ma50?.toLocaleString('id-ID')}</div>
            <div className="text-xs mt-1">
              <span className={`font-semibold ${marketCtx.technical?.above_ma20 ? 'text-green-600' : 'text-red-500'}`}>
                {marketCtx.technical?.above_ma20 ? '✅' : '❌'} MA20
              </span>
              {' '}
              <span className={`font-semibold ${marketCtx.technical?.above_ma50 ? 'text-green-600' : 'text-red-500'}`}>
                {marketCtx.technical?.above_ma50 ? '✅' : '❌'} MA50
              </span>
            </div>
          </div>
        </div>
      )}
      {analyticLoading && <LoadingSpinner message={`Menganalisis ${analyticTicker}...`}/>}
      {analyticError && !analyticLoading && <ErrorBox message={analyticError} onRetry={handleAnalyze}/>}

      {!analyticLoading && r && (
        <div className="space-y-4 animate-slide-up">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="card p-5 flex flex-col items-center justify-center gap-3">
              <ScoreGauge score={r.composite_score||r.score||0} size={100}/>
              <div className="text-center">
                <p className="font-display font-bold text-xl text-white">{r.ticker||analyticTicker}</p>
                <p className="font-mono text-xs text-slate-500 mt-0.5">{r.mode||analyticMode} MODE</p>
              </div>
              {r.signal && <SignalBadge signal={r.signal}/>}
              {r.market_regime && (
                <div className={`mt-1 rounded-xl border px-3 py-2 text-center ${
                  r.market_regime.includes('BULL') ? 'border-accent-green/30 bg-accent-green/10' :
                  r.market_regime.includes('BEAR') ? 'border-accent-red/30 bg-accent-red/10' :
                  'border-slate-600/30 bg-slate-600/10'
                }`}>
                  <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">Market Regime</p>
                  <p className={`font-display text-sm font-bold ${
                    r.market_regime.includes('BULL') ? 'text-accent-green' :
                    r.market_regime.includes('BEAR') ? 'text-accent-red' :
                    'text-slate-400'
                  }`}>{r.market_regime}</p>
                </div>
              )}

              {r.setup_type && (
                <div className="mt-1 rounded-xl border border-accent-blue/30 bg-accent-blue/10 px-3 py-2 text-center">
                  <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                    Setup Type
                  </p>
                  <p className="font-display text-sm font-bold uppercase text-accent-blue">
                    {String(r.setup_type).replace(/_/g, ' ')}
                  </p>
                  {r.setup_quality && (
                    <p className="mt-1 font-mono text-xs text-accent-gold">
                      Quality: {r.setup_quality}
                    </p>
                  )}
                </div>
              )}
              {/* WIN PROBABILITY — ML Engine */}
              {r.win_probability && (
                <div className="w-full rounded-xl border px-3 py-2 text-center" style={{borderColor: r.win_probability.color+'40', background: r.win_probability.color+'10'}}>
                  <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">Win Probability</p>
                  <p className="font-display text-2xl font-bold mt-1" style={{color: r.win_probability.color}}>
                    {r.win_probability.probability}%
                  </p>
                  <div className="flex items-center justify-center gap-2 mt-1">
                    <span className="font-mono text-xs font-bold px-2 py-0.5 rounded" style={{background: r.win_probability.color+'30', color: r.win_probability.color}}>
                      Grade {r.win_probability.grade}
                    </span>
                    <span className="font-mono text-[10px] text-slate-500">{r.win_probability.grade_label}</span>
                  </div>
                  <p className="font-mono text-[9px] text-slate-600 mt-1">{r.win_probability.method}</p>
                </div>
              )}
              <div className="w-full">
                <p className="label-xs mb-1.5">AI Confidence</p>
                <ConfidenceBar value={r.confidence||r.ai_confidence||0}/>
              </div>
            </div>

            <div className="card p-5 space-y-3">
              <p className="label-xs">Trade Setup</p>
              {[
                ['Entry Price', r.entry, 'text-accent-green'],
                ['Stop Loss', r.stop_loss||r.sl, 'text-accent-red'],
                ['Take Profit 1', r.tp1, 'text-accent-gold'],
                ['Take Profit 2', r.tp2, 'text-accent-gold'],
                ['Take Profit 3', r.tp3, 'text-accent-gold'],
                ['Risk:Reward', r.risk_reward ? `1:${Number(r.risk_reward).toFixed(2)}` : null, 'text-accent-blue'],
              ].filter(([,v]) => v).map(([k,v,c]) => (
                <div key={k} className="flex justify-between items-center py-1.5 border-b border-border-dim last:border-0">
                  <span className="font-mono text-xs text-slate-500">{k}</span>
                  <span className={clsx('font-mono font-bold text-sm', c)}>
                    {typeof v==='number'?`Rp ${v.toLocaleString('id-ID')}`:v}
                  </span>
                </div>
              ))}
              <button onClick={() => sendToMonitoring({
                ticker:r.ticker||analyticTicker,
                entry_price:r.entry, stop_loss:r.stop_loss||r.sl,
                take_profit_1:r.tp1,
                take_profit_2:r.tp2, take_profit_3:r.tp3,
                mode:analyticMode,
                final_score:r.score||r.composite_score||50,
                market_regime:r.market_regime||'SIDEWAYS',
                engine_scores:r.engines?.engines||{},
                kb_context:r.rag_used?'rag_active':''
              })} className="btn-primary w-full flex items-center justify-center gap-2 mt-2">
                Monitor Posisi<ArrowRight className="w-4 h-4"/>
              </button>
            </div>
          </div>

          {r?.rag_used && (
            <div className="card p-4 border border-emerald-500/30 bg-emerald-500/10">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-display font-bold text-sm text-emerald-300">
                    RAG Knowledge Base Active
                  </p>
                  <p className="font-mono text-xs text-slate-400 mt-1">
                    {r.rag_context_count || 0} knowledge references injected into AI rationale
                  </p>
                </div>
                <span className="rounded-full bg-emerald-500/20 px-3 py-1 font-mono text-xs font-bold text-emerald-300">
                  ACTIVE
                </span>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {(r.rag_engines || []).map((eng) => (
                  <span
                    key={eng}
                    className="rounded-lg bg-slate-900/70 px-2 py-1 font-mono text-[11px] text-slate-300"
                  >
                    {eng}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="card p-5">
            <p className="label-xs mb-3">Engine Scores — 34 Engines</p>
            <div className="flex gap-2 mb-4 flex-wrap">
              {GROUPS.map(g => (
                <button key={g.key} onClick={() => setActiveGroup(g.key)}
                  className="px-3 py-1.5 rounded border text-xs font-mono font-semibold tracking-wider uppercase transition-all duration-200"
                  style={activeGroup===g.key?{borderColor:g.color,background:`${g.color}15`,color:g.color}:{borderColor:'#1E2D45',color:'#64748b'}}>
                  {g.label}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
              {getGroupEngines(activeGroup).map(([k,v]) => (
                <ScoreBar key={k}
                  label={k.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}
                  score={typeof v==='object'?(v.score??0):(v??0)}/>
              ))}
              {getGroupEngines(activeGroup).length===0 && (
                <div className="col-span-2 py-6 text-center">
                  <p className="font-mono text-xs text-slate-700">Jalankan analisis untuk melihat engine scores</p>
                </div>
              )}
            </div>
            <div className="mt-5 pt-4 border-t border-border-dim grid grid-cols-4 gap-3">
              {GROUPS.map(g => {
                const score = calcGroupScore(g.key)
                const pct = score
                return <div key={g.key} className="text-center">
                  <ScoreGauge score={score||0} size={56} label={g.label.split(' ')[0]}/>
                  <div className="font-mono text-xs font-bold mt-1" style={{color: score>=60?'#00FF88':score<=40?'#FF4444':'#FFB800'}}>{score}%</div>
                </div>
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

            <div className="card p-5">
              <p className="label-xs mb-3">🚀 Bullish Confirmation Engines</p>

              <div className="space-y-2">
                {topBullishEngines.map((e, idx) => (
                  <div key={idx} className="flex items-center justify-between border-b border-border-dim pb-2">
                    <div>
                      <div className="font-mono text-xs text-slate-900 font-bold">
                        {String(e.engine || '').replace(/Engine/g,'')}
                      </div>
                      <div className="text-[11px] text-green-600 uppercase">
                        {e.signal || 'bullish'}
                      </div>
                    </div>

                    <div className="text-green-600 font-mono font-bold">
                      {Number(e.score || 0).toFixed(1)}
                    </div>
                  </div>
                ))}

                {topBullishEngines.length === 0 && (
                  <div className="text-xs text-slate-500">
                    Tidak ada bullish confirmation kuat
                  </div>
                )}
              </div>
            </div>

            <div className="card p-5">
              <p className="label-xs mb-3">⚠️ Risk / Weak Engines</p>

              <div className="space-y-2">
                {topRiskEngines.map((e, idx) => (
                  <div key={idx} className="flex items-center justify-between border-b border-border-dim pb-2">
                    <div>
                      <div className="font-mono text-xs text-slate-900 font-bold">
                        {String(e.engine || '').replace(/Engine/g,'')}
                      </div>
                      <div className="text-[11px] text-red-500 uppercase">
                        {e.signal || 'weak'}
                      </div>
                    </div>

                    <div className="text-red-500 font-mono font-bold">
                      {Number(e.score || 0).toFixed(1)}
                    </div>
                  </div>
                ))}

                {topRiskEngines.length === 0 && (
                  <div className="text-xs text-slate-500">
                    Tidak ada major risk engine
                  </div>
                )}
              </div>
            </div>

          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

            <div className="card p-5">
              <p className="label-xs mb-4">✅ WHY BUY?</p>

              <div className="space-y-2">
                {decisionTree.whyBuy.map((x, idx) => (
                  <div
                    key={idx}
                    className="flex items-start gap-2 text-sm border-b border-border-dim pb-2"
                  >
                    <span className="text-green-500 font-bold">✔</span>
                    <span className="text-slate-900">{x}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card p-5">
              <p className="label-xs mb-4">⚠ WHY NOT FULL SIZE?</p>

              <div className="space-y-2">
                {decisionTree.whyNotFullSize.map((x, idx) => (
                  <div
                    key={idx}
                    className="flex items-start gap-2 text-sm border-b border-border-dim pb-2"
                  >
                    <span className="text-red-500 font-bold">⚠</span>
                    <span className="text-slate-900">{x}</span>
                  </div>
                ))}

                {decisionTree.whyNotFullSize.length === 0 && (
                  <div className="text-green-600 text-sm">
                    Tidak ada major warning
                  </div>
                )}
              </div>
            </div>

          </div>

          <div className="card p-5">
            <p className="label-xs mb-4">🧠 Institutional Confidence Breakdown</p>

            <div className="space-y-4">
              {confidenceDrivers.map(([name,val]) => (
                <div key={name}>
                  <div className="flex justify-between text-xs font-mono mb-1">
                    <span>{name}</span>
                    <span>{Number(val || 0).toFixed(1)}%</span>
                  </div>

                  <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, Number(val || 0))}%`,
                        background:
                          Number(val || 0) >= 70
                            ? '#22c55e'
                            : Number(val || 0) >= 50
                            ? '#f59e0b'
                            : '#ef4444'
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {r.rationale && (
            <div className="card p-5">
              <p className="label-xs mb-3">🤖 AI Trading Rationale</p>
              <div className="bg-bg-secondary rounded p-4 border border-border-dim">
              <div className="font-mono text-xs text-slate-900 leading-relaxed"
                dangerouslySetInnerHTML={{__html: r.rationale
                  .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                  .replace(/\*(.+?)\*/g, '<em>$1</em>')
                  .replace(/##\s(.+)/g, '<div class="font-bold text-sm text-slate-900 mt-2 mb-1">$1</div>')
                  .replace(/\n/g, '<br/>')
                }} />
              </div>
            </div>
          )}
        </div>
      )}

      {!analyticLoading && !analyticError && !r && (
        <div className="card p-12 text-center">
          <BarChart2 className="w-12 h-12 text-slate-700 mx-auto mb-4"/>
          <p className="font-display text-lg text-slate-500 mb-1">Masukkan ticker saham</p>
          <p className="font-mono text-sm text-slate-700">Ketik kode saham IDX dan pilih mode trading</p>
        </div>
      )}
    </div>
  )
}
