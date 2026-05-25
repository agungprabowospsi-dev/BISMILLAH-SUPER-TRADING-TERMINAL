import React, { useState, useEffect, useRef, lazy, Suspense } from 'react'
import { BarChart2, ChevronRight, RefreshCw, ArrowRight } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { analyzeStock } from '../../utils/api'
import { ScoreGauge, ScoreBar, SignalBadge, LoadingSpinner, ErrorBox, ConfidenceBar } from '../shared/ScoreComponents'
import clsx from 'clsx'
const EnrichmentPanel = lazy(() => import("./EnrichmentPanel"))

const MODES = ['SWING','INTRADAY','SCALPING']
const GROUPS = [
  {key:'group1',label:'Market Structure',color:'#0EA5FF'},
  {key:'group2',label:'Smart Money',color:'#00FF88'},
  {key:'group3',label:'Execution Layer',color:'#FFB800'},
  {key:'group4',label:'Decision Control',color:'#8B5CF6'},
]

const fmtPrice = (value) => {
  const n = Number(value || 0)
  return n > 0 ? `Rp ${n.toLocaleString('id-ID')}` : '-'
}

const fmtPercent = (value, digits = 1) => {
  const n = Number(value)
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : '-'
}

const formatLabel = (value) => String(value || '-').replace(/_/g, ' ').toUpperCase()

const normalizeEngineScoresForMonitoring = (engines) => {
  if (Array.isArray(engines)) {
    return Object.fromEntries(
      engines.map((e) => [e.engine || e.name || 'unknown', Number(e.score || 0)])
    )
  }
  if (engines && typeof engines === 'object') return engines
  return {}
}

