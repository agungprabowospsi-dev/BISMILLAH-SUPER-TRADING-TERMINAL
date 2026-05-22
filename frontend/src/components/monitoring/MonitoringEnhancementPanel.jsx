import React, { useState, useEffect } from 'react'
import { Brain, TrendingUp, TrendingDown, AlertTriangle, CheckCircle, XCircle, Activity, BarChart2, RefreshCw } from 'lucide-react'

const BACKEND = 'https://backend-production-daed.up.railway.app'

// ─── HELPERS ───────────────────────────────────────────────
const clx = (...c) => c.filter(Boolean).join(' ')

const actionColor = (action) => ({
  HOLD_TP2:  'text-green-400 bg-green-400/10 border-green-400/30',
  HOLD_TP1:  'text-blue-400 bg-blue-400/10 border-blue-400/30',
  REDUCE_50: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  EXIT_ALL:  'text-red-400 bg-red-400/10 border-red-400/30',
}[action] || 'text-gray-400 bg-gray-400/10 border-gray-400/30')

const actionIcon = (action) => ({
  HOLD_TP2:  <CheckCircle size={16} className="text-green-400" />,
  HOLD_TP1:  <TrendingUp size={16} className="text-blue-400" />,
  REDUCE_50: <AlertTriangle size={16} className="text-yellow-400" />,
  EXIT_ALL:  <XCircle size={16} className="text-red-400" />,
}[action] || <Activity size={16} />)

const labelColor = (label) => ({
  VERY_STRONG: 'text-green-400',
  STRONG:      'text-emerald-400',
  MODERATE:    'text-yellow-400',
  WEAK:        'text-orange-400',
  EXHAUSTED:   'text-red-400',
}[label] || 'text-gray-400')

const phaseColor = (phase) => ({
  ACCUMULATION:   'text-blue-400',
  MARKUP:         'text-green-400',
  DISTRIBUTION:   'text-red-400',
  MARKDOWN:       'text-red-500',
  REACCUMULATION: 'text-yellow-400',
  UNKNOWN:        'text-gray-400',
}[phase] || 'text-gray-400')

const probBar = (pct) => (
  <div className="w-full bg-gray-700 rounded-full h-1.5 mt-1">
    <div
      className={clx('h-1.5 rounded-full transition-all',
        pct >= 60 ? 'bg-green-400' : pct >= 40 ? 'bg-yellow-400' : 'bg-red-400'
      )}
      style={{ width: `${Math.min(pct, 100)}%` }}
    />
  </div>
)

// ─── SUB COMPONENTS ────────────────────────────────────────

const Section = ({ title, icon, children, alert }) => (
  <div className={clx(
    'rounded-xl border p-3 mb-3',
    alert ? 'border-red-500/40 bg-red-500/5' : 'border-gray-700/50 bg-gray-800/40'
  )}>
    <div className="flex items-center gap-2 mb-2">
      {icon}
      <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">{title}</span>
      {alert && <span className="ml-auto text-xs text-red-400 font-bold">⚠ ALERT</span>}
    </div>
    {children}
  </div>
)

const Row = ({ label, value, valueClass }) => (
  <div className="flex justify-between items-center py-0.5">
    <span className="text-xs text-gray-500">{label}</span>
    <span className={clx('text-xs font-medium', valueClass || 'text-gray-200')}>{value}</span>
  </div>
)

const PriceFeedCard = ({ data }) => (
  <Section title="Price Feed" icon={<Activity size={14} className="text-blue-400" />}>
    <Row label="Last Price" value={`Rp ${data.last_price?.toLocaleString('id-ID')}`} valueClass="text-white font-bold" />
    <Row label="Change"
      value={`${data.change_pct >= 0 ? '+' : ''}${data.change_pct?.toFixed(2)}%`}
      valueClass={data.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}
    />
    <Row label="Volume" value={`${(data.volume_today / 1000).toFixed(0)}K lot`} />
  </Section>
)

const AlertCard = ({ data }) => {
  if (!data.triggered) return null
  return (
    <Section title={`🔔 ${data.alert_type}`} icon={<AlertTriangle size={14} className="text-red-400" />} alert>
      <p className="text-sm font-bold text-red-300">{data.message}</p>
      <div className="mt-2 grid grid-cols-2 gap-1">
        <Row label="SL" value={`Rp ${data.sl_price?.toLocaleString('id-ID')}`} valueClass="text-red-400" />
        <Row label="TP1" value={`Rp ${data.tp1_price?.toLocaleString('id-ID')}`} valueClass="text-green-400" />
        <Row label="TP2" value={`Rp ${data.tp2_price?.toLocaleString('id-ID')}`} valueClass="text-green-400" />
        <Row label="TP3" value={`Rp ${data.tp3_price?.toLocaleString('id-ID')}`} valueClass="text-green-400" />
      </div>
    </Section>
  )
}

