import React, { useEffect, useState, useCallback } from 'react'
import { Activity, Plus, Trash2, RefreshCw, AlertTriangle } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { startMonitoring, getMonitoringList, removeMonitoring, checkMonitoring } from '../../utils/api'
import clsx from 'clsx'

export default function MonitoringPage() {
  const { monitoringInput, monitoringPositions, setMonitoringPositions } = useStore()
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState({ticker:'',entry_price:'',stop_loss:'',take_profit_1:'',take_profit_2:'',take_profit_3:'',mode:'DAYTRADING'})

  useEffect(() => {
    if(monitoringInput) {
      setForm({
        ticker:monitoringInput.ticker||'',
        entry_price:monitoringInput.entry_price||'',
        stop_loss:monitoringInput.stop_loss||'',
        take_profit_1:monitoringInput.take_profit_1||monitoringInput.take_profit||'',
        take_profit_2:monitoringInput.take_profit_2||'',
        take_profit_3:monitoringInput.take_profit_3||'',
        mode:monitoringInput.mode||'DAYTRADING',
      })
      setShowForm(true)
    }
  }, [monitoringInput])

  const loadPositions = useCallback(async () => {
    try {
      const res = await getMonitoringList()
      setMonitoringPositions(res?.monitors || res?.positions || res?.data?.monitors || res?.data?.positions || res?.data || [])
    } catch {}
  }, [])

  useEffect(() => {
    loadPositions()
    const iv = setInterval(loadPositions, 15000)
    return () => clearInterval(iv)
  }, [loadPositions])

  const handleAdd = async () => {
    if(!form.ticker || !form.entry_price || !form.stop_loss) return

    const payload = {
      ticker: form.ticker.toUpperCase(),
      entry_price: Number(form.entry_price),
      stop_loss: Number(form.stop_loss),
      take_profit: Number(form.take_profit_1) || null,
      take_profit_1: Number(form.take_profit_1) || null,
      take_profit_2: Number(form.take_profit_2) || null,
      take_profit_3: Number(form.take_profit_3) || null,
      mode: form.mode,
    }

    const newPos = {
      ...payload,
      id: Date.now(),
      monitoring_id: `manual_${payload.ticker}_${Date.now()}`,
      current_price: payload.entry_price,
      status: 'HOLD',
      position: 'hold',
      pnl: 0,
      pnl_pct: 0,
      institutional_alerts: [{
        level: 'LOW',
        type: 'LOCAL_POSITION_ADDED',
        message: 'Manual position added successfully.'
      }]
    }

    const currentPositions = useStore.getState().monitoringPositions || []
    useStore.setState({
      monitoringPositions: [newPos, ...currentPositions],
      monitoringInput: null
    })

    setShowForm(false)
    setForm({ticker:'',entry_price:'',stop_loss:'',take_profit_1:'',take_profit_2:'',take_profit_3:'',mode:'DAYTRADING'})
  }

  const handleRemove = async (ticker) => {
    try { await removeMonitoring(ticker) } catch {}
    setMonitoringPositions(monitoringPositions.filter(p => p.ticker!==ticker))
  }

  return (
    <div className="p-4 lg:p-6 max-w-7xl mx-auto animate-fade-in">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="font-display font-bold text-2xl text-white tracking-wide">MONITORING TOOL</h1>
          <p className="text-slate-500 text-sm font-mono mt-0.5">Real-time P&L · Alert otomatis · Re-analysis</p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadPositions} className="btn-ghost flex items-center gap-2">
            <RefreshCw className="w-4 h-4"/>Refresh
          </button>
          <button onClick={() => setShowForm(!showForm)} className="btn-primary flex items-center gap-2">
            <Plus className="w-4 h-4"/>Add Position
          </button>
        </div>
      </div>

      {showForm && (
        <div className="card p-5 mb-5 border-accent-green/20 animate-slide-up">
          <p className="label-xs mb-4">NEW POSITION</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {[
              ['Ticker *','ticker','text','BBCA'],
              ['Entry Price *','entry_price','number','9450'],
              ['Stop Loss *','stop_loss','number','9200'],
              ['Take Profit 1','take_profit_1','number','9700'],
              ['Take Profit 2','take_profit_2','number','9950'],
              ['Take Profit 3','take_profit_3','number','10200'],
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
            <button onClick={handleAdd} disabled={loading} className="btn-primary flex items-center gap-2 disabled:opacity-50">
              {loading?<RefreshCw className="w-4 h-4 animate-spin"/>:<Plus className="w-4 h-4"/>}
              {loading?'Adding...':'Add to Monitor'}
            </button>
            <button onClick={() => setShowForm(false)} className="btn-ghost">Cancel</button>
          </div>
        </div>
      )}

      {monitoringPositions.length>0 && (
        <div className="mb-4 p-3 border border-red-500 text-red-400 text-xs font-mono overflow-auto max-h-80 bg-black/20 rounded">
          <pre>{JSON.stringify(monitoringPositions, null, 2)}</pre>
        </div>
      )}

      {monitoringPositions.length>0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {monitoringPositions.map((pos,i) => {
            const pnl = pos.pnl||pos.unrealized_pnl||0
            const pnlPct = pos.pnl_pct||pos.pnl_percent||0
            const current = pos.current_price||pos.last_price||pos.entry_price
            const status = pos.status||'HOLD'
            const pnlColor = pnl>0?'text-accent-green':pnl<0?'text-accent-red':'text-slate-400'
            const entry=pos.entry_price, sl=pos.stop_loss, tp=pos.take_profit_1
            const range = tp&&sl?tp-sl:1
            const progress = tp&&sl?Math.max(0,Math.min(100,((current-sl)/range)*100)):50
            return (
              <div key={pos.id||pos.ticker||i} className={clsx('card p-4 space-y-3',
                status==='WARNING'&&'border-accent-gold/30', status==='EXIT'&&'border-accent-red/30')}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-display font-bold text-lg text-white">{pos.ticker}</span>
                    <span className={clsx('text-xs font-mono font-semibold px-2 py-0.5 rounded border',
                      status==='HOLD'?'text-slate-400 border-slate-600/30 bg-slate-600/5':
                      status==='EXIT'?'text-accent-red border-accent-red/30 bg-accent-red/5':
                      status==='WARNING'?'text-accent-gold border-accent-gold/30 bg-accent-gold/5':
                      'text-accent-green border-accent-green/30 bg-accent-green/5')}>{status}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="label-xs">{pos.mode}</span>
                    <button onClick={() => handleRemove(pos.ticker)} className="p-1 text-slate-700 hover:text-accent-red transition-colors">
                      <Trash2 className="w-3.5 h-3.5"/>
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="label-xs">Current Price</p>
                    <p className="font-mono font-bold text-xl text-white">Rp {Number(current).toLocaleString('id-ID')}</p>
                  </div>
                  <div className="text-right">
                    <p className="label-xs">Unrealized P&L</p>
                    <p className={clsx('font-mono font-bold text-xl',pnlColor)}>{pnl>=0?'+':''}{Number(pnl).toLocaleString('id-ID')}</p>
                    <p className={clsx('font-mono text-xs',pnlColor)}>{pnlPct>=0?'+':''}{Number(pnlPct).toFixed(2)}%</p>
                  </div>
                </div>
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
                <div className="grid grid-cols-3 gap-2">
                  {[['Entry',pos.entry_price,'text-slate-300'],['SL',pos.stop_loss,'text-accent-red'],['TP1',pos.take_profit_1,'text-accent-green']].map(([lbl,val,c]) => (
                    <div key={lbl} className="bg-bg-secondary rounded p-2 text-center">
                      <p className="label-xs mb-0.5">{lbl}</p>
                      <p className={clsx('font-mono text-xs font-bold',c)}>{val?Number(val).toLocaleString('id-ID'):'—'}</p>
                    </div>
                  ))}
                </div>
                {pos.engine_context && (
                  <div className="bg-bg-secondary border border-border-dim rounded p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="label-xs">INSTITUTIONAL ENGINE CONTEXT</p>
                      <span className="text-[10px] font-mono text-accent-green border border-accent-green/30 bg-accent-green/5 px-2 py-0.5 rounded">
                        {pos.engine_context.total_engines || 34} ENGINES
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                      <div>
                        <p className="text-slate-600">Score</p>
                        <p className="text-white font-bold">
                          {pos.engine_context.composite_score ?? '—'}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-600">Signal</p>
                        <p className="text-white font-bold uppercase">
                          {pos.engine_context.signal || '—'}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-600">RAG</p>
                        <p className={pos.engine_context.rag_used ? 'text-accent-green font-bold' : 'text-slate-500'}>
                          {pos.engine_context.rag_used ? `ACTIVE (${pos.engine_context.rag_context_count || 0})` : 'OFF'}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-600">Bandarmology</p>
                        <p className={pos.engine_context.bandarmology_included ? 'text-accent-green font-bold' : 'text-slate-500'}>
                          {pos.engine_context.bandarmology_included ? 'ACTIVE' : 'OFF'}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {pos.institutional_alerts?.length>0 && pos.institutional_alerts.slice(0,2).map((a,j) => (
                  <div key={`inst-${j}`} className="flex items-center gap-2 text-xs font-mono text-accent-gold bg-accent-gold/5 border border-accent-gold/20 rounded px-2 py-1">
                    <AlertTriangle className="w-3 h-3 shrink-0"/>{a.message||a}
                  </div>
                ))}

                <pre className="text-[9px] text-slate-500 overflow-auto max-h-40 bg-black/20 p-2 rounded">
{JSON.stringify(pos, null, 2)}
                </pre>

                {pos.alerts?.length>0 && pos.alerts.slice(0,2).map((a,j) => (
                  <div key={j} className="flex items-center gap-2 text-xs font-mono text-accent-gold bg-accent-gold/5 border border-accent-gold/20 rounded px-2 py-1">
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
