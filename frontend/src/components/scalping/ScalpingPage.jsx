import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Zap, Wifi, WifiOff, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { getScalpingData, getWsUrl } from '../../utils/api'
import clsx from 'clsx'

const POPULAR = ['BBCA','BBRI','TLKM','BMRI','ASII','GOTO','ANTM','INDF','ICBP','UNVR']
const SIG = {
  ENTRY:{color:'text-accent-green',bg:'bg-accent-green/10 border-accent-green/30',label:'🟢 ENTRY'},
  EXIT:{color:'text-accent-red',bg:'bg-accent-red/10 border-accent-red/30',label:'🔴 EXIT'},
  HOLD:{color:'text-slate-400',bg:'bg-slate-700/10 border-slate-700/30',label:'⬜ HOLD'},
}

export default function ScalpingPage() {
  const { scalpingTicker, setScalpingTicker } = useStore()
  const [input, setInput] = useState(scalpingTicker||'')
  const [wsStatus, setWsStatus] = useState('disconnected')
  const [data, setData] = useState(null)
  const [history, setHistory] = useState([])
  const [orderbook, setOrderbook] = useState({bids:[],asks:[]})
  const wsRef = useRef(null)
  const reconnRef = useRef(null)

  const connectWs = useCallback((ticker) => {
    if(wsRef.current) wsRef.current.close()
    if(!ticker) return
    setWsStatus('connecting')
    const ws = new WebSocket(getWsUrl(ticker))
    wsRef.current = ws
    ws.onopen = () => setWsStatus('connected')
    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        setData(prev => ({...prev,...d}))
        if(d.price) setHistory(h => [...h,{price:d.price,time:Date.now()}].slice(-60))
        if(d.orderbook) setOrderbook(d.orderbook)
      } catch {}
    }
    ws.onclose = () => {
      setWsStatus('disconnected')
      reconnRef.current = setTimeout(() => connectWs(ticker), 3000)
    }
    ws.onerror = () => setWsStatus('disconnected')
  }, [])

  const fetchData = useCallback(async (ticker) => {
    if(!ticker) return
    try {
      const res = await getScalpingData(ticker)
      setData(prev => ({...prev,...res.data}))
      if(res.data?.orderbook) setOrderbook(res.data.orderbook)
    } catch {}
  }, [])

  const handleStart = (ticker) => {
    const t = (ticker||input).toUpperCase().trim()
    if(!t) return
    setInput(t); setScalpingTicker(t)
    setData(null); setHistory([]); setOrderbook({bids:[],asks:[]})
    fetchData(t); connectWs(t)
  }

  useEffect(() => () => { wsRef.current?.close(); clearTimeout(reconnRef.current) }, [])

  useEffect(() => {
    if(!scalpingTicker) return
    const iv = setInterval(() => fetchData(scalpingTicker), 5000)
    return () => clearInterval(iv)
  }, [scalpingTicker, fetchData])

  const signal = data?.signal||'HOLD'
  const level = data?.level||'NEUTRAL'
  const price = data?.price
  const prevPrice = history[history.length-2]?.price
  const priceUp = price&&prevPrice ? price>prevPrice : null
  const cfg = SIG[signal]||SIG.HOLD

  return (
    <div className="p-4 lg:p-6 max-w-7xl mx-auto animate-fade-in">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="font-display font-bold text-2xl text-white tracking-wide flex items-center gap-2">
            <Zap className="w-6 h-6 text-accent-green"/>SCALPING TERMINAL
          </h1>
          <p className="text-slate-500 text-sm font-mono mt-0.5">WebSocket real-time · Tick data · Signal per detik</p>
        </div>
        <div className={clsx('flex items-center gap-1.5 px-3 py-1.5 rounded border font-mono text-xs',
          wsStatus==='connected'?'text-accent-green bg-accent-green/5 border-accent-green/20':
          wsStatus==='connecting'?'text-accent-gold bg-accent-gold/5 border-accent-gold/20':
          'text-slate-500 bg-bg-secondary border-border-dim')}>
          {wsStatus==='connected'?<Wifi className="w-3 h-3"/>:wsStatus==='connecting'?<RefreshCw className="w-3 h-3 animate-spin"/>:<WifiOff className="w-3 h-3"/>}
          {wsStatus==='connected'?'WS Connected':wsStatus==='connecting'?'Connecting...':'WS Offline'}
        </div>
      </div>

      <div className="card p-4 mb-5">
        <div className="flex gap-3 flex-wrap items-center">
          <input type="text" value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key==='Enter' && handleStart()}
            placeholder="TICKER" maxLength={10}
            className="w-32 bg-bg-secondary border border-border-dim rounded px-3 py-2 font-mono text-sm text-white placeholder-slate-700 focus:border-accent-green focus:outline-none uppercase"/>
          <button onClick={() => handleStart()} className="btn-primary flex items-center gap-2">
            <Zap className="w-4 h-4"/>Start
          </button>
          <div className="flex flex-wrap gap-1.5">
            {POPULAR.map(t => (
              <button key={t} onClick={() => handleStart(t)}
                className={clsx('px-2.5 py-1 rounded border text-xs font-mono transition-all duration-150',
                  scalpingTicker===t?'border-accent-green/50 bg-accent-green/5 text-accent-green':'border-border-dim text-slate-600 hover:text-slate-300 hover:border-border-bright')}>
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {scalpingTicker ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-4">
            <div className={clsx('card p-5 border rounded-lg text-center',cfg.bg)}>
              <p className="label-xs mb-3">{scalpingTicker} — SIGNAL</p>
              <div className={clsx('font-display font-bold text-4xl tracking-widest mb-1',cfg.color)}>{cfg.label}</div>
              <div className={clsx('font-mono text-xs font-semibold uppercase tracking-widest mt-2',
                level==='GOOD'?'text-accent-green':level==='BAD'?'text-accent-red':'text-slate-400')}>
                LEVEL: {level}
              </div>
              <div className={clsx('mt-3 w-3 h-3 rounded-full mx-auto',
                signal==='ENTRY'?'bg-accent-green animate-pulse':signal==='EXIT'?'bg-accent-red animate-pulse':'bg-slate-600')}/>
            </div>

            <div className="card p-4">
              <p className="label-xs mb-2">{scalpingTicker} — LIVE PRICE</p>
              {price ? (
                <>
                  <div className="flex items-center gap-2">
                    <span className={clsx('font-mono font-bold text-3xl',
                      priceUp===true?'text-accent-green':priceUp===false?'text-accent-red':'text-white')}>
                      {Number(price).toLocaleString('id-ID')}
                    </span>
                    {priceUp===true&&<TrendingUp className="w-5 h-5 text-accent-green"/>}
                    {priceUp===false&&<TrendingDown className="w-5 h-5 text-accent-red"/>}
                  </div>
                  {data?.change!==undefined&&(
                    <p className={clsx('font-mono text-sm mt-1',data.change>=0?'text-accent-green':'text-accent-red')}>
                      {data.change>=0?'+':''}{data.change} ({data.change_pct}%)
                    </p>
                  )}
                </>
              ) : <div className="shimmer h-9 w-32 rounded mt-1"/>}
              <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-border-dim">
                {[['Volume',data?.volume],['Bid',data?.bid],['Ask',data?.ask],['Spread',data?.spread]].map(([k,v]) => (
                  <div key={k}><p className="label-xs">{k}</p>
                    <p className="font-mono text-xs text-white">{v!=null?Number(v).toLocaleString('id-ID'):'—'}</p>
                  </div>
                ))}
              </div>
            </div>

            {history.length>2&&(
              <div className="card p-3">
                <p className="label-xs mb-2">Price Ticks ({history.length})</p>
                <svg width="100%" height="40" viewBox="0 0 100 40" preserveAspectRatio="none">
                  {(() => {
                    const prices=history.map(d=>d.price)
                    const min=Math.min(...prices),max=Math.max(...prices),range=max-min||1
                    const pts=prices.map((p,i)=>`${(i/(prices.length-1))*100},${40-((p-min)/range)*40}`).join(' ')
                    const up=prices[prices.length-1]>=prices[0]
                    return <polyline points={pts} fill="none" stroke={up?'#00FF88':'#FF3355'} strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
                  })()}
                </svg>
              </div>
            )}
          </div>

          <div className="card p-4">
            <p className="label-xs mb-3">ORDER BOOK</p>
            <p className="label-xs text-accent-red mb-1">ASKS (Jual)</p>
            <div className="space-y-0.5 mb-2">
              {(orderbook.asks||[]).slice(0,8).map((a,i) => {
                const price=a.price||a[0],vol=a.volume||a[1]||0
                const max=Math.max(...(orderbook.asks||[]).map(x=>x.volume||x[1]||0),1)
                return (
                  <div key={i} className="relative flex items-center justify-between px-2 py-0.5 rounded overflow-hidden">
                    <div className="absolute right-0 top-0 h-full bg-accent-red/10 rounded" style={{width:`${(vol/max)*100}%`}}/>
                    <span className="font-mono text-xs text-accent-red relative z-10">{Number(price).toLocaleString('id-ID')}</span>
                    <span className="font-mono text-xs text-slate-500 relative z-10">{vol>=1000?`${(vol/1000).toFixed(0)}K`:vol}</span>
                  </div>
                )
              })}
              {!orderbook.asks?.length&&[...Array(5)].map((_,i)=><div key={i} className="flex justify-between px-2 py-0.5"><div className="shimmer h-3 w-20 rounded"/><div className="shimmer h-3 w-12 rounded"/></div>)}
            </div>
            <div className="py-1 text-center border-y border-border-dim my-1">
              <span className="font-mono text-xs text-slate-500">
                {data?.bid&&data?.ask?`Spread: ${(Number(data.ask)-Number(data.bid)).toFixed(0)}`:'— Spread —'}
              </span>
            </div>
            <p className="label-xs text-accent-green mb-1">BIDS (Beli)</p>
            <div className="space-y-0.5">
              {(orderbook.bids||[]).slice(0,8).map((b,i) => {
                const price=b.price||b[0],vol=b.volume||b[1]||0
                const max=Math.max(...(orderbook.bids||[]).map(x=>x.volume||x[1]||0),1)
                return (
                  <div key={i} className="relative flex items-center justify-between px-2 py-0.5 rounded overflow-hidden">
                    <div className="absolute left-0 top-0 h-full bg-accent-green/10 rounded" style={{width:`${(vol/max)*100}%`}}/>
                    <span className="font-mono text-xs text-accent-green relative z-10">{Number(price).toLocaleString('id-ID')}</span>
                    <span className="font-mono text-xs text-slate-500 relative z-10">{vol>=1000?`${(vol/1000).toFixed(0)}K`:vol}</span>
                  </div>
                )
              })}
              {!orderbook.bids?.length&&[...Array(5)].map((_,i)=><div key={i} className="flex justify-between px-2 py-0.5"><div className="shimmer h-3 w-20 rounded"/><div className="shimmer h-3 w-12 rounded"/></div>)}
            </div>
          </div>

          <div className="space-y-4">
            <div className="card p-4">
              <p className="label-xs mb-3">INTRADAY STATS</p>
              <div className="space-y-2">
                {[
                  ['High',data?.high,'text-accent-green'],
                  ['Low',data?.low,'text-accent-red'],
                  ['Open',data?.open,'text-white'],
                  ['VWAP',data?.vwap,'text-accent-blue'],
                  ['Volume',data?.volume_today,'text-slate-300'],
                  ['Rel Vol',data?.rvol?`${data.rvol}x`:null,data?.rvol>=2?'text-accent-gold':'text-slate-400'],
                ].map(([k,v,c]) => (
                  <div key={k} className="flex justify-between items-center">
                    <span className="font-mono text-xs text-slate-600">{k}</span>
                    <span className={clsx('font-mono text-xs font-semibold',c)}>
                      {v!=null?(typeof v==='number'?v.toLocaleString('id-ID'):v):'—'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            {data?.volume_alert&&(
              <div className="card p-3 border-accent-gold/30 bg-accent-gold/5">
                <p className="font-mono text-xs text-accent-gold">⚡ {data.volume_alert}</p>
              </div>
            )}
            {!data&&(
              <div className="card p-6 text-center">
                <RefreshCw className="w-6 h-6 text-slate-700 mx-auto mb-2 animate-spin"/>
                <p className="font-mono text-xs text-slate-600">Menghubungkan ke data feed...</p>
              </div>
            )}
          </div>
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
