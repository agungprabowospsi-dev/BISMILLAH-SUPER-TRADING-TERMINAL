import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Zap, RefreshCw, TrendingUp, TrendingDown, Brain, AlertTriangle } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import clsx from 'clsx'

const BACKEND = 'https://backend-production-daed.up.railway.app'
const POPULAR = ['BBCA','BBRI','TLKM','BMRI','ASII','GOTO','ANTM','INDF','ICBP','UNVR']
const SIG = {
  ENTRY: { color: 'text-accent-green', bg: 'bg-accent-green/10 border-accent-green/30', label: '🟢 ENTRY' },
  EXIT:  { color: 'text-accent-red',   bg: 'bg-accent-red/10 border-accent-red/30',     label: '🔴 EXIT'  },
  HOLD:  { color: 'text-slate-400',    bg: 'bg-slate-700/10 border-slate-700/30',        label: '⬜ HOLD'  },
}

export default function ScalpingPage() {
  const { scalpingTicker, setScalpingTicker } = useStore()
  const [input, setInput] = useState(scalpingTicker || '')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState([])
  const intervalRef = useRef(null)

  const fetchSnapshot = useCallback(async (ticker) => {
    if (!ticker) return
    try {
      const res = await fetch(BACKEND + '/api/scalping/snapshot/' + ticker)
      const d = await res.json()
      if (d.price) { setData(d); setHistory(h => [...h, { price: d.price, time: Date.now() }].slice(-60)) }
    } catch (e) { console.error(e) }
  }, [])

  const handleStart = async (ticker) => {
    const t = (ticker || input).toUpperCase().trim()
    if (!t) return
    setInput(t); setScalpingTicker(t); setData(null); setHistory([]); setLoading(true)
    clearInterval(intervalRef.current)
    await fetchSnapshot(t)
    setLoading(false)
    intervalRef.current = setInterval(() => fetchSnapshot(t), 10000)
  }

  useEffect(() => { if (scalpingTicker) handleStart(scalpingTicker); return () => clearInterval(intervalRef.current) }, [])

  const signal = data?.signal || 'HOLD'
  const cfg = SIG[signal] || SIG.HOLD
  const price = data?.price
  const prevPrice = history[history.length - 2]?.price
  const priceUp = price && prevPrice ? price > prevPrice : null
  const isGood = data?.is_good_for_scalping

  return (
    <div className="p-4 lg:p-6 max-w-7xl mx-auto animate-fade-in">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="font-display font-bold text-2xl text-white tracking-wide flex items-center gap-2">
            <Zap className="w-6 h-6 text-accent-green"/>SCALPING TERMINAL
          </h1>
          <p className="text-slate-500 text-sm font-mono mt-0.5">Real-time · Bid/Ask Analysis · AI Signal</p>
        </div>
        {data && (
          <div className={clsx('flex items-center gap-2 px-3 py-1.5 rounded border font-mono text-xs font-bold',
            isGood ? 'text-accent-green bg-accent-green/5 border-accent-green/20' : 'text-accent-red bg-accent-red/5 border-accent-red/20')}>
            {isGood ? '✅ BAGUS UNTUK SCALPING' : '❌ TIDAK BAGUS'}
          </div>
        )}
      </div>

      <div className="card p-4 mb-5">
        <div className="flex gap-3 flex-wrap items-center">
          <input type="text" value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && handleStart()}
            placeholder="TICKER" maxLength={10}
            className="w-32 bg-bg-secondary border border-border-dim rounded px-3 py-2 font-mono text-sm text-white placeholder-slate-700 focus:border-accent-green focus:outline-none uppercase"/>
          <button onClick={() => handleStart()} className="btn-primary flex items-center gap-2">
            {loading ? <RefreshCw className="w-4 h-4 animate-spin"/> : <Zap className="w-4 h-4"/>}
            {loading ? 'Loading...' : 'Start'}
          </button>
          <div className="flex flex-wrap gap-1.5">
            {POPULAR.map(t => (
              <button key={t} onClick={() => handleStart(t)}
                className={clsx('px-2.5 py-1 rounded border text-xs font-mono transition-all',
                  scalpingTicker === t ? 'border-accent-green/50 bg-accent-green/5 text-accent-green' : 'border-border-dim text-slate-600 hover:text-slate-300')}>
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {scalpingTicker && data ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-4">
            <div className={clsx('card p-5 border rounded-lg text-center', cfg.bg)}>
              <p className="label-xs mb-3">{scalpingTicker} — SIGNAL</p>
              <div className={clsx('font-display font-bold text-4xl tracking-widest mb-2', cfg.color)}>{cfg.label}</div>
              <p className="font-mono text-xs text-slate-400 mt-2 px-2">{data.reason}</p>
              <div className={clsx('mt-3 w-3 h-3 rounded-full mx-auto',
                signal === 'ENTRY' ? 'bg-accent-green animate-pulse' : signal === 'EXIT' ? 'bg-accent-red animate-pulse' : 'bg-slate-600')}/>
            </div>
            <div className="card p-4">
              <p className="label-xs mb-2">{scalpingTicker} — LIVE PRICE</p>
              <div className="flex items-center gap-2">
                <span className={clsx('font-mono font-bold text-3xl', priceUp === true ? 'text-accent-green' : priceUp === false ? 'text-accent-red' : 'text-white')}>
                  {Number(price).toLocaleString('id-ID')}
                </span>
                {priceUp === true && <TrendingUp className="w-5 h-5 text-accent-green"/>}
                {priceUp === false && <TrendingDown className="w-5 h-5 text-accent-red"/>}
              </div>
              {data.change !== undefined && (
                <p className={clsx('font-mono text-sm mt-1', data.change >= 0 ? 'text-accent-green' : 'text-accent-red')}>
                  {data.change >= 0 ? '+' : ''}{Number(data.change).toLocaleString('id-ID')} ({data.change_pct}%)
                </p>
              )}
              <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-border-dim">
                {[['Bid', data.bid], ['Ask', data.ask], ['Spread', data.spread], ['Spread%', data.spread_pct ? data.spread_pct + '%' : null]].map(([k, v]) => (
                  <div key={k}><p className="label-xs">{k}</p>
                    <p className="font-mono text-xs text-white">{v != null ? (typeof v === 'number' ? Number(v).toLocaleString('id-ID') : v) : '—'}</p>
                  </div>
                ))}
              </div>
            </div>
            {history.length > 2 && (
              <div className="card p-3">
                <p className="label-xs mb-2">Price Ticks ({history.length})</p>
                <svg width="100%" height="40" viewBox="0 0 100 40" preserveAspectRatio="none">
                  {(() => {
                    const prices = history.map(d => d.price)
                    const min = Math.min(...prices), max = Math.max(...prices), range = max - min || 1
                    const pts = prices.map((p, i) => (i / (prices.length - 1)) * 100 + ',' + (40 - ((p - min) / range) * 40)).join(' ')
                    return <polyline points={pts} fill="none" stroke={prices[prices.length-1] >= prices[0] ? '#00FF88' : '#FF3355'} strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
                  })()}
                </svg>
              </div>
            )}
          </div>

          <div className="card p-4">
            <p className="label-xs mb-3">BID/ASK ANALYSIS</p>
            <div className="bg-bg-secondary rounded p-3 mb-3 text-center">
              <p className="label-xs mb-1">Bid/Ask Ratio</p>
              <p className={clsx('font-mono font-bold text-2xl', data.bid_ask_ratio > 1.5 ? 'text-accent-green' : data.bid_ask_ratio < 0.7 ? 'text-accent-red' : 'text-white')}>
                {data.bid_ask_ratio}x
              </p>
              <p className="font-mono text-xs text-slate-500 mt-1">Freq Ratio: {data.freq_ratio}x</p>
            </div>
            <p className="label-xs text-accent-red mb-1">ASK (Jual)</p>
            <div className="bg-accent-red/5 border border-accent-red/20 rounded p-2 mb-2">
              <div className="flex justify-between font-mono text-xs">
                <span className="text-accent-red font-bold">{Number(data.ask).toLocaleString('id-ID')}</span>
                <span className="text-slate-500">{Number(data.offer_lot).toLocaleString('id-ID')} lot</span>
              </div>
              <div className="flex justify-between font-mono text-xs mt-1">
                <span className="text-slate-600">Freq</span>
                <span className="text-slate-400">{Number(data.offer_freq).toLocaleString('id-ID')}x</span>
              </div>
            </div>
            <div className="py-1 text-center border-y border-border-dim my-2">
              <span className="font-mono text-xs text-slate-500">Spread: {Number(data.spread).toLocaleString('id-ID')} ({data.spread_pct}%)</span>
            </div>
            <p className="label-xs text-accent-green mb-1">BID (Beli)</p>
            <div className="bg-accent-green/5 border border-accent-green/20 rounded p-2">
              <div className="flex justify-between font-mono text-xs">
                <span className="text-accent-green font-bold">{Number(data.bid).toLocaleString('id-ID')}</span>
                <span className="text-slate-500">{Number(data.bid_lot).toLocaleString('id-ID')} lot</span>
              </div>
              <div className="flex justify-between font-mono text-xs mt-1">
                <span className="text-slate-600">Freq</span>
                <span className="text-slate-400">{Number(data.bid_freq).toLocaleString('id-ID')}x</span>
              </div>
            </div>
            <div className={clsx('mt-3 p-2 rounded border text-center font-mono text-xs font-bold',
              isGood ? 'bg-accent-green/5 border-accent-green/20 text-accent-green' : 'bg-accent-red/5 border-accent-red/20 text-accent-red')}>
              {data.scalping_quality}
            </div>
          </div>

          <div className="space-y-4">
            <div className="card p-4">
              <p className="label-xs mb-3">INTRADAY STATS</p>
              <div className="space-y-2">
                {[['High', data.high, 'text-accent-green'], ['Low', data.low, 'text-accent-red'], ['Avg', data.avg, 'text-white'],
                  ['Volume', data.volume, 'text-slate-300'], ['Rel Vol', data.rvol ? data.rvol + 'x' : null, data?.rvol >= 2 ? 'text-accent-gold' : 'text-slate-400'],
                  ['Prev', data.prev, 'text-slate-400']].map(([k, v, c]) => (
                  <div key={k} className="flex justify-between items-center">
                    <span className="font-mono text-xs text-slate-600">{k}</span>
                    <span className={clsx('font-mono text-xs font-semibold', c)}>
                      {v != null ? (typeof v === 'number' ? Number(v).toLocaleString('id-ID') : v) : '—'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            {data.volume_alert && (
              <div className="card p-3 border-accent-gold/30 bg-accent-gold/5">
                <p className="font-mono text-xs text-accent-gold flex items-center gap-2">
                  <AlertTriangle className="w-3 h-3"/>⚡ {data.volume_alert}
                </p>
              </div>
            )}
            {data.ai_analysis && (
              <div className="card p-4 border-accent-green/20">
                <div className="flex items-center gap-2 mb-2">
                  <Brain className="w-3.5 h-3.5 text-accent-green"/>
                  <p className="label-xs text-accent-green">AI SCALPING ANALYSIS</p>
                </div>
                <p className="font-mono text-xs text-slate-400 leading-relaxed">
                  {data.ai_analysis.replace(/\*\*/g, '').replace(/#+\s/g, '')}
                </p>
              </div>
            )}
          </div>
        </div>
      ) : scalpingTicker && loading ? (
        <div className="card p-12 text-center">
          <RefreshCw className="w-8 h-8 text-accent-green mx-auto mb-4 animate-spin"/>
          <p className="font-mono text-sm text-slate-400">Mengambil data scalping {scalpingTicker}...</p>
        </div>
      ) : (
        <div className="card p-12 text-center">
          <Zap className="w-12 h-12 text-slate-700 mx-auto mb-4"/>
          <p className="font-display text-lg text-slate-500 mb-1">Pilih saham untuk mulai scalping</p>
          <p className="font-mono text-sm text-slate-700">Ketik ticker atau klik dari daftar populer</p>
        </div>
      )}
    </div>
  )
}