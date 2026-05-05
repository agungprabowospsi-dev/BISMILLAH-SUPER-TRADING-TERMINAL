import React from 'react'
import Header from './components/shared/Header'
import ScreenerPage from './components/screener/ScreenerPage'
import AnalyticPage from './components/analytic/AnalyticPage'
import MonitoringPage from './components/monitoring/MonitoringPage'
import ScalpingPage from './components/scalping/ScalpingPage'
import { useStore } from './stores/useStore'

export default function App() {
  const { activeTab } = useStore()
  return (
    <div className="min-h-screen bg-bg-primary">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-accent-green/3 rounded-full blur-3xl"/>
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-accent-blue/3 rounded-full blur-3xl"/>
      </div>
      <Header/>
      <main className="relative z-10">
        {activeTab==='screener' && <ScreenerPage/>}
        {activeTab==='analytic' && <AnalyticPage/>}
        {activeTab==='monitoring' && <MonitoringPage/>}
        {activeTab==='scalping' && <ScalpingPage/>}
      </main>
      <footer className="border-t border-border-dim mt-8 px-6 py-3 flex items-center justify-between">
        <span className="font-mono text-xs text-slate-700">BISMILLAH SUPER TRADING TERMINAL v1.0</span>
        <span className="font-mono text-xs text-slate-700">34 Engines · AI-Powered · IDX Market</span>
      </footer>
    </div>
  )
}
