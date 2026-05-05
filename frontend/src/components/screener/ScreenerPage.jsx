import React, { useState } from 'react'
import { Search, TrendingUp, ChevronRight, RefreshCw, Target, Clock, Zap } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { runScreener } from '../../utils/api'
import { ScoreGauge, ScoreBar, SignalBadge, LoadingSpinner, ErrorBox, ConfidenceBar } from '../shared/ScoreComponents'
import clsx from 'clsx'

const MODES = [
  { id:'SWING', label:'Swing', icon:TrendingUp, desc:'<1 bulan' },
  { id:'DAYTRADING', label:'Day Trade', icon:Clock, desc:'Intraday' },
  { id:'SCALPING', label:'Scalping', icon:Zap, desc:'Per menit' },
]

export default function ScreenerPage() {
  const { screenerMode, setScreenerMode, screenerResults, setScreenerResults,
    screenerLoading, setScreenerLoading, screenerError, setScreenerError, sendToAnalytic } = useStore()
  const [selected, setSelected] = useState(null)

  const handleScan = async () => {
    setScreenerLoading(true); setScreenerError(null); setScreenerResults(null); setSelected(null)
    try {
      const res = await runScreener(screenerMode)
      setScreenerResults(res.data)
    } catch(e) {
      setScreenerError(e?.response?.data?.detail || e.message || 'Gagal menjalankan screener')
    } finally { setScreenerLoading(false) }
  }

  const stocks = screenerResults?.top_stocks || screenerResults?.results || []

  return (
    <div className="p-4 lg:p-6 max-w-7xl mx-auto animate-fade-in">
      <div className="mb-6">
        <h1 className="font-display font-bold text-2xl text-white tracking-wide">SCREENER TOOL</h1>
        <p className="text-slate-500 text-sm font-mono mt-0.5">Scan seluruh saham IDX · 34 engines · AI-powered ranking</p>
      </div>
      <div className="card p-4 mb-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="label-xs">Mode:</span>
          <div className="flex gap-2">
            {MODES.map(({id,label,icon:Icon,desc}) => (
              <button key={id} onClick={() => setScreenerMode(id)}
                className={clsx('flex items-center gap-2 px-4 py-2 rounded border text-sm font-display font-semibold tracking-wider uppercase transition-all duration-200',
                  screenerMode===id?'border-accent-green bg-accent-green/10 text-accent-green':'border-border-dim text-slate-500 hover:border-border-bright hover:text-slate-300')}>
                <Icon className="w-3.5 h-3.5"/>{label}
              </button>
            ))}
          </div>
          <div className="ml-auto">
            <button onClick={handleScan} disabled={screenerLoading}
              className="btn-primary flex items-center gap-2 disabled:opacity-50">
              {screenerLoading?<RefreshCw className="w-4 h-4 animate-spin"/>:<Search className="w-4 h-4"/>}
              {screenerLoading?'Scanning...':'Run Screener'}
            </button>
          </div>
        </div>
      </div>
      {screenerLoading && <LoadingSpinner message="Scanning semua saham IDX..."/>}
      {screenerError && !screenerLoading && <ErrorBox message={screenerError} onRetry={handleScan}/>}
      {!screenerLoading && stocks.length>0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1 space-y-2">
            <p className="label-xs mb-3">TOP {stocks.length} SAHAM PILIHAN</p>
            {stocks.map((stock,i) => (
              <div key={stock.ticker||i} onClick={() => setSelected(stock)}
                className={clsx('card p-3 cursor-pointer transition-all duration-200',
                  selected?.ticker===stock.ticker?'border-accent-green/60 bg-accent-green/5':'hover:border-border-bright')}>
                <div className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded bg-border-dim flex items-center justify-center shrink-0">
                    <span className="font-display font-bold text-xs text-slate-400">#{i+1}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-display font-bold text-white text-sm">{stock.ticker}</span>
                      {stock.signal && <SignalBadge signal={stock.signal}/>}
                    </div>
                    <div className="font-mono text-xs text-slate-500 truncate">{stock.name||'—'}</div>
                  </div>
                  <div className="flex flex-col items-end">
                    <span className={clsx('font-mono font-bold text-lg leading-none',
                      (stock.composite_score||0)>=70?'text-accent-green':(stock.composite_score||0)>=45?'text-accent-gold':'text-accent-red')}>
                      {Math.round(stock.composite_score||stock.score||0)}
                    </span>
                    <span className="label-xs">score</span>
                  </div>
                  <ChevronRight className={clsx('w-4 h-4 shrink-0',selected?.ticker===stock.ticker?'text-accent-green':'text-slate-600')}/>
                </div>
              </div>
            ))}
          </div>
          <div className="lg:col-span-2">
            {selected ? (
              <div className="card p-5 space-y-4 animate-slide-up">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-3 mb-1">
                      <h2 className="font-display font-bold text-2xl text-white">{selected.ticker}</h2>
                      {selected.signal && <SignalBadge signal={selected.signal}/>}
                    </div>
                    <p className="font-mono text-sm text-slate-500">{selected.name||'—'}</p>
                  </div>
                  <ScoreGauge score={selected.composite_score||selected.score||0} size={72} label="Score"/>
                </div>
                {selected.confidence!==undefined && (
                  <div><p className="label-xs mb-1.5">AI Confidence</p>
                    <ConfidenceBar value={selected.confidence||0}/></div>
                )}
                {(selected.entry_price||selected.stop_loss||selected.take_profit) && (
                  <div className="grid grid-cols-3 gap-3">
                    {selected.entry_price && <div className="bg-bg-secondary rounded p-2.5 text-center">
                      <p className="label-xs mb-1">Entry</p>
                      <p className="font-mono text-sm font-bold text-accent-green">{Number(selected.entry_price).toLocaleString('id-ID')}</p>
                    </div>}
                    {selected.stop_loss && <div className="bg-bg-secondary rounded p-2.5 text-center">
                      <p className="label-xs mb-1">Stop Loss</p>
                      <p className="font-mono text-sm font-bold text-accent-red">{Number(selected.stop_loss).toLocaleString('id-ID')}</p>
                    </div>}
                    {selected.take_profit && <div className="bg-bg-secondary rounded p-2.5 text-center">
                      <p className="label-xs mb-1">Target</p>
                      <p className="font-mono text-sm font-bold text-accent-gold">{Number(selected.take_profit).toLocaleString('id-ID')}</p>
                    </div>}
                  </div>
                )}
                {selected.rationale && (
                  <div className="bg-bg-secondary rounded p-3 border border-border-dim">
                    <p className="label-xs mb-2">🤖 AI Rationale</p>
                    <p className="font-mono text-xs text-slate-400 leading-relaxed">{selected.rationale}</p>
                  </div>
                )}
                <button onClick={() => sendToAnalytic(selected.ticker)}
                  className="btn-primary w-full flex items-center justify-center gap-2">
                  Deep Analyze {selected.ticker}<ChevronRight className="w-4 h-4"/>
                </button>
              </div>
            ) : (
              <div className="card h-full flex items-center justify-center min-h-[300px]">
                <div className="text-center">
                  <Target className="w-10 h-10 text-slate-700 mx-auto mb-3"/>
                  <p className="font-mono text-sm text-slate-600">Pilih saham untuk melihat detail</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {!screenerLoading && !screenerError && stocks.length===0 && !screenerResults && (
        <div className="card p-12 text-center">
          <Search className="w-12 h-12 text-slate-700 mx-auto mb-4"/>
          <p className="font-display text-lg text-slate-500 mb-1">Siap untuk scan</p>
          <p className="font-mono text-sm text-slate-700">Pilih mode trading dan klik Run Screener</p>
        </div>
      )}
    </div>
  )
}
