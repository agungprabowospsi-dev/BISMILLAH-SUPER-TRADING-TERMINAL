import React from 'react'
import Header from './components/shared/Header'
import ScreenerPage from './components/screener/ScreenerPage'
import AnalyticPage from './components/analytic/AnalyticPage'
import MonitoringPage from './components/monitoring/MonitoringPage'
import ScalpingPage from './components/scalping/ScalpingPage'
import KnowledgeBasePage from './components/knowledge_base/KnowledgeBasePage'
import BacktestPage from './components/backtest/BacktestPage'
import SystemMonitorPage from './components/system_monitor/SystemMonitorPage'
import { useStore } from './stores/useStore'

export default function App() {
  const { activeTab } = useStore()
  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f1f5f9', color: '#1e293b' }}>
      <Header/>
      <main style={{ position: 'relative', zIndex: 10 }}>
        {activeTab==='screener' && <ScreenerPage/>}
        {activeTab==='analytic' && <AnalyticPage/>}
        {activeTab==='monitoring' && <MonitoringPage/>}
        {activeTab==='scalping' && <ScalpingPage/>}
        {activeTab==='kb' && <KnowledgeBasePage/>}
        {activeTab==='backtest' && <BacktestPage/>}
        {activeTab==='sysmonitor' && <SystemMonitorPage/>}
      </main>
      <footer style={{ borderTop: '1px solid #e2e8f0', marginTop: 32, padding: '12px 24px', display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#94a3b8' }}>BISMILLAH SUPER TRADING TERMINAL v1.0</span>
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#94a3b8' }}>35 Engines · AI-Powered · IDX Market</span>
        <button onClick={() => { if(window.caches){window.caches.keys().then(keys=>keys.forEach(k=>window.caches.delete(k)));} localStorage.clear(); sessionStorage.clear(); window.location.reload(true); }} style={{ fontFamily: 'monospace', fontSize: 11, color: '#ef4444', background: 'none', border: '1px solid #ef4444', borderRadius: 4, padding: '2px 8px', cursor: 'pointer' }}>⟳ Clear Cache</button>
      </footer>
    </div>
  )
}