export default function AnalyticPage() {
  const { analyticTicker, setAnalyticTicker, analyticMode, setAnalyticMode, screenerSelectedStock,
    analyticResult, setAnalyticResult, analyticLoading, setAnalyticLoading,
    analyticError, setAnalyticError, sendToMonitoring } = useStore()
  const [activeGroup, setActiveGroup] = useState('group1')
  const [marketCtx, setMarketCtx] = useState(null)
  const lastAutoAnalyzeRef = useRef('')

  const handleAnalyze = async () => {
    if(!analyticTicker.trim()) return
    setAnalyticLoading(true); setAnalyticError(null); setAnalyticResult(null); setMarketCtx(null)
    try {
      // SA-6: Build screener_context jika ada
      let screenerCtx = null
      if (screenerSelectedStock) {
        const s = screenerSelectedStock
        const sc = s.final_score || s.score || 0
        screenerCtx = {
          grade: sc >= 75 ? 'A' : sc >= 55 ? 'B' : sc >= 45 ? 'C' : 'D',
          score: sc,
          wyckoff_phase: s.bandarmology?.wyckoff_phase || s.wyckoff_phase || '',
          weinstein_stage: s.bandarmology?.weinstein_stage || s.weinstein_stage || 0,
          vsa_signal: s.bandarmology?.vsa_signal || s.vsa_signal || '',
          phase: s.phase || s.bandarmology?.phase || '',
          akumulasi_score: s.akumulasi_score || 50.0,
          foreign_signal: s.foreign_flow?.signal || '',
          bandarmology_score: s.bandarmology_composite || s.bandarmology?.score || 0,
          signal: s.signal || '',
          rvol: s.rvol || s.volume_ratio || 0,
          change_pct: s.change_pct || 0,
          watchlist_only: Boolean(s.watchlist_only),
          adaptive_prefilter_used: Boolean(s.adaptive_prefilter_used),
          watchlist_fallback_used: Boolean(s.watchlist_fallback_used),
          opportunity_lane: s._opportunity_lane || s.opportunity_lane || '',
          top_gainer_opportunity: s.top_gainer_opportunity || {},
        }
      }
      const res = await analyzeStock(analyticTicker.toUpperCase().trim(), analyticMode, screenerCtx)
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

  const empiricalMemory = r?.empirical_memory || null
  const empiricalAvailable = Boolean(empiricalMemory?.available)
  const empiricalSample = Number(empiricalMemory?.sample_count || 0)
  const empiricalWinrate = Number(empiricalMemory?.winrate || 0)
  const empiricalExpectancy = Number(empiricalMemory?.expectancy_pct || 0)
  const empiricalConfidence = Number(empiricalMemory?.confidence || 0)
  const empiricalFeatures = empiricalMemory?.features || {}
  const empiricalVerdict = !empiricalMemory
    ? { label: 'NO DATA', color: 'slate', impact: 'Historical memory belum dikirim oleh backend analytic.' }
    : !empiricalAvailable
    ? { label: 'LEARNING', color: 'amber', impact: 'Pattern sudah dikenali, tetapi agregat historis belum cukup untuk menjadi bukti utama.' }
    : empiricalSample < 30
    ? { label: 'REFERENCE ONLY', color: 'amber', impact: 'Sample historis masih tipis, gunakan sebagai referensi pendukung.' }
    : empiricalWinrate >= 58
    ? { label: 'SUPPORTS SETUP', color: 'green', impact: 'Historis 15 tahun mendukung setup ini sebagai faktor penguat keputusan.' }
    : empiricalWinrate <= 45
    ? { label: 'HISTORICAL WARNING', color: 'red', impact: 'Historis 15 tahun memperingatkan setup ini, perlu konfirmasi ekstra atau hindari entry agresif.' }
    : { label: 'NEUTRAL', color: 'blue', impact: 'Historis tidak cukup kuat untuk mendukung atau menolak setup.' }
  const empiricalColorClasses = {
    green: 'border-green-500/40 bg-green-500/10 text-green-500',
    red: 'border-red-500/40 bg-red-500/10 text-red-500',
    amber: 'border-amber-500/40 bg-amber-500/10 text-amber-500',
    blue: 'border-sky-500/40 bg-sky-500/10 text-sky-500',
    slate: 'border-slate-400/40 bg-slate-400/10 text-slate-500',
  }
  const actionOrderType = String(r?.action_plan?.order_type || r?.entry_order_type || '').toUpperCase()
  const orderbookExecution = r?.orderbook_execution || r?.action_plan?.orderbook_execution || null
  const officialEnrichment = r?.official_enrichment || r?.action_plan?.official_enrichment || null
  const moneyMaker = r?.money_maker || r?.action_plan?.money_maker || null
  const opportunityExecution = r?.opportunity_execution || r?.action_plan?.opportunity_execution || null
  const noActionableLong = ['NO_LONG_ENTRY', 'NO_MARKET_ENTRY'].includes(actionOrderType)
  const valueOrFallback = (value, fallback) =>
    value !== undefined && value !== null && value !== '' ? value : fallback
  const tradeEntry = noActionableLong && actionOrderType === 'NO_LONG_ENTRY'
    ? null
    : valueOrFallback(r?.action_plan?.entry_price, r?.entry)
  const tradeStop = valueOrFallback(r?.action_plan?.stop_loss, valueOrFallback(r?.dynamic_sltp?.sl, r?.stop_loss || r?.sl))
  const tradeTp1 = noActionableLong && actionOrderType === 'NO_LONG_ENTRY'
    ? null
    : valueOrFallback(r?.action_plan?.take_profit_1, valueOrFallback(r?.dynamic_sltp?.tp1, r?.tp1))
  const tradeTp2 = noActionableLong && actionOrderType === 'NO_LONG_ENTRY'
    ? null
    : valueOrFallback(r?.action_plan?.take_profit_2, valueOrFallback(r?.dynamic_sltp?.tp2, r?.tp2))
  const tradeTp3 = noActionableLong && actionOrderType === 'NO_LONG_ENTRY'
    ? null
    : valueOrFallback(r?.action_plan?.take_profit_3, valueOrFallback(r?.dynamic_sltp?.tp3, r?.tp3))
  const canSendToMonitoring = Boolean(tradeEntry && tradeStop && tradeTp1 && !noActionableLong)

  const groupEngineKeys = {
    group1:['priceaction','trend','support','resistance','volumeintelligence','relativevolume','multitime','orderblock','breakorder','fairvalue','liquidity'],
    group2:['bandarmology','inventory','flowmapping','intradaypositioning','brokerbehavior','foreignflow'],
    group3:['quant','orderbook','relativestrength','fibonacci','pattern','sector','macromarket','macroeconomics','geopolit','news','insider','probability','tradingsetup'],
    group4:['risk','scorecard','aiconfidence','smartrotation','realtimealert','liquidityquality'],
  }

  const normalizeEngineName = (name) => String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '')
  const getGroupEngines = (grp) =>
    Object.entries(engines).filter(([k]) =>
      groupEngineKeys[grp]?.some(gk => normalizeEngineName(k).includes(gk)))

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
        <p className="text-slate-500 text-sm font-mono mt-0.5">Deep analysis 35 engines · Multi-timeframe · AI trading decision</p>
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
                <p className="font-mono text-[10px] text-slate-400 mt-0.5">Score analytic ≠ score screener — metrik berbeda</p>
              </div>
              {r.signal && <SignalBadge signal={r.signal}/>}

              {/* GO / NO GO Banner */}
              {r.go_no_go && (
                <div className={`w-full rounded-xl border-2 px-4 py-3 text-center ${
                  r.go_no_go === 'STRONG GO' ? 'border-green-500 bg-green-500/10' :
                  r.go_no_go === 'GO'         ? 'border-green-400 bg-green-400/10' :
                  r.go_no_go === 'WAIT'       ? 'border-yellow-400 bg-yellow-400/10' :
                                                'border-red-500 bg-red-500/10'
                }`}>
                  <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mb-1">
                    Setup Decision
                  </p>
                  <p className={`font-display text-2xl font-bold ${
                    r.go_no_go === 'STRONG GO' ? 'text-green-400' :
                    r.go_no_go === 'GO'         ? 'text-green-400' :
                    r.go_no_go === 'WAIT'       ? 'text-yellow-400' :
                                                  'text-red-400'
                  }`}>
                    {r.go_no_go === 'STRONG GO' ? '🟢 STRONG GO' :
                     r.go_no_go === 'GO'         ? '🟢 GO' :
                     r.go_no_go === 'WAIT'       ? '🟡 WAIT' :
                                                   '🔴 NO GO'}
                  </p>
                  <p className="font-mono text-xs text-slate-400 mt-1">
                    Confidence: {r.go_confidence}%
                  </p>
                  {r.go_reasons?.length > 0 && (
                    <div className="mt-2 text-left space-y-0.5">
                      {r.go_reasons.map((reason, i) => (
                        <p key={i} className="font-mono text-[10px] text-green-400">✅ {reason}</p>
                      ))}
                    </div>
                  )}
                  {r.no_go_reasons?.length > 0 && (
                    <div className="mt-1 text-left space-y-0.5">
                      {r.no_go_reasons.map((reason, i) => (
                        <p key={i} className="font-mono text-[10px] text-red-400">❌ {reason}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Phase 2 Summary */}
              {r.wyckoff_phase && r.wyckoff_phase !== 'UNKNOWN' && (
                <div className="w-full rounded-xl border border-violet-500/30 bg-violet-500/5 px-3 py-2">
                  <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mb-1">Phase 2</p>
                  <div className="flex justify-between items-center">
                    <span className="font-mono text-xs text-slate-400">Wyckoff</span>
                    <span className={`font-mono text-xs font-bold ${
                      ['ACCUMULATION','MARKUP','REACCUMULATION'].includes(r.wyckoff_phase) ? 'text-green-400' :
                      ['DISTRIBUTION','MARKDOWN'].includes(r.wyckoff_phase) ? 'text-red-400' : 'text-yellow-400'
                    }`}>{r.wyckoff_phase}</span>
                  </div>
                  <div className="flex justify-between items-center mt-0.5">
                    <span className="font-mono text-xs text-slate-400">Weinstein</span>
                    <span className={`font-mono text-xs font-bold ${
                      r.weinstein_stage === 2 ? 'text-green-400' :
                      r.weinstein_stage === 4 ? 'text-red-400' :
                      r.weinstein_stage === 3 ? 'text-orange-400' : 'text-slate-400'
                    }`}>Stage {r.weinstein_stage}</span>
                  </div>
                  {r.vsa_signal && r.vsa_signal !== 'NONE' && (
                    <div className="flex justify-between items-center mt-0.5">
                      <span className="font-mono text-xs text-slate-400">VSA</span>
                      <span className={`font-mono text-xs font-bold ${
                        ['STOPPING_VOLUME','NO_SUPPLY','TEST'].includes(r.vsa_signal) ? 'text-green-400' :
                        ['UP_THRUST','NO_DEMAND'].includes(r.vsa_signal) ? 'text-red-400' : 'text-yellow-400'
                      }`}>{r.vsa_signal}</span>
                    </div>
                  )}
                  <div className="flex justify-between items-center mt-0.5">
                    <span className="font-mono text-xs text-slate-400">Enrichment</span>
                    <span className={`font-mono text-xs font-bold ${
                      r.enrichment_verdict === 'PROCEED' ? 'text-green-400' :
                      r.enrichment_verdict === 'SKIP' ? 'text-red-400' : 'text-yellow-400'
                    }`}>{r.enrichment_verdict}</span>
                  </div>
                </div>
              )}

              {r.market_regime && (
                <div className={`mt-1 rounded-xl border px-3 py-2 text-center ${
                  r.market_regime.includes('BULL') ? 'border-accent-green/30 bg-accent-green/10' :
                  r.market_regime.includes('BEAR') ? 'border-accent-red/30 bg-accent-red/10' :
                  'border-slate-600/30 bg-slate-600/10'
                }`}>
                  <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">Market Context</p>
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
              {r.action_plan && (
                <div className="w-full rounded-xl border border-accent-gold/40 bg-accent-gold/10 px-3 py-3 text-left">
                  <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mb-2">
                    Executable Setup Plan
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      ['Setup', String(r.action_plan.setup_type || r.setup_type || '').replace(/_/g, ' ')],
                      ['Order', String(r.action_plan.order_type || r.entry_order_type || '').replace(/_/g, ' ')],
                      ['Trigger', fmtPrice(r.action_plan.trigger_price)],
                      ['Entry Zone', `${fmtPrice(r.action_plan.entry_zone_low)} - ${fmtPrice(r.action_plan.entry_zone_high)}`],
                      ['Stop', fmtPrice(r.action_plan.stop_loss || r.stop_loss)],
                      ['Invalidation', fmtPrice(r.action_plan.invalidation_price)],
                    ].map(([k,v]) => (
                      <div key={k} className="rounded-lg border border-slate-200 bg-white/70 px-2 py-1.5">
                        <p className="font-mono text-[9px] uppercase tracking-wider text-slate-500">{k}</p>
                        <p className="font-mono text-[11px] font-bold text-slate-900">{v}</p>
                      </div>
                    ))}
                  </div>
                  {r.action_plan.next_action && (
                    <p className="mt-2 font-mono text-[11px] leading-relaxed text-slate-700">
                      {r.action_plan.next_action}
                    </p>
                  )}
                  {r.action_plan.confirmation_needed?.length > 0 && (
                    <div className="mt-2">
                      <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500">Confirmation Needed</p>
                      <div className="mt-1 space-y-0.5">
                        {r.action_plan.confirmation_needed.slice(0, 4).map((x, i) => (
                          <p key={i} className="font-mono text-[10px] text-slate-700">- {x}</p>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {orderbookExecution && (
                <div className="w-full rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-3 py-3 text-left">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                        Orderbook Execution Overlay
                      </p>
                      <p className="mt-1 font-mono text-[11px] font-bold uppercase text-slate-900">
                        {String(orderbookExecution.execution_recommendation || 'USE_EXISTING_PLAN').replace(/_/g, ' ')}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 font-mono text-[9px] font-bold uppercase tracking-wider text-cyan-600">
                      Additive
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {[
                      ['Bias', formatLabel(orderbookExecution.liquidity_bias)],
                      ['Spread', formatLabel(orderbookExecution.spread_health)],
                      ['Bid/Ask', orderbookExecution.bid_ask_ratio ? `${Number(orderbookExecution.bid_ask_ratio).toFixed(2)}x` : '-'],
                      ['Spread %', orderbookExecution.spread_pct !== undefined ? fmtPercent(orderbookExecution.spread_pct, 2) : '-'],
                      ['Limit Entry', orderbookExecution.suggested_limit_entry ? fmtPrice(orderbookExecution.suggested_limit_entry) : '-'],
                      ['Ask Trigger', orderbookExecution.suggested_market_trigger ? fmtPrice(orderbookExecution.suggested_market_trigger) : '-'],
                    ].map(([k, v]) => (
                      <div key={k} className="rounded-lg border border-slate-200 bg-white/70 px-2 py-1.5">
                        <p className="font-mono text-[9px] uppercase tracking-wider text-slate-500">{k}</p>
                        <p className="font-mono text-[11px] font-bold text-slate-900">{v}</p>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 font-mono text-[11px] leading-relaxed text-slate-700">
                    {orderbookExecution.reason || 'Orderbook hanya menajamkan cara eksekusi, bukan mengganti keputusan setup.'}
                  </p>
                </div>
              )}

              {officialEnrichment?.available && (
                <div className="w-full rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-left">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                        Official Invezgo Enrichment
                      </p>
                      <p className="mt-1 font-mono text-[11px] font-bold uppercase text-slate-900">
                        Time, momentum, broker, fundamental, corporate action
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 font-mono text-[9px] font-bold uppercase tracking-wider text-emerald-600">
                      Cached
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {[
                      ['Time Table', formatLabel(officialEnrichment.time_table?.pressure || 'n/a')],
                      ['Momentum', formatLabel(officialEnrichment.momentum_chart?.bias || 'n/a')],
                      ['Broker Stalker', `${Number(officialEnrichment.broker_stalker?.available_count || 0)} active`],
                      ['Corp Action', `${Number(officialEnrichment.corporate_actions?.count || 0)} items`],
                      ['Key Stat', officialEnrichment.key_stat?.available ? `${Number(officialEnrichment.key_stat?.rows || 0)} rows` : '-'],
                      ['Sankey', officialEnrichment.sankey_available ? 'Available' : '-'],
                    ].map(([k, v]) => (
                      <div key={k} className="rounded-lg border border-slate-200 bg-white/70 px-2 py-1.5">
                        <p className="font-mono text-[9px] uppercase tracking-wider text-slate-500">{k}</p>
                        <p className="font-mono text-[11px] font-bold text-slate-900">{v}</p>
                      </div>
                    ))}
                  </div>
                  {officialEnrichment.warnings?.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {officialEnrichment.warnings.slice(0, 3).map((w, i) => (
                        <p key={i} className="font-mono text-[10px] text-amber-700">- {w.message}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {moneyMaker?.available && (
                <div className="w-full rounded-xl border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-3 text-left">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                        Money Maker Core
                      </p>
                      <p className="mt-1 font-mono text-[11px] font-bold uppercase text-slate-900">
                        {formatLabel(moneyMaker.verdict || 'n/a')} | {formatLabel(moneyMaker.phase || 'n/a')}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full border border-fuchsia-500/40 bg-fuchsia-500/10 px-2 py-1 font-mono text-[9px] font-bold uppercase tracking-wider text-fuchsia-600">
                      BFD {Number(moneyMaker.bfd_score || 0)}/5
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {[
                      ['Score', Number(moneyMaker.score || 0).toFixed(1)],
                      ['Broker', Number(moneyMaker.components?.broker || 0).toFixed(0)],
                      ['Orderbook', Number(moneyMaker.components?.orderbook || 0).toFixed(0)],
                      ['Official', Number(moneyMaker.components?.official || 0).toFixed(0)],
                      ['VSR', `${Number(moneyMaker.metrics?.vsr || 0).toFixed(2)}x`],
                      ['Bandar Avg Dist', `${Number(moneyMaker.metrics?.current_vs_bandar_avg_pct || 0).toFixed(2)}%`],
                      ['Execution', formatLabel(moneyMaker.execution_intelligence?.stance || 'n/a')],
                      ['Memory', moneyMaker.flow_memory?.flow_reversal_alert ? 'REVERSAL' : moneyMaker.flow_memory?.memory_available ? `${Number(moneyMaker.flow_memory?.bfd_delta || 0).toFixed(1)} BFD` : '-'],
                    ].map(([k, v]) => (
                      <div key={k} className="rounded-lg border border-slate-200 bg-white/70 px-2 py-1.5">
                        <p className="font-mono text-[9px] uppercase tracking-wider text-slate-500">{k}</p>
                        <p className="font-mono text-[11px] font-bold text-slate-900">{v}</p>
                      </div>
                    ))}
                  </div>
                  {moneyMaker.risk_flags?.length > 0 && (
                    <p className="mt-2 font-mono text-[10px] text-amber-700">
                      Risk: {moneyMaker.risk_flags.slice(0, 4).join(', ')}
                    </p>
                  )}
                  {moneyMaker.patterns?.length > 0 && (
                    <p className="mt-2 font-mono text-[10px] text-fuchsia-700">
                      Patterns: {moneyMaker.patterns.slice(0, 4).map((p) => p.name).join(', ')}
                    </p>
                  )}
                  {moneyMaker.doctrine?.rules?.length > 0 && (
                    <p className="mt-1 font-mono text-[10px] text-slate-700">
                      Doctrine: {moneyMaker.doctrine.rules[0]}
                    </p>
                  )}
                </div>
              )}

              {empiricalMemory && (
                <div className="w-full rounded-xl border border-sky-500/30 bg-sky-500/10 px-3 py-3 text-left">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                        15Y Historical Memory
                      </p>
                      <p className="mt-1 font-mono text-[11px] font-bold text-slate-900">
                        {empiricalMemory.pattern_key || 'Pattern belum tersedia'}
                      </p>
                    </div>
                    <span className={clsx(
                      'shrink-0 rounded-full border px-2 py-1 font-mono text-[9px] font-bold uppercase tracking-wider',
                      empiricalColorClasses[empiricalVerdict.color]
                    )}>
                      {empiricalVerdict.label}
                    </span>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {[
                      ['Sample', empiricalSample ? empiricalSample.toLocaleString('id-ID') : '-'],
                      ['Winrate', empiricalAvailable ? fmtPercent(empiricalWinrate) : '-'],
                      ['Expectancy', empiricalAvailable ? fmtPercent(empiricalExpectancy, 2) : '-'],
                      ['Confidence', empiricalAvailable ? fmtPercent(empiricalConfidence) : '-'],
                    ].map(([k, v]) => (
                      <div key={k} className="rounded-lg border border-slate-200 bg-white/70 px-2 py-1.5">
                        <p className="font-mono text-[9px] uppercase tracking-wider text-slate-500">{k}</p>
                        <p className="font-mono text-[11px] font-bold text-slate-900">{v}</p>
                      </div>
                    ))}
                  </div>

                  {(empiricalFeatures.trend_state || empiricalFeatures.momentum_state || empiricalFeatures.volume_state || empiricalFeatures.location_state) && (
                    <div className="mt-2 grid grid-cols-2 gap-1.5">
                      {[
                        ['Trend', empiricalFeatures.trend_state],
                        ['Momentum', empiricalFeatures.momentum_state],
                        ['Volume', empiricalFeatures.volume_state],
                        ['Location', empiricalFeatures.location_state],
                      ].filter(([, v]) => v).map(([k, v]) => (
                        <div key={k} className="flex justify-between gap-2 rounded border border-slate-200 bg-white/50 px-2 py-1">
                          <span className="font-mono text-[9px] uppercase text-slate-500">{k}</span>
                          <span className="font-mono text-[9px] font-bold text-slate-800">{formatLabel(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <p className="mt-2 font-mono text-[11px] leading-relaxed text-slate-700">
                    {empiricalVerdict.impact}
                  </p>
                  {empiricalMemory.literature && (
                    <p className="mt-2 rounded-lg border border-slate-200 bg-white/60 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-slate-600">
                      {empiricalMemory.literature}
                    </p>
                  )}
                </div>
              )}
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
                ['Order Type', String(r.action_plan?.order_type || r.entry_order_type || r.entry_method || '').replace(/_/g, ' '), 'text-accent-blue'],
                ['Trigger Price', r.action_plan?.trigger_price || r.trigger_price, 'text-accent-gold'],
                ['Entry Price', tradeEntry, 'text-accent-green'],
                ['Entry Zone', r.action_plan ? `${fmtPrice(r.action_plan.entry_zone_low)} - ${fmtPrice(r.action_plan.entry_zone_high)}` : null, 'text-accent-green'],
                ['Stop Loss', tradeStop, 'text-accent-red'],
                ['Take Profit 1', tradeTp1, 'text-accent-gold'],
                ['Take Profit 2', tradeTp2, 'text-accent-gold'],
                ['Take Profit 3', tradeTp3, 'text-accent-gold'],
                ['Risk:Reward', !noActionableLong && r.risk_reward ? `1:${Number(r.risk_reward).toFixed(2)}` : null, 'text-accent-blue'],
              ].filter(([,v]) => v).map(([k,v,c]) => (
                <div key={k} className="flex justify-between items-center py-1.5 border-b border-border-dim last:border-0">
                  <span className="font-mono text-xs text-slate-500">{k}</span>
                  <span className={clsx('font-mono font-bold text-sm', c)}>
                    {typeof v==='number'?`Rp ${v.toLocaleString('id-ID')}`:v}
                  </span>
                </div>
              ))}
              {noActionableLong && (
                <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-2 font-mono text-xs leading-relaxed text-amber-700">
                  Belum ada long entry aktif. Gunakan trigger dan confirmation needed sebagai syarat sebelum target profit dianggap valid.
                </div>
              )}
              {opportunityExecution?.active && (
                <div className="rounded-lg border border-sky-400/40 bg-sky-400/10 px-3 py-2 font-mono text-xs leading-relaxed text-sky-700">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold uppercase">Top Gainer Opportunity Mode</span>
                    <span className="font-bold">{Number(opportunityExecution.change_pct || 0).toFixed(2)}%</span>
                  </div>
                  <p className="mt-1">
                    {String(opportunityExecution.execution_bias || '').replace(/_/g, ' ')}. Eksekusi hanya setelah trigger, base/VWAP, orderbook, dan flow mengonfirmasi.
                  </p>
                </div>
              )}
              {/* Dynamic SL/TP — hidden, sudah digabung ke Trade Setup primary */}
              {false && r.dynamic_sltp && r.dynamic_sltp.method !== 'error' && (
                <div className="mt-2 rounded-lg border border-accent-blue/30 bg-accent-blue/5 p-3">
                  <p className="font-mono text-[10px] text-slate-500 mb-2">⚡ DYNAMIC SL/TP (ATR × Regime × Score)</p>
                  {[
                    ['Dynamic SL', r.dynamic_sltp.sl, 'text-accent-red'],
                    ['Dynamic TP1', r.dynamic_sltp.tp1, 'text-accent-gold'],
                    ['Dynamic TP2', r.dynamic_sltp.tp2, 'text-accent-gold'],
                    ['Dynamic TP3', r.dynamic_sltp.tp3, 'text-accent-gold'],
                    ['ATR', r.dynamic_sltp.atr ? `${r.dynamic_sltp.atr_pct?.toFixed(1)}%` : null, 'text-accent-blue'],
                    ['R:R TP1', r.dynamic_sltp.rr1 ? `1:${r.dynamic_sltp.rr1}` : null, 'text-accent-blue'],
                  ].filter(([,v]) => v).map(([k,v,c]) => (
                    <div key={k} className="flex justify-between items-center py-1 border-b border-border-dim/50 last:border-0">
                      <span className="font-mono text-[10px] text-slate-500">{k}</span>
                      <span className={clsx('font-mono font-bold text-xs', c)}>
                        {typeof v==='number'?`Rp ${v.toLocaleString('id-ID')}`:v}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <button onClick={() => sendToMonitoring({
                ticker:r.ticker||analyticTicker,
                entry_price:tradeEntry,
                stop_loss:tradeStop,
                take_profit:tradeTp1,
                take_profit_1:tradeTp1,
                take_profit_2:tradeTp2,
                take_profit_3:tradeTp3,
                mode:analyticMode,
                final_score:r.score||r.composite_score||50,
                market_regime:r.market_regime||'SIDEWAYS',
                engine_scores:normalizeEngineScoresForMonitoring(r.engines?.engines || r.engine_scores || {}),
                lq45_change:r.lq45_change||0,
                breadth_ratio:r.market_breadth||50,
                kb_context:r.rag_used?'rag_active':'',
                // ALIGN: Pass GO/NO GO decision to monitoring
                analytic_context: {
                  go_no_go: r.go_no_go || 'WAIT',
                  go_confidence: r.go_confidence || 50,
                  go_reasons: r.go_reasons || [],
                  no_go_reasons: r.no_go_reasons || [],
                  win_probability: r.win_probability || 50,
                  action_plan: r.action_plan || null,
                  orderbook_execution: orderbookExecution || null,
                  official_enrichment: officialEnrichment || null,
                  money_maker: moneyMaker || null,
                  opportunity_execution: opportunityExecution || null,
                  empirical_memory: r.empirical_memory || null,
                  setup_type: r.setup_type || '',
                  setup_reason: r.setup_reason || ''
                }
              })} disabled={!canSendToMonitoring} className="btn-primary w-full flex items-center justify-center gap-2 mt-2 disabled:opacity-50 disabled:cursor-not-allowed">
                {canSendToMonitoring ? 'Monitor Posisi' : 'Belum Bisa Monitor'}<ArrowRight className="w-4 h-4"/>
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
            <p className="label-xs mb-3">Engine Scores — 35 Engines</p>
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
                  <p className="font-mono text-xs text-slate-700">
                    {r ? 'Tidak ada engine yang cocok dengan grup ini' : 'Jalankan analisis untuk melihat engine scores'}
                  </p>
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
          {r && <Suspense fallback={null}><EnrichmentPanel ticker={analyticTicker} /></Suspense>}
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
