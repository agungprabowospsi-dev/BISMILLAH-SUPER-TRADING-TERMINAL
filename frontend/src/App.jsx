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
    <div style={{ minHeight: '100vh', backgroundColor: '#f1f5f9', color: '#1e293b' }}>
      <Header/>
      <main style={{ position: 'relative', zIndex: 10 }}>
        {activeTab==='screener' && <ScreenerPage/>}
        {activeTab==='analytic' && <AnalyticPage/>}
        {activeTab==='monitoring' && <MonitoringPage/>}
        {activeTab==='scalping' && <ScalpingPage/>}
      </main>
      <footer style={{ borderTop: '1px solid #e2e8f0', marginTop: 32, padding: '12px 24px', display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#94a3b8' }}>BISMILLAH SUPER TRADING TERMINAL v1.0</span>
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#94a3b8' }}>34 Engines · AI-Powered · IDX Market</span>
      </footer>
    </div>
  )
}
