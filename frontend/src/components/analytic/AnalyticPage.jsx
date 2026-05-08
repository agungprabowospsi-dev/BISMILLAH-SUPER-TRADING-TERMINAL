import React, { useState } from 'react'
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

  const handleAnalyze = async () => {
    if(!analyticTicker.trim()) return
    setAnalyticLoading(true); setAnalyticError(null); setAnalyticResult(null)
    try {
      const res = await analyzeStock(analyticTicker.toUpperCase().trim(), analyticMode)
      setAnalyticResult(res)
    } catch(e) {
      setAnalyticError(e?.response?.data?.detail || e.message || 'Gagal menganalisis')
    } finally { setAnalyticLoading(false) }
  }

  const r = analyticResult
  // Backend returns engines as array [{engine, score, signal, ...}]
  // Convert to object {engineName: {score, signal, ...}} for UI
  const enginesRaw = r?.engines?.engines || r?.engine_scores || []
  const engines = Array.isArray(enginesRaw)
    ? Object.fromEntries(enginesRaw.map(e => [e.engine, e]))
    : enginesRaw

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
            className="w-40 bg-bg-secondary border border-border-dim rounded px-3 py-2 font-mono text-sm text-white placeholder-slate-700 focus:border-accent-green focus:outline-none uppercase"/>
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
                entry_price:r.entry, stop_loss:r.stop_loss||r.sl||r.sl,
                take_profit_1:r.tp1,
                take_profit_2:r.tp2, take_profit_3:r.tp3,
                mode:analyticMode
              })} className="btn-primary w-full flex items-center justify-center gap-2 mt-2">
                Monitor Posisi<ArrowRight className="w-4 h-4"/>
              </button>
            </div>
          </div>

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
