import React, { useEffect, useState } from 'react'
import { Activity, TrendingUp, BarChart2, Zap, Wifi, WifiOff, BookOpen } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { checkHealth } from '../../utils/api'
import clsx from 'clsx'

const TABS = [
  { id:'screener', label:'Screener', icon:TrendingUp },
  { id:'analytic', label:'Analytic', icon:BarChart2 },
  { id:'monitoring', label:'Monitoring', icon:Activity },
  { id:'scalping', label:'Scalping', icon:Zap },
  { id:'kb', label:'Knowledge Base', icon:BookOpen },
  { id:'backtest', label:'Backtest', icon:Activity },
  { id:'regime', label:'Market Regime', icon:Activity },
]

const TICKERS = [
  {sym:'BBCA',price:'9.450',chg:'+1.34%',up:true},{sym:'BBRI',price:'4.230',chg:'-0.47%',up:false},
  {sym:'TLKM',price:'3.890',chg:'+0.78%',up:true},{sym:'ASII',price:'5.200',chg:'+2.15%',up:true},
  {sym:'BMRI',price:'6.125',chg:'-0.81%',up:false},{sym:'GOTO',price:'78',chg:'+3.97%',up:true},
  {sym:'ANTM',price:'1.685',chg:'-1.17%',up:false},{sym:'INDF',price:'6.950',chg:'+0.72%',up:true},
]

export default function Header() {
  const { activeTab, setActiveTab, backendOnline, setBackendOnline } = useStore()
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const ping = async () => {
      try { await checkHealth(); setBackendOnline(true) }
      catch { setBackendOnline(false) }
    }
    ping()
    const iv = setInterval(ping, 30000)
    return () => clearInterval(iv)
  }, [])

  useEffect(() => {
    const iv = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(iv)
  }, [])

  const isOpen = () => {
    const now = new Date(); const wib = new Date(now.getTime() + 7*60*60*1000); const m = wib.getUTCHours()*60+wib.getUTCMinutes()
    return m>=540 && m<=960
  }

  return (
    <header className="sticky top-0 z-50 flex flex-col border-b border-border-dim bg-bg-primary/95 backdrop-blur-sm">
      <div className="flex items-center justify-between px-4 py-1.5 border-b border-border-dim/50 bg-bg-secondary/50">
        <div className="flex-1 overflow-hidden mr-4 max-w-2xl">
          <div className="ticker-inner inline-flex gap-6">
            {[...TICKERS,...TICKERS].map((t,i) => (
              <span key={i} className="inline-flex items-center gap-1.5 font-mono text-xs">
                <span className="text-slate-400">{t.sym}</span>
                <span className="text-slate-800 font-semibold">{t.price}</span>
                <span className={t.up?'text-accent-green':'text-accent-red'}>{t.chg}</span>
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <div className="flex items-center gap-1.5">
            <span className={clsx('w-1.5 h-1.5 rounded-full',isOpen()?'bg-accent-green animate-pulse':'bg-slate-500')}/>
            <span className="text-xs font-mono text-slate-400">{isOpen()?'IDX OPEN':'IDX CLOSED'}</span>
          </div>
          {backendOnline===null
            ? <span className="text-xs font-mono text-slate-500">connecting...</span>
            : backendOnline
              ? <span className="flex items-center gap-1 text-xs font-mono text-accent-green"><Wifi className="w-3 h-3"/>ONLINE</span>
              : <span className="flex items-center gap-1 text-xs font-mono text-accent-red"><WifiOff className="w-3 h-3"/>OFFLINE</span>
          }
          <span className="font-mono text-xs text-slate-400">{time.toLocaleTimeString('id-ID',{hour12:false})} WIB</span>
        </div>
      </div>
      <div className="flex items-center px-4 pt-2 pb-0">
        <div className="mr-8 flex items-center gap-2.5">
          <div className="relative">
            <div className="w-8 h-8 border border-accent-green/50 rounded flex items-center justify-center">
              <span className="font-display font-bold text-accent-green text-sm">B</span>
            </div>
            <div className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-accent-green rounded-full blink"/>
          </div>
          <div>
            <div className="font-display font-bold text-accent-green text-base tracking-wider leading-none">BISMILLAH</div>
            <div className="font-mono text-[9px] text-slate-500 tracking-widest uppercase leading-none mt-0.5">Super Trading Terminal</div>
          </div>
        </div>
        <nav className="flex gap-0">
          {TABS.map(({id,label,icon:Icon}) => (
            <button key={id} onClick={() => setActiveTab(id)}
              className={clsx('tab-btn flex items-center gap-2', activeTab===id?'tab-active':'tab-inactive')}>
              <Icon className="w-3.5 h-3.5"/>{label}
            </button>
          ))}
        </nav>
        <div className="ml-auto mb-2 flex items-center gap-1.5 px-3 py-1 rounded border border-purple-500/30 bg-purple-500/5">
          <span className="font-mono text-xs text-purple-400 font-semibold">34 ENGINES</span>
          <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse"/>
        </div>
      </div>
    </header>
  )
}
