import MonitoringEnhancementPanel from "./MonitoringEnhancementPanel"
import React, { useState, useEffect, useRef } from 'react'
import { useStore } from '../../stores/useStore'
import { Activity, Plus, Trash2, AlertTriangle, WifiOff, ChevronDown, ChevronUp, Brain } from 'lucide-react'
import clsx from 'clsx'

const BACKEND = 'https://backend-production-daed.up.railway.app'
const POLL_INTERVAL = 15000
const STORAGE_KEY = 'bismillah_positions'

async function fetchMarketData(ticker) {
  try {
    const res = await fetch(`${BACKEND}/api/analytic/market-context/${ticker}`)
    if (!res.ok) return null
    const data = await res.json()
    return {
      price: data?.price?.last || null,
      name: data?.company?.name || ticker,
      change: data?.price?.change || 0,
      change_pct: data?.price?.change_pct || 0,
      volume_signal: data?.volume?.signal || null,
      trend: data?.technical?.trend || null,
    }
  } catch { return null }
}

async function fetchEngineData(pos) {
  try {
    const res = await fetch(`${BACKEND}/api/monitoring/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildMonitoringPayload(pos))
    })
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

function formatBil(value) {
  const num = Number(value || 0)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toLocaleString('id-ID', { maximumFractionDigits: 2 })}B`
}

function normalizeEngineScores(scores) {
  if (Array.isArray(scores)) {
    return Object.fromEntries(scores.map((e) => [e.engine || e.name || 'unknown', Number(e.score || 0)]))
  }
  if (scores && typeof scores === 'object') return scores
  return {}
}

function warningLevel(level) {
  return String(level || 'LOW').toUpperCase()
}

function buildMonitoringPayload(pos) {
  return {
    monitoring_id: pos.monitoring_id || pos.id,
    ticker: pos.ticker,
    entry_price: Number(pos.entry_price || 0),
    stop_loss: Number(pos.stop_loss || 0),
    take_profit: Number(pos.take_profit || pos.take_profit_1 || pos.entry_price || 0),
    take_profit_1: Number(pos.take_profit_1 || pos.take_profit || 0),
    take_profit_2: Number(pos.take_profit_2 || 0),
    take_profit_3: Number(pos.take_profit_3 || 0),
    mode: String(pos.mode || 'intraday').toLowerCase(),
    current_price: Number(pos.current_price || pos.entry_price || 0),
    lot: Number(pos.lot || 1),
    broker: pos.broker || '',
    entry_score: Number(pos.entry_score || pos.final_score || 0),
    final_score: Number(pos.final_score || pos.entry_score || 50),
    engine_scores: normalizeEngineScores(pos.engine_scores || {}),
    market_regime: pos.market_regime || 'SIDEWAYS',
    lq45_change: Number(pos.lq45_change || 0),
    breadth_ratio: Number(pos.breadth_ratio || 50),
    kb_context: pos.kb_context || '',
    analytic_context: pos.analytic_context || {},
    empirical_memory: pos.empirical_memory || pos.analytic_context?.empirical_memory || null,
    name: pos.name || pos.ticker,
    status: pos.status || 'HOLD',
    created_at: pos.created_at,
  }
}

function normalizeServerPosition(pos) {
  const normalized = {
    ...pos,
    id: pos.monitoring_id || pos.id || `${pos.ticker}_${pos.mode}_${pos.entry_price}`,
    monitoring_id: pos.monitoring_id || pos.id,
    take_profit_1: pos.take_profit_1 || pos.take_profit || null,
    take_profit_2: pos.take_profit_2 || null,
    take_profit_3: pos.take_profit_3 || null,
    lot: Number(pos.lot || 1),
    modal: pos.modal || Number(pos.entry_price || 0) * Number(pos.lot || 1) * 100,
    engine_scores: normalizeEngineScores(pos.engine_scores || {}),
    analytic_context: pos.analytic_context || {},
    empirical_memory: pos.empirical_memory || pos.analytic_context?.empirical_memory || null,
  }
  return normalized
}

async function fetchServerPositions() {
  const res = await fetch(`${BACKEND}/api/monitoring/active`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function startServerPosition(pos) {
  const res = await fetch(`${BACKEND}/api/monitoring/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildMonitoringPayload(pos))
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function removeServerPosition(pos) {
  const res = await fetch(`${BACKEND}/api/monitoring/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ monitoring_id: pos.monitoring_id || pos.id, ticker: pos.ticker })
  })
  if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`)
}

async function clearServerPositions() {
  const res = await fetch(`${BACKEND}/api/monitoring/clear`, { method: 'POST' })
  if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`)
}

