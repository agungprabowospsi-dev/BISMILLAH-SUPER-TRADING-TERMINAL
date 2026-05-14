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
      body: JSON.stringify({
        ticker: pos.ticker,
        entry_price: pos.entry_price,
        stop_loss: pos.stop_loss,
        take_profit: pos.take_profit_1 || pos.entry_price,
        mode: pos.mode
      })
    })
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

export default function MonitoringPage() {
  const [positions, setPositions] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      return saved ? JSON.parse(saved) : []
    } catch { return [] }
  })
  const [showForm, setShowForm] = useState(false)
  const [backendOnline, setBackendOnline] = useState(null)
  const [expandedEngines, setExpandedEngines] = useState({})
  const toggleEngines = (id) => setExpandedEngines(prev => ({...prev, [id]: !prev[id]}))
  const [form, setForm] = useState({
    ticker: '', entry_price: '', stop_loss: '',
    take_profit_1: '', take_profit_2: '', take_profit_3: '', mode: 'DAYTRADING'
  })
  const positionsRef = useRef([])
  const { monitoringInput, setMonitoringInput } = useStore()

  useEffect(() => {
    const pending = localStorage.getItem('pendingMonitor')
    if (!pending) return
    try {
      const data = JSON.parse(pending)
      localStorage.removeItem('pendingMonitor')
      setForm({
        ticker: data.ticker || '',
        entry_price: String(data.entry_price || ''),
        stop_loss: String(data.stop_loss || ''),
        take_profit_1: String(data.take_profit_1 || ''),
        take_profit_2: String(data.take_profit_2 || ''),
        take_profit_3: String(data.take_profit_3 || ''),
        mode: data.mode?.toUpperCase() || 'DAYTRADING'
      })
      setShowForm(true)
    } catch(e) { console.error(e) }
  }, [])

  useEffect(() => { positionsRef.current = positions }, [positions])

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(positions))
    } catch { }
  }, [positions])

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
      status,
      institutional_alerts: engine?.institutional_alerts ?? pos.institutional_alerts,
      engine_context: engine?.engine_context ?? pos.engine_context,
      smart_trailing_stop: engine?.smart_trailing_stop ?? pos.smart_trailing_stop,
      warnings: engine?.warnings ?? pos.warnings,
      rr: engine?.rr ?? pos.rr,
    }
  }

  useEffect(() => {
    const poll = setInterval(async () => {
      const current = positionsRef.current
      if (!current.length) return
      const updated = await Promise.all(current.map(refreshOne))
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
    const newPos = {
      id: Date.now(),
      ticker,
      entry_price: entry,
      stop_loss: sl,
      take_profit_1: parseFloat(form.take_profit_1) || null,
      take_profit_2: parseFloat(form.take_profit_2) || null,
      take_profit_3: parseFloat(form.take_profit_3) || null,
      mode: form.mode,
      current_price: entry,
      name: ticker,
      status: 'HOLD',
      pnl: 0, pnl_pct: 0,
      institutional_alerts: [], engine_context: null, warnings: [], rr: null,
    }
    setShowForm(false)
    setForm({ ticker:'',entry_price:'',stop_loss:'',take_profit_1:'',take_profit_2:'',take_profit_3:'',mode:'DAYTRADING' })
    const enriched = await refreshOne(newPos)
    setPositions(prev => [enriched, ...prev])
  }

  const handleRemove = (id) => setPositions(prev => prev.filter(p => p.id !== id))

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
        <button onClick={() => { localStorage.removeItem("bismillah_positions"); window.location.reload(); }} className="btn-ghost flex items-center gap-1 text-xs mr-2">🗑 Reset</button>
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
                {['SWING','DAYTRADING','SCALPING'].map(m => <option key={m} value={m}>{m}</option>)}
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
                    {pos.name && pos.name !== pos.ticker && (
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

                {/* Engine Context */}
                {pos.engine_context && (
                  <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="label-xs">34 ENGINE CONTEXT</p>
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
                      <div><p className="text-slate-600">Engines</p><p className="text-white font-bold">{pos.engine_context.total_engines||34}</p></div>
                    </div>
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

                {/* Broker & Foreign Flow Data */}
                {pos.engine_context?.engine_details && (
                  (() => {
                    const bandar = pos.engine_context.engine_details.BandarmologyEngine
                    const foreign = pos.engine_context.engine_details.ForeignFlowEngine
                    const ob = pos.engine_context.engine_details.OrderbookEngine
                    if (!bandar && !foreign && !ob) return null
                    return (
                      <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                        <p className="label-xs">SMART MONEY DATA</p>
                        <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                          {foreign?.data && (
                            <>
                              <div>
                                <p className="text-slate-600">Foreign Flow</p>
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
                    w.level==='HIGH'?'text-accent-red bg-accent-red/5 border border-accent-red/20':
                    w.level==='MEDIUM'?'text-accent-gold bg-accent-gold/5 border border-accent-gold/20':
                    'text-slate-400 bg-slate-600/5 border border-slate-600/20'}`}>
                    <AlertTriangle className="w-3 h-3 shrink-0"/>
                    <span className="font-bold mr-1">[{w.level||'INFO'}]</span>{w.message||w}
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