const BandarTypeCard = ({ data }) => (
  <Section title="Bandar Type" icon={<Brain size={14} className="text-purple-400" />}>
    <Row label="Type" value={data.bandar_type} valueClass="text-purple-300 font-bold" />
    <Row label="Confidence" value={`${data.confidence?.toFixed(1)}%`}
      valueClass={data.confidence >= 70 ? 'text-green-400' : data.confidence >= 50 ? 'text-yellow-400' : 'text-red-400'}
    />
    <Row label="Net Foreign" value={`${(data.net_foreign_lot / 1000).toFixed(0)}K lot`}
      valueClass={data.net_foreign_lot >= 0 ? 'text-green-400' : 'text-red-400'}
    />
    {data.rag_triggered && <p className="text-xs text-yellow-400 mt-1">⚡ RAG triggered</p>}
  </Section>
)

const BandarmologiCard = ({ data }) => (
  <Section
    title="Bandarmologi Monitor"
    icon={<BarChart2 size={14} className="text-cyan-400" />}
    alert={data.distribution_detected}
  >
    <Row label="Phase" value={data.current_phase}
      valueClass={phaseColor(data.current_phase)}
    />
    <Row label="Score Delta" value={`${data.score_delta >= 0 ? '+' : ''}${data.score_delta?.toFixed(1)}`}
      valueClass={data.score_delta >= 0 ? 'text-green-400' : 'text-red-400'}
    />
    <Row label="OBV Trend" value={data.obv_trend} />
    <Row label="Inst. Flow" value={data.institutional_flow} />
    {data.distribution_detected && (
      <p className="text-xs text-red-400 mt-1 font-bold">
        ⚠ {data.distribution_signals?.count} sinyal distribusi aktif
      </p>
    )}
    <p className="text-xs text-gray-400 mt-1 italic">{data.status_message}</p>
  </Section>
)

const MomentumCard = ({ data }) => (
  <Section title="Momentum Strength" icon={<TrendingUp size={14} className="text-green-400" />}>
    <div className="flex items-center justify-between mb-1">
      <span className="text-xs text-gray-500">Score</span>
      <span className={clx('text-lg font-bold', labelColor(data.label))}>{data.score?.toFixed(0)}</span>
    </div>
    {probBar(data.score)}
    <Row label="Label" value={data.label} valueClass={labelColor(data.label)} />
    <Row label="ROC" value={`${data.roc_pct?.toFixed(2)}%`} />
    <Row label="Volume Confirm" value={data.volume_confirming ? '✅ Ya' : '❌ Tidak'}
      valueClass={data.volume_confirming ? 'text-green-400' : 'text-red-400'}
    />
    {data.score_drop > 0 && (
      <p className="text-xs text-orange-400 mt-1">⬇ Drop {data.score_drop?.toFixed(1)} poin</p>
    )}
  </Section>
)