export default function MonitoringPage() {
  const [positions, setPositions] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      return saved ? JSON.parse(saved) : []
    } catch { return [] }
  })
  const [showForm, setShowForm] = useState(() => !!useStore.getState().monitoringInput)
  const [backendOnline, setBackendOnline] = useState(null)
  const [expandedEngines, setExpandedEngines] = useState({})
  const toggleEngines = (id) => setExpandedEngines(prev => ({...prev, [id]: !prev[id]}))
  const [form, setForm] = useState(() => {
    const mi = useStore.getState().monitoringInput
    if (mi) return {
      ticker: mi.ticker || '',
      entry_price: String(mi.entry_price || ''),
      stop_loss: String(mi.stop_loss || ''),
      take_profit_1: String(mi.take_profit_1 || ''),
      take_profit_2: String(mi.take_profit_2 || ''),
      take_profit_3: String(mi.take_profit_3 || ''),
      mode: (mi.mode || 'INTRADAY').toUpperCase(),
      lot: String(mi.lot || ''),
      broker: mi.broker || ''
    }
    return { ticker: '', entry_price: '', stop_loss: '', take_profit_1: '', take_profit_2: '', take_profit_3: '', mode: 'INTRADAY', lot: '', broker: '', entry_score: '' }
  })
  const positionsRef = useRef([])
  const { monitoringInput, setMonitoringInput } = useStore()


  useEffect(() => {
    if (!monitoringInput) return
    setForm({
      ticker: monitoringInput.ticker || '',
      entry_price: String(monitoringInput.entry_price || ''),
        stop_loss: String(monitoringInput.stop_loss || ''),
        take_profit_1: String(monitoringInput.take_profit_1 || ''),
        take_profit_2: String(monitoringInput.take_profit_2 || ''),
        take_profit_3: String(monitoringInput.take_profit_3 || ''),
        mode: (monitoringInput.mode || 'INTRADAY').toUpperCase(),
        lot: String(monitoringInput.lot || ''),
        broker: monitoringInput.broker || '',
        entry_score: String(monitoringInput.final_score || monitoringInput.entry_score || '')
      })
    setShowForm(true)
  }, [monitoringInput])


  useEffect(() => { positionsRef.current = positions }, [positions])

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(positions))
    } catch { }
  }, [positions])

  useEffect(() => {
    let cancelled = false
    const syncServerState = async () => {
      try {
        const data = await fetchServerPositions()
        if (cancelled) return
        const serverPositions = (data.monitors || []).map(normalizeServerPosition)
        if (serverPositions.length > 0) {
          setBackendOnline(true)
          setPositions(serverPositions)
          return
        }
        const localPositions = positionsRef.current
        if (localPositions.length > 0) {
          await Promise.all(localPositions.map((pos) => startServerPosition(pos).catch(() => null)))
          setBackendOnline(true)
        }
      } catch {
        if (!cancelled) setBackendOnline(false)
      }
    }
    syncServerState()
    return () => { cancelled = true }
  }, [])

  const refreshOne = async (pos) => {
    const [market, engine] = await Promise.all([
      fetchMarketData(pos.ticker),
      fetchEngineData(pos)
    ])
    const price = market?.price || pos.current_price || pos.entry_price
    const pnlAmt = price - pos.entry_price
    const pnlPct = (pnlAmt / pos.entry_price) * 100
    let status = 'HOLD'
    if (price <= pos.stop_loss) status = 'EXIT'
    else if (pos.take_profit_1 && price >= pos.take_profit_1) status = 'TP HIT'
    else if (engine?.position === 'warning') status = 'WARNING'
    if (market) setBackendOnline(true)
    return {
      ...pos,
      current_price: price,
      name: market?.name || pos.name || pos.ticker,
      trend: market?.trend || pos.trend,
      volume_signal: market?.volume_signal || pos.volume_signal,
      pnl: pnlAmt,
      pnl_pct: pnlPct,
      pnl_rupiah: pnlAmt * (pos.lot || 1) * 100,
      status,
      institutional_alerts: engine?.institutional_alerts ?? pos.institutional_alerts,
      engine_context: engine?.engine_context ?? pos.engine_context,
      smart_trailing_stop: engine?.smart_trailing_stop ?? pos.smart_trailing_stop,
      warnings: engine?.warnings ?? pos.warnings,
      rr: engine?.rr ?? pos.rr,
      analytic_context: engine?.analytic_context ?? pos.analytic_context,
      empirical_memory: engine?.empirical_memory ?? pos.empirical_memory,
    }
  }

  useEffect(() => {
    const poll = setInterval(async () => {
      const current = positionsRef.current
      if (!current.length) return
      const updated = await Promise.all(current.map(async (pos) => (await refreshOne(pos)) || pos))
      setPositions(updated)
    }, POLL_INTERVAL)
    return () => clearInterval(poll)
  }, [])

  const handleAdd = async () => {
    const ticker = form.ticker.trim().toUpperCase()
    const entry = parseFloat(form.entry_price)
    const sl = parseFloat(form.stop_loss)
    if (!ticker || isNaN(entry) || isNaN(sl)) {
      alert('Ticker, Entry Price, dan Stop Loss wajib diisi!')
      return
    }
    const inputCtx = useStore.getState().monitoringInput || {}
    const newPos = {
      id: Date.now(),
      ticker,
      entry_price: entry,
      stop_loss: sl,
      take_profit_1: parseFloat(form.take_profit_1) || null,
      take_profit_2: parseFloat(form.take_profit_2) || null,
      take_profit_3: parseFloat(form.take_profit_3) || null,
      mode: form.mode.toLowerCase(),
      current_price: entry,
      lot: parseFloat(form.lot) || 1,
      broker: form.broker || '',
      entry_score: parseFloat(form.entry_score) || 0,
      modal: entry * (parseFloat(form.lot) || 1) * 100,
      name: ticker,
      status: 'HOLD',
      pnl: 0, pnl_pct: 0,
      institutional_alerts: [], engine_context: null, warnings: [], rr: null,
      engine_scores: normalizeEngineScores(inputCtx.engine_scores || {}),
      market_regime: inputCtx.market_regime || 'SIDEWAYS',
      lq45_change: inputCtx.lq45_change || 0,
      breadth_ratio: inputCtx.breadth_ratio || 50,
      final_score: inputCtx.final_score || 50.0,
      kb_context: inputCtx.kb_context || '',
      analytic_context: inputCtx.analytic_context || {},
      empirical_memory: inputCtx.analytic_context?.empirical_memory || null,
    }
    setMonitoringInput(null)
    setShowForm(false)
    setForm({ ticker:'',entry_price:'',stop_loss:'',take_profit_1:'',take_profit_2:'',take_profit_3:'',mode:'INTRADAY',lot:'',broker:'',entry_score:'' })
    let serverPos = newPos
    try {
      const saved = await startServerPosition(newPos)
      serverPos = normalizeServerPosition(saved.position || { ...newPos, monitoring_id: saved.monitoring_id })
      setBackendOnline(true)
    } catch {
      setBackendOnline(false)
    }
    const enriched = (await refreshOne(serverPos)) || serverPos
    setPositions(prev => {
      const next = [enriched, ...prev]
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)) } catch {}
      return next
    })
  }

  const handleRemove = async (id) => {
    const target = positionsRef.current.find(p => p.id === id || p.monitoring_id === id)
    setPositions(prev => prev.filter(p => p.id !== id && p.monitoring_id !== id))
    if (target) {
      try {
        await removeServerPosition(target)
        setBackendOnline(true)
      } catch {
        setBackendOnline(false)
      }
    }
  }

  const handleReset = async () => {
    try {
      await clearServerPositions()
      setBackendOnline(true)
    } catch {
      setBackendOnline(false)
    }
    localStorage.removeItem(STORAGE_KEY)
    setPositions([])
  }

  return (
    <div className="p-4 lg:p-6 max-w-7xl mx-auto animate-fade-in">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="font-display font-bold text-2xl text-white tracking-wide">MONITORING TOOL</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-slate-500 text-sm font-mono">Real-time P&L · Alert otomatis · Re-analysis</p>
            {backendOnline === true && (
              <span className="flex items-center gap-1.5 text-[10px] font-mono text-accent-green">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-green opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-green"></span>
                </span>
                LIVE
              </span>
            )}
            {backendOnline === false && (
              <span className="flex items-center gap-1 text-[10px] font-mono text-accent-red">
                <WifiOff className="w-3 h-3"/>OFFLINE
              </span>
            )}
          </div>
        </div>
        <button onClick={handleReset} className="btn-ghost flex items-center gap-1 text-xs mr-2">Reset</button>
        <button onClick={() => setShowForm(!showForm)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4"/>Add Position
        </button>
      </div>

      {showForm && (
        <div className="card p-5 mb-5 border-accent-green/20 animate-slide-up">
          <p className="label-xs mb-4">NEW POSITION</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {[
              ['Ticker *','ticker','text','BBCA'],
              ['Entry Price *','entry_price','text','6125'],
              ['Stop Loss *','stop_loss','text','5900'],
              ['Take Profit 1','take_profit_1','text','6400'],
              ['Take Profit 2','take_profit_2','text','6700'],
              ['Take Profit 3','take_profit_3','text','7000'],
              ['Lot (lembar/100) *','lot','text','10'],
              ['Broker','broker','text','BCA Sekuritas'],
              ['Entry Score (0-100)','entry_score','text','70'],
            ].map(([label,key,type,ph]) => (
              <div key={key}>
                <label className="label-xs block mb-1.5">{label}</label>
                <input type={type} value={form[key]} placeholder={ph}
                  onChange={(e) => setForm({...form,[key]:key==='ticker'?e.target.value.toUpperCase():e.target.value})}
                  className="w-full bg-bg-secondary border border-border-dim rounded px-3 py-2 font-mono text-sm text-white placeholder-slate-700 focus:border-accent-green focus:outline-none"/>
              </div>
            ))}
            <div>
              <label className="label-xs block mb-1.5">Mode</label>
              <select value={form.mode} onChange={(e) => setForm({...form,mode:e.target.value})}
                className="w-full bg-bg-secondary border border-border-dim rounded px-3 py-2 font-mono text-sm text-white focus:border-accent-green focus:outline-none">
                {['SWING','INTRADAY','SCALPING'].map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={handleAdd} className="btn-primary flex items-center gap-2">
              <Plus className="w-4 h-4"/>Add to Monitor
            </button>
            <button onClick={() => setShowForm(false)} className="btn-ghost">Cancel</button>
          </div>
        </div>
      )}

      {positions.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {positions.map((pos, i) => {
            const pnl = pos.pnl || 0
            const pnlPct = pos.pnl_pct || 0
            const current = pos.current_price || pos.entry_price
            const status = pos.status || 'HOLD'
            const pnlColor = pnl > 0 ? 'text-accent-green' : pnl < 0 ? 'text-accent-red' : 'text-slate-400'
            const sl = pos.stop_loss, tp = pos.take_profit_1, entry = pos.entry_price
            const range = tp && sl ? tp - sl : 1
            const progress = tp && sl ? Math.max(0, Math.min(100, ((current - sl) / range) * 100)) : 50

            return (
              <div key={pos.id || i} className={clsx('card p-4 space-y-3',
                status==='WARNING'&&'border-accent-gold/30',
                status==='EXIT'&&'border-accent-red/30',
                status==='TP HIT'&&'border-accent-green/30')}>

                {/* Header */}
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-display font-bold text-lg text-white">{pos.ticker}</span>
                      <span className={clsx('text-xs font-mono font-semibold px-2 py-0.5 rounded border',
                        status==='HOLD'?'text-slate-400 border-slate-600/30 bg-slate-600/5':
                        status==='EXIT'?'text-accent-red border-accent-red/30 bg-accent-red/5':
                        status==='TP HIT'?'text-accent-green border-accent-green/30 bg-accent-green/5':
                        status==='WARNING'?'text-accent-gold border-accent-gold/30 bg-accent-gold/5':
                        'text-slate-400 border-slate-600/30 bg-slate-600/5')}>{status}</span>
                    </div>
                    {pos.name && (
                      <p className="text-[10px] font-mono text-slate-500 mt-0.5">{pos.name}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="label-xs">{pos.mode}</span>
                    <button onClick={() => handleRemove(pos.id)} className="p-1 text-slate-700 hover:text-accent-red transition-colors">
                      <Trash2 className="w-3.5 h-3.5"/>
                    </button>
                  </div>
                </div>

                {/* Price & PnL */}
                <div className="flex items-center justify-between">
                  <div>
                    <p className="label-xs">Current Price</p>
                    <p className="font-mono font-bold text-xl text-accent-green">Rp {Number(current).toLocaleString('id-ID')}</p>
                    {pos.trend && <p className="text-[10px] font-mono text-slate-500 mt-0.5">{pos.trend}</p>}
                  </div>
                  <div className="text-right">
                    <p className="label-xs">Unrealized P&L</p>
                    <p className={clsx('font-mono font-bold text-xl',pnlColor)}>
                      {pnl >= 0 ? '+' : ''}{Number(pnl).toLocaleString('id-ID')}
                    </p>
                    <p className={clsx('font-mono text-xs',pnlColor)}>{pnlPct>=0?'+':''}{Number(pnlPct).toFixed(2)}%</p>
                  </div>
                </div>

                {/* Progress Bar */}
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px] font-mono text-slate-600">
                    <span>SL {Number(sl||0).toLocaleString('id-ID')}</span>
                    <span>Entry {Number(entry||0).toLocaleString('id-ID')}</span>
                    {tp&&<span>TP {Number(tp).toLocaleString('id-ID')}</span>}
                  </div>
                  <div className="h-2 bg-border-dim rounded-full overflow-hidden relative">
                    <div className="absolute left-0 top-0 h-full bg-accent-red/20" style={{width:'50%'}}/>
                    <div className="absolute right-0 top-0 h-full bg-accent-green/20" style={{width:'50%'}}/>
                    <div className="absolute top-0 h-full w-0.5 bg-white transition-all duration-500" style={{left:`${progress}%`}}/>
                  </div>
                </div>

                {/* Entry/SL/TP Cards */}
                <div className="grid grid-cols-3 gap-2">
                  {[['Entry',pos.entry_price,'text-slate-300'],['SL',pos.stop_loss,'text-accent-red'],['TP1',pos.take_profit_1,'text-accent-green']].map(([lbl,val,c]) => (
                    <div key={lbl} className="bg-bg-secondary rounded p-2 text-center">
                      <p className="label-xs mb-0.5">{lbl}</p>
                      <p className={clsx('font-mono text-xs font-bold',c)}>{val?Number(val).toLocaleString('id-ID'):'—'}</p>
                    </div>
                  ))}
                </div>

                {/* TP2 & TP3 */}
                {(pos.take_profit_2 || pos.take_profit_3) && (
                  <div className="grid grid-cols-2 gap-2">
                    {pos.take_profit_2 && (
                      <div className="bg-bg-secondary rounded p-2 text-center">
                        <p className="label-xs mb-0.5">TP2</p>
                        <p className="font-mono text-xs font-bold text-accent-green">{Number(pos.take_profit_2).toLocaleString('id-ID')}</p>
                      </div>
                    )}
                    {pos.take_profit_3 && (
                      <div className="bg-bg-secondary rounded p-2 text-center">
                        <p className="label-xs mb-0.5">TP3</p>
                        <p className="font-mono text-xs font-bold text-accent-green">{Number(pos.take_profit_3).toLocaleString('id-ID')}</p>
                      </div>
                    )}
                  </div>
                )}

                {/* R:R */}
                {pos.rr && (
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-bg-secondary rounded p-2 text-center">
                      <p className="label-xs mb-0.5">R:R Target</p>
                      <p className="font-mono text-xs font-bold text-white">1:{Number(pos.rr.rr_target||0).toFixed(1)}</p>
                    </div>
                    <div className="bg-bg-secondary rounded p-2 text-center">
                      <p className="label-xs mb-0.5">R:R Current</p>
                      <p className={clsx('font-mono text-xs font-bold',pos.rr.rr_current>0?'text-accent-green':'text-slate-400')}>
                        {Number(pos.rr.rr_current||0).toFixed(2)}
                      </p>
                    </div>
                  </div>
                )}

                {/* Modal & Forward Test Info */}
                <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                  <p className="label-xs text-accent-gold">💰 FORWARD TEST INFO</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className="label-xs">Modal</p>
                      <p className="font-mono text-xs font-bold text-white">Rp {Number((pos.modal || pos.entry_price * (pos.lot||1) * 100) || 0).toLocaleString('id-ID')}</p>
                    </div>
                    <div>
                      <p className="label-xs">Lot</p>
                      <p className="font-mono text-xs font-bold text-white">{pos.lot || 1} lot ({((pos.lot||1)*100).toLocaleString('id-ID')} lembar)</p>
                    </div>
                    <div>
                      <p className="label-xs">P&L Rupiah</p>
                      <p className={clsx('font-mono text-xs font-bold', (pos.pnl_rupiah||pos.pnl*100) > 0 ? 'text-accent-green' : (pos.pnl_rupiah||pos.pnl*100) < 0 ? 'text-accent-red' : 'text-slate-400')}>
                        {(pos.pnl_rupiah||0) >= 0 ? '+' : ''}Rp {Number(pos.pnl_rupiah || (pos.pnl * (pos.lot||1) * 100) || 0).toLocaleString('id-ID')}
                      </p>
                    </div>
                    {pos.broker && <div>
                      <p className="label-xs">Broker</p>
                      <p className="font-mono text-xs font-bold text-white">{pos.broker}</p>
                    </div>}
                  </div>
                </div>

                {pos.analytic_context && Object.keys(pos.analytic_context).length > 0 && (
                  <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="label-xs">ANALYTIC DECISION</p>
                      <span className={clsx('text-[10px] font-mono font-bold px-2 py-0.5 rounded border',
                        pos.analytic_context.go_no_go === 'STRONG GO' || pos.analytic_context.go_no_go === 'GO'
                          ? 'text-accent-green border-accent-green/30 bg-accent-green/5'
                          : pos.analytic_context.go_no_go === 'NO GO'
                          ? 'text-accent-red border-accent-red/30 bg-accent-red/5'
                          : 'text-accent-gold border-accent-gold/30 bg-accent-gold/5')}>
                        {pos.analytic_context.go_no_go || 'WAIT'}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                      <div>
                        <p className="text-slate-600">Confidence</p>
                        <p className="text-white font-bold">{Number(pos.analytic_context.go_confidence || 0).toFixed(0)}%</p>
                      </div>
                      <div>
                        <p className="text-slate-600">Win Prob</p>
                        <p className="text-white font-bold">
                          {typeof pos.analytic_context.win_probability === 'object'
                            ? `${Number(pos.analytic_context.win_probability.probability || 0).toFixed(0)}%`
                            : `${Number(pos.analytic_context.win_probability || 0).toFixed(0)}%`}
                        </p>
                      </div>
                    </div>
                    {pos.analytic_context.action_plan && (
                      (() => {
                        const opp = pos.analytic_context.action_plan.opportunity_execution || pos.analytic_context.opportunity_execution || null
                        const radar = pos.analytic_context.action_plan.watchlist_alignment || pos.analytic_context.watchlist_alignment || null
                        return (
                          <div className="space-y-2 pt-2 border-t border-border-dim text-xs font-mono">
                            <div className="grid grid-cols-2 gap-2">
                              <div>
                                <p className="text-slate-600">Setup</p>
                                <p className="text-white font-bold uppercase">
                                  {String(pos.analytic_context.action_plan.setup_type || pos.analytic_context.setup_type || '-').replace(/_/g, ' ')}
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-600">Order</p>
                                <p className="text-accent-blue font-bold uppercase">
                                  {String(pos.analytic_context.action_plan.order_type || '-').replace(/_/g, ' ')}
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-600">Trigger</p>
                                <p className="text-accent-gold font-bold">
                                  Rp {Number(pos.analytic_context.action_plan.trigger_price || 0).toLocaleString('id-ID')}
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-600">Invalidation</p>
                                <p className="text-accent-red font-bold">
                                  Rp {Number(pos.analytic_context.action_plan.invalidation_price || 0).toLocaleString('id-ID')}
                                </p>
                              </div>
                            </div>
                            {opp?.active && (
                              <div className="rounded border border-sky-400/30 bg-sky-400/10 p-2 text-sky-300">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-bold uppercase">Opportunity Watch</span>
                                  <span className="font-bold">{Number(opp.change_pct || 0).toFixed(2)}%</span>
                                </div>
                                <p className="mt-1 text-sky-200/90">
                                  {String(opp.execution_bias || '').replace(/_/g, ' ')}. Monitoring fokus pada trigger, VWAP/base, orderbook, dan flow reversal.
                                </p>
                              </div>
                            )}
                            {radar?.active && !opp?.active && (
                              <div className="rounded border border-amber-400/30 bg-amber-400/10 p-2 text-amber-300">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-bold uppercase">Watchlist Radar</span>
                                  <span className="font-bold">{Number(radar.change_pct || 0).toFixed(2)}%</span>
                                </div>
                                <p className="mt-1 text-amber-200/90">
                                  Belum execution lane. Upgrade jika move 5% atau lebih, RVOL/frequency/value hidup, dan trigger terkonfirmasi.
                                </p>
                              </div>
                            )}
                          </div>
                        )
                      })()
                    )}
                    {(pos.analytic_context.orderbook_execution || pos.analytic_context.action_plan?.orderbook_execution) && (
                      (() => {
                        const obx = pos.analytic_context.orderbook_execution || pos.analytic_context.action_plan?.orderbook_execution
                        return (
                          <div className="pt-2 border-t border-border-dim text-xs font-mono space-y-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-slate-600">Orderbook Execution</p>
                              <p className="text-cyan-300 font-bold uppercase text-right">
                                {String(obx.execution_recommendation || 'USE_EXISTING_PLAN').replace(/_/g, ' ')}
                              </p>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                              <div><p className="text-slate-600">Liquidity</p><p className="text-white font-bold uppercase">{String(obx.liquidity_bias || '-').replace(/_/g, ' ')}</p></div>
                              <div><p className="text-slate-600">Spread</p><p className="text-white font-bold uppercase">{String(obx.spread_health || '-').replace(/_/g, ' ')}</p></div>
                              <div><p className="text-slate-600">Bid/Ask</p><p className="text-white font-bold">{Number(obx.bid_ask_ratio || 0).toFixed(2)}x</p></div>
                              <div><p className="text-slate-600">Limit</p><p className="text-accent-green font-bold">Rp {Number(obx.suggested_limit_entry || 0).toLocaleString('id-ID')}</p></div>
                            </div>
                            {obx.reason && <p className="text-slate-400 leading-relaxed">{obx.reason}</p>}
                          </div>
                        )
                      })()
                    )}
                  </div>
                )}

                {pos.empirical_memory && (
                  <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="label-xs">15Y HISTORICAL MEMORY</p>
                      <span className={clsx('text-[10px] font-mono font-bold px-2 py-0.5 rounded border',
                        pos.empirical_memory.available
                          ? 'text-accent-green border-accent-green/30 bg-accent-green/5'
                          : 'text-accent-gold border-accent-gold/30 bg-accent-gold/5')}>
                        {pos.empirical_memory.available ? 'ACTIVE' : 'LEARNING'}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                      <div><p className="text-slate-600">Pattern</p><p className="text-white font-bold">{pos.empirical_memory.pattern_key || '-'}</p></div>
                      <div><p className="text-slate-600">Sample</p><p className="text-white font-bold">{pos.empirical_memory.sample_count || '-'}</p></div>
                      <div><p className="text-slate-600">Winrate</p><p className="text-white font-bold">{pos.empirical_memory.available ? `${Number(pos.empirical_memory.winrate || 0).toFixed(1)}%` : '-'}</p></div>
                      <div><p className="text-slate-600">Expectancy</p><p className="text-white font-bold">{pos.empirical_memory.available ? `${Number(pos.empirical_memory.expectancy_pct || 0).toFixed(2)}%` : '-'}</p></div>
                    </div>
                  </div>
                )}

                {/* Engine Context */}
                {pos.engine_context && (
                  <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="label-xs">MONITORING ENGINE CONTEXT</p>
                      <span className="text-[10px] font-mono text-accent-green border border-accent-green/30 bg-accent-green/5 px-2 py-0.5 rounded">
                        Score: {Number(pos.engine_context.composite_score||0).toFixed(1)}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                      <div><p className="text-slate-600">Signal</p><p className="text-white font-bold uppercase">{pos.engine_context.signal||'—'}</p></div>
                      <div><p className="text-slate-600">RAG</p>
                        <p className={pos.engine_context.rag_used?'text-accent-green font-bold':'text-slate-500'}>
                          {pos.engine_context.rag_used?`ACTIVE (${pos.engine_context.rag_context_count||0})`:'OFF'}
                        </p>
                      </div>
                      <div><p className="text-slate-600">Bandarmology</p>
                        <p className={pos.engine_context.bandarmology_included?'text-accent-green font-bold':'text-slate-500'}>
                          {pos.engine_context.bandarmology_included?'ACTIVE':'OFF'}
                        </p>
                      </div>
                      <div><p className="text-slate-600">BrokerBehavior</p>
                        <p className={pos.engine_context.broker_behavior_included?'text-accent-green font-bold':'text-slate-500'}>
                          {pos.engine_context.broker_behavior_included?'ACTIVE':'OFF'}
                        </p>
                      </div>
                      <div><p className="text-slate-600">Orderbook</p>
                        <p className={pos.engine_context.orderbook_included?'text-accent-green font-bold':'text-slate-500'}>
                          {pos.engine_context.orderbook_included?'ACTIVE':'OFF'}
                        </p>
                      </div>
                      <div><p className="text-slate-600">Engines</p><p className="text-white font-bold">{pos.engine_context.total_engines||8}</p></div>
                      <div>
                        <p className="text-slate-600">Bull/Bear</p>
                        <p className="text-white font-bold">
                          {Number(pos.engine_context.bullish_count || 0)}/{Number(pos.engine_context.bearish_count || 0)}
                        </p>
                      </div>
                    </div>
                    {pos.engine_context.official_enrichment?.available && (
                      <div className="border-t border-border-dim pt-2">
                        <p className="label-xs mb-2">OFFICIAL INVEZGO WARNING CONTEXT</p>
                        <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                          <div><p className="text-slate-600">Time Table</p><p className="text-white font-bold uppercase">{String(pos.engine_context.official_enrichment.time_table?.pressure || '-').replace(/_/g,' ')}</p></div>
                          <div><p className="text-slate-600">Momentum</p><p className="text-white font-bold uppercase">{String(pos.engine_context.official_enrichment.momentum_chart?.bias || '-').replace(/_/g,' ')}</p></div>
                          <div><p className="text-slate-600">Broker Stalker</p><p className="text-white font-bold">{Number(pos.engine_context.official_enrichment.broker_stalker?.available_count || 0)} active</p></div>
                          <div><p className="text-slate-600">Corp Action</p><p className="text-white font-bold">{Number(pos.engine_context.official_enrichment.corporate_actions?.count || 0)}</p></div>
                        </div>
                      </div>
                    )}
                    {pos.engine_context.money_maker?.available && (
                      <div className="border-t border-border-dim pt-2">
                        <p className="label-xs mb-2">MONEY MAKER CORE</p>
                        <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                          <div><p className="text-slate-600">Score</p><p className="text-white font-bold">{Number(pos.engine_context.money_maker.score || 0).toFixed(1)}</p></div>
                          <div><p className="text-slate-600">BFD</p><p className="text-white font-bold">{Number(pos.engine_context.money_maker.bfd_score || 0)}/5</p></div>
                          <div><p className="text-slate-600">Phase</p><p className="text-white font-bold uppercase">{String(pos.engine_context.money_maker.phase || '-').replace(/_/g,' ')}</p></div>
                          <div><p className="text-slate-600">Verdict</p><p className="text-white font-bold uppercase">{String(pos.engine_context.money_maker.verdict || '-').replace(/_/g,' ')}</p></div>
                          <div><p className="text-slate-600">Pattern</p><p className="text-white font-bold uppercase">{String(pos.engine_context.money_maker.patterns?.[0]?.name || '-').replace(/_/g,' ')}</p></div>
                          <div><p className="text-slate-600">Memory</p><p className="text-white font-bold uppercase">{pos.engine_context.money_maker.flow_memory?.flow_reversal_alert ? 'REVERSAL' : pos.engine_context.money_maker.flow_memory?.memory_available ? `${Number(pos.engine_context.money_maker.flow_memory?.bfd_delta || 0).toFixed(1)}` : '-'}</p></div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* AI Engine Rationale — Collapsible */}
                {pos.engine_context?.engine_details && Object.keys(pos.engine_context.engine_details).length > 0 && (
                  <div className="bg-bg-secondary border border-border-dim rounded overflow-hidden">
                    <button
                      onClick={() => toggleEngines(pos.id)}
                      className="w-full flex items-center justify-between px-3 py-2 hover:bg-white/5 transition-colors">
                      <div className="flex items-center gap-2">
                        <Brain className="w-3.5 h-3.5 text-accent-green"/>
                        <p className="label-xs text-accent-green">AI ENGINE RATIONALE</p>
                      </div>
                      {expandedEngines[pos.id]
                        ? <ChevronUp className="w-3.5 h-3.5 text-slate-500"/>
                        : <ChevronDown className="w-3.5 h-3.5 text-slate-500"/>}
                    </button>
                    {expandedEngines[pos.id] && (
                      <div className="px-3 pb-3 space-y-3 border-t border-border-dim pt-3">
                        {Object.entries(pos.engine_context.engine_details).map(([eng, v]) => {
                          const rationale = v?.rationale
                          if (!rationale || rationale === 'AI analysis temporarily unavailable.') return null
                          const sig = v?.signal || 'neutral'
                          const engShort = eng.replace('Engine','')
                          return (
                            <div key={eng} className="space-y-1">
                              <div className="flex items-center justify-between">
                                <p className="text-[10px] font-mono font-bold text-slate-400 uppercase">{engShort}</p>
                                <span className={clsx('text-[9px] font-mono font-bold uppercase px-1.5 py-0.5 rounded border',
                                  sig==='bullish'?'text-accent-green border-accent-green/30 bg-accent-green/5':
                                  sig==='bearish'?'text-accent-red border-accent-red/30 bg-accent-red/5':
                                  'text-slate-400 border-slate-600/30 bg-slate-600/5')}>{sig}</span>
                              </div>
                              <div className="text-[10px] font-mono text-slate-400 leading-relaxed">
                                {rationale.replace(/\*\*/g,'').replace(/#+\s/g,'').trim()}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* Broker Flow Data */}
                {pos.engine_context?.engine_details && (
                  (() => {
                    const bandar = pos.engine_context.engine_details.BandarmologyEngine
                    const brokerBehavior = pos.engine_context.engine_details.BrokerBehaviorEngine
                    const foreign = pos.engine_context.engine_details.ForeignFlowEngine
                    const ob = pos.engine_context.engine_details.OrderbookEngine
                    const behavior = brokerBehavior?.data
                    if (!bandar && !brokerBehavior && !foreign && !ob) return null
                    return (
                      <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                        <p className="label-xs">SMART MONEY DATA</p>
                        <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                          {behavior && (
                            <>
                              <div>
                                <p className="text-slate-600">Broker Behavior</p>
                                <p className={brokerBehavior.signal==='bullish'?'text-accent-green font-bold':brokerBehavior.signal==='bearish'?'text-accent-red font-bold':'text-slate-400 font-bold'}>
                                  {(behavior.pressure||'neutral').replace(/_/g,' ').toUpperCase()}
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-600">Smart Net</p>
                                <p className={Number(behavior.smart_money_net_bil)>0?'text-accent-green font-bold':Number(behavior.smart_money_net_bil)<0?'text-accent-red font-bold':'text-slate-400 font-bold'}>
                                  {formatBil(behavior.smart_money_net_bil)}
                                </p>
                              </div>
                            </>
                          )}
                          {foreign?.data && (
                            <>
                              <div>
                                <p className="text-slate-600">Broker Flow</p>
                                <p className={foreign.data.trend==='net_buy'?'text-accent-green font-bold':'text-accent-red font-bold'}>
                                  {foreign.data.trend==='net_buy'?'NET BUY ↑':'NET SELL ↓'}
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-600">Net Foreign</p>
                                <p className={Number(foreign.data.net_foreign)>0?'text-accent-green font-bold':'text-accent-red font-bold'}>
                                  {Number(foreign.data.net_foreign||0).toLocaleString('id-ID')}
                                </p>
                              </div>
                            </>
                          )}
                          {ob?.data && ob.data.bid_ask_ratio && (
                            <>
                              <div>
                                <p className="text-slate-600">Bid/Ask Ratio</p>
                                <p className={ob.data.bid_ask_ratio>1.5?'text-accent-green font-bold':ob.data.bid_ask_ratio<0.7?'text-accent-red font-bold':'text-white font-bold'}>
                                  {Number(ob.data.bid_ask_ratio||0).toFixed(2)}x
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-600">Orderbook</p>
                                <p className={ob.signal==='bullish'?'text-accent-green font-bold':ob.signal==='bearish'?'text-accent-red font-bold':'text-slate-400'}>
                                  {(ob.signal||'neutral').toUpperCase()}
                                </p>
                              </div>
                            </>
                          )}
                        </div>

                        {behavior && (
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2 border-t border-border-dim">
                            <div>
                              <p className="text-[10px] font-mono font-bold text-accent-green mb-1">TOP 5 BUYERS</p>
                              <div className="space-y-1">
                                {(behavior.top_buyers || []).slice(0, 5).map((b) => (
                                  <div key={`buy-${b.code}`} className="flex items-center justify-between text-[10px] font-mono">
                                    <span className="text-slate-300 font-bold">{b.code || b.name}</span>
                                    <span className="text-accent-green">{formatBil(b.buy_bil)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                            <div>
                              <p className="text-[10px] font-mono font-bold text-accent-red mb-1">TOP 5 SELLERS</p>
                              <div className="space-y-1">
                                {(behavior.top_sellers || []).slice(0, 5).map((b) => (
                                  <div key={`sell-${b.code}`} className="flex items-center justify-between text-[10px] font-mono">
                                    <span className="text-slate-300 font-bold">{b.code || b.name}</span>
                                    <span className="text-accent-red">{formatBil(b.sell_bil)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })()
                )}

                {/* Smart Trailing Stop */}
                {pos.smart_trailing_stop?.active && (
                  <div className="bg-accent-green/5 border border-accent-green/20 rounded p-2 text-xs font-mono">
                    <p className="text-accent-green font-bold mb-1">🔒 SMART TRAILING STOP ACTIVE</p>
                    <p className="text-slate-400">Suggested SL: <span className="text-white">{Number(pos.smart_trailing_stop.suggested_stop_loss).toLocaleString('id-ID')}</span></p>
                    <p className="text-slate-400">Stage: <span className="text-white uppercase">{pos.smart_trailing_stop.trailing_stage}</span></p>
                  </div>
                )}

                {/* Early Warning System */}
                {pos.warnings?.length > 0 && pos.warnings.map((w,j) => (
                  <div key={j} className={`flex items-center gap-2 text-xs font-mono rounded px-2 py-1 ${
                    warningLevel(w.level)==='HIGH'?'text-accent-red bg-accent-red/5 border border-accent-red/20':
                    warningLevel(w.level)==='MEDIUM'?'text-accent-gold bg-accent-gold/5 border border-accent-gold/20':
                    'text-slate-400 bg-slate-600/5 border border-slate-600/20'}`}>
                    <AlertTriangle className="w-3 h-3 shrink-0"/>
                    <span className="font-bold mr-1">[{warningLevel(w.level)}]</span>{w.message||w.msg||w}
                  </div>
                ))}

                {/* Institutional Alerts */}
                {pos.institutional_alerts?.length > 0 && pos.institutional_alerts.slice(0,2).map((a,j) => (
                  <div key={j} className={clsx('flex items-center gap-2 text-xs font-mono rounded px-2 py-1',
                    a.level==='HIGH'?'text-accent-red bg-accent-red/5 border border-accent-red/20':
                    a.level==='MEDIUM'?'text-accent-gold bg-accent-gold/5 border border-accent-gold/20':
                    'text-slate-400 bg-slate-600/5 border border-slate-600/20')}>
                    <AlertTriangle className="w-3 h-3 shrink-0"/>{a.message||a}
                  </div>
                ))}

                {/* REV22 Monitoring Enhancement Panel */}
                <div className="mt-3">
                  <MonitoringEnhancementPanel position={pos} />
                </div>

              </div>
            )
          })}
        </div>
      ) : (
        <div className="card p-12 text-center">
          <Activity className="w-12 h-12 text-slate-700 mx-auto mb-4"/>
          <p className="font-display text-lg text-slate-500 mb-1">Belum ada posisi aktif</p>
          <p className="font-mono text-sm text-slate-700">Tambah posisi atau klik "Monitor Posisi" dari Analytic Tool</p>
        </div>
      )}
    </div>
  )
}