const RetestCard = ({ data }) => (
  <Section title="Retest Classifier" icon={<Activity size={14} className="text-orange-400" />}
    alert={['REVERSAL_WARNING','REVERSAL_CONFIRMED'].includes(data.classification)}
  >
    <Row label="Classification" value={data.classification}
      valueClass={['VERY_SHALLOW','NORMAL_RETEST'].includes(data.classification) ? 'text-green-400' :
        ['MEDIUM_RETEST','DEEP_BUT_VALID'].includes(data.classification) ? 'text-yellow-400' : 'text-red-400'}
    />
    <Row label="Fib Level" value={`${data.fib_level_pct?.toFixed(1)}%`} />
    <Row label="Pullback" value={`${data.pullback_pct?.toFixed(1)}%`} />
    <Row label="Vol Ratio" value={`${data.volume_ratio_pullback?.toFixed(2)}x`}
      valueClass={data.volume_ratio_pullback < 0.8 ? 'text-green-400' : 'text-yellow-400'}
    />
    {data.vsa_signal && <Row label="VSA" value={data.vsa_signal} valueClass="text-cyan-400" />}
    {data.bandar_retest_type && <Row label="Bandar Retest" value={data.bandar_retest_type}
      valueClass={data.bandar_retest_type === 'NORMAL_BANDAR_RETEST' ? 'text-green-400' :
        data.bandar_retest_type === 'DISTRIBUSI_TERSELUBUNG' ? 'text-red-400' : 'text-yellow-400'}
    />}
    {data.pattern_name && data.pattern_name !== 'NONE' && (
      <Row label="Pattern" value={`${data.pattern_name} (${data.pattern_win_rate?.toFixed(0)}%)`}
        valueClass={data.pattern_implication === 'BULLISH' ? 'text-green-400' :
          data.pattern_implication === 'BEARISH' ? 'text-red-400' : 'text-yellow-400'}
      />
    )}
    {data.retest_verdict && <Row label="Verdict" value={data.retest_verdict}
      valueClass={data.retest_verdict === 'STRONG_HOLD' ? 'text-green-400' :
        data.retest_verdict === 'HOLD' ? 'text-blue-400' :
        data.retest_verdict === 'REDUCE_50' ? 'text-yellow-400' : 'text-red-400'}
    />}
  </Section>
)

const TPProbCard = ({ data }) => (
  <Section title="TP Probability" icon={<TrendingUp size={14} className="text-green-400" />}>
    <div className="space-y-2">
      <div>
        <Row label="TP1" value={`${data.prob_tp1?.toFixed(1)}%`}
          valueClass={data.prob_tp1 >= 60 ? 'text-green-400' : data.prob_tp1 >= 40 ? 'text-yellow-400' : 'text-red-400'}
        />
        {probBar(data.prob_tp1)}
      </div>
      <div>
        <Row label="TP2" value={`${data.prob_tp2?.toFixed(1)}%`}
          valueClass={data.prob_tp2 >= 45 ? 'text-green-400' : 'text-yellow-400'}
        />
        {probBar(data.prob_tp2)}
      </div>
      <div>
        <Row label="TP3" value={`${data.prob_tp3?.toFixed(1)}%`} />
        {probBar(data.prob_tp3)}
      </div>
    </div>
    <div className="mt-2 pt-2 border-t border-gray-700/50">
      <Row label="Expected Value"
        value={`Rp ${data.expected_value?.toLocaleString('id-ID')}`}
        valueClass={data.expected_value >= 0 ? 'text-green-400' : 'text-red-400'}
      />
      <Row label="Multiplier" value={`${data.multiplier_stack?.total?.toFixed(3)}x`}
        valueClass={data.multiplier_stack?.total >= 1 ? 'text-green-400' : 'text-red-400'}
      />
    </div>
  </Section>
)

const RAGCard = ({ data }) => {
  if (!data.triggered) return null
  return (
    <Section title="RAG Monitor" icon={<Brain size={14} className="text-yellow-400" />}>
      <Row label="Trigger" value={data.trigger_reason} valueClass="text-yellow-400" />
      {data.rate_limited && <p className="text-xs text-orange-400">⏳ Rate limited — 15 menit cooldown</p>}
      {data.kb_insight && !data.rate_limited && (
        <div className="mt-2 p-2 bg-gray-700/30 rounded-lg">
          <p className="text-xs text-gray-300 leading-relaxed">{data.kb_insight}</p>
        </div>
      )}
      {data.confidence_boost > 0 && (
        <Row label="Confidence Boost" value={`+${data.confidence_boost} poin`} valueClass="text-green-400" />
      )}
    </Section>
  )
}

const RecommendationCard = ({ data }) => (
  <div className={clx(
    'rounded-xl border-2 p-4 mb-3',
    actionColor(data.action)
  )}>
    <div className="flex items-center gap-2 mb-3">
      {actionIcon(data.action)}
      <span className="text-base font-bold">{data.action}</span>
      <span className="ml-auto text-sm font-semibold">{data.confidence?.toFixed(1)}%</span>
    </div>
    <div className="space-y-1">
      {data.reason?.map((r, i) => (
        <p key={i} className="text-xs opacity-80">• {r}</p>
      ))}
    </div>
  </div>
)

const Phase2Card = ({ data }) => {
  if (!data?.wyckoff_phase || data.wyckoff_phase === 'UNKNOWN') return null
  return (
    <Section title="Phase 2 — Wyckoff + Weinstein + VSA"
      icon={<Brain size={14} className="text-violet-400" />}
      alert={data.wyckoff_phase === 'DISTRIBUTION' || data.weinstein_stage === 4}
    >
      <Row label="Wyckoff Phase" value={data.wyckoff_phase}
        valueClass={['ACCUMULATION','MARKUP','REACCUMULATION'].includes(data.wyckoff_phase) ? 'text-green-400' :
          ['DISTRIBUTION','MARKDOWN'].includes(data.wyckoff_phase) ? 'text-red-400' : 'text-yellow-400'}
      />
      <div className="flex items-center justify-between py-0.5">
        <span className="text-xs text-gray-500">Weinstein Stage</span>
        <span className={clx('text-xs font-bold px-2 py-0.5 rounded',
          data.weinstein_stage === 2 ? 'bg-green-400/20 text-green-400' :
          data.weinstein_stage === 4 ? 'bg-red-400/20 text-red-400' :
          data.weinstein_stage === 3 ? 'bg-orange-400/20 text-orange-400' :
          'bg-gray-700 text-gray-400'
        )}>
          Stage {data.weinstein_stage}
        </span>
      </div>
      <Row label="VSA Background" value={data.vsa_background}
        valueClass={data.vsa_background === 'BULLISH' ? 'text-green-400' :
          data.vsa_background === 'BEARISH' ? 'text-red-400' : 'text-gray-400'}
      />
    </Section>
  )
}

// ─── MAIN COMPONENT ────────────────────────────────────────

export default function MonitoringEnhancementPanel({ position }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [pollInterval, setPollInterval] = useState(null)

  const fetchData = async () => {
    if (!position?.ticker) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        `${BACKEND}/api/monitoring/enhancement/${position.ticker}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker:      position.ticker,
            trade_mode:  position.mode || 'SWING',
            entry_price: parseFloat(position.entry_price) || 0,
            sl_price:    parseFloat(position.stop_loss) || 0,
            tp1_price:   parseFloat(position.take_profit_1) || 0,
            tp2_price:   parseFloat(position.take_profit_2) || 0,
            tp3_price:   parseFloat(position.take_profit_3) || 0,
            entry_score: parseFloat(position.entry_score) || 0,
            lots:        parseInt(position.lot) || 10,
          })
        }
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setLastUpdate(new Date().toLocaleTimeString('id-ID'))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // Auto-poll per trade mode
  // SWING=5min, INTRADAY=1min, SCALPING=30sec
  useEffect(() => {
    if (!position?.ticker) return
    const mode = position?.mode || 'SWING'
    const intervalMs = mode === 'SCALPING' ? 30 * 1000
                     : mode === 'INTRADAY' ? 60 * 1000
                     : 5 * 60 * 1000
    fetchData()
    const interval = setInterval(fetchData, intervalMs)
    setPollInterval(interval)
    return () => clearInterval(interval)
  }, [position?.ticker, position?.mode])

  if (!position?.ticker) return (
    <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
      Pilih posisi untuk melihat monitoring enhancement
    </div>
  )

  return (
    <div className="space-y-1">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-purple-400" />
          <span className="text-sm font-bold text-gray-200">
            Enhancement — {position.ticker}
          </span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-400">
            {position.mode || 'SWING'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdate && (
            <span className="text-xs text-gray-500">{lastUpdate}</span>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="p-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 transition-colors"
          >
            <RefreshCw size={12} className={clx('text-gray-400', loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          ⚠ {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !data && (
        <div className="space-y-2">
          {[1,2,3].map(i => (
            <div key={i} className="h-20 rounded-xl bg-gray-700/30 animate-pulse" />
          ))}
        </div>
      )}

      {/* Data */}
      {data && (
        <>
          <RecommendationCard data={data.recommendation} />
          {data.alert?.triggered && <AlertCard data={data.alert} />}
          <PriceFeedCard data={data.price_feed} />
          <BandarTypeCard data={data.bandar_type} />
          <BandarmologiCard data={data.bandarmologi} />
          <MomentumCard data={data.momentum} />
          <RetestCard data={data.retest} />
          <Phase2Card data={data.retest} />
          <TPProbCard data={data.tp_probability} />
          <RAGCard data={data.rag_monitor} />

          {/* Processing time */}
          <p className="text-xs text-gray-600 text-right mt-1">
            ⚡ {data.processing_time_ms?.toFixed(0)}ms
          </p>
        </>
      )}
    </div>
  )
}
