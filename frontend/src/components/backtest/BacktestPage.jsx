import React, { useState, useEffect, useRef } from "react";
import { BACKEND_URL } from "../../utils/api";

const MODES = ["swing", "intraday"];
const TIMEFRAMES_SWING = ["daily", "weekly"];
const TIMEFRAMES_INTRADAY = ["1h", "4h", "daily"];
const PERIODS = ["1y", "3y", "5y", "10y", "15y"];
const UNIVERSES = [20, 50, 100];
const MIN_SCORES = [60, 65, 70, 75];

export default function BacktestPage() {
  const [tab, setTab] = useState("universe");
  const [mode, setMode] = useState("swing");
  const [timeframe, setTimeframe] = useState("daily");
  const [period, setPeriod] = useState("5y");
  const [universe, setUniverse] = useState(20);
  const [minScore, setMinScore] = useState(65);
  const [ticker, setTicker] = useState("BBCA");
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  const startBacktest = async () => {
    setLoading(true); setError(null); setStatus(null); setJobId(null);
    try {
      const endpoint = tab === "universe" ? "/api/backtest/universe/start" : "/api/backtest/single/run";
      const body = tab === "universe"
        ? { mode, timeframe, period, universe, min_score: minScore }
        : { ticker: ticker.toUpperCase(), mode, timeframe, period, min_score: minScore };
      const res = await fetch(`${BACKEND_URL}${endpoint}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
      });
      const data = await res.json();
      setJobId(data.job_id);
      setStatus({ status: "running", progress: 0, message: "Memulai backtest..." });
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  useEffect(() => {
    if (!jobId) return;
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/api/backtest/status/${jobId}`);
        const data = await res.json();
        setStatus(data);
        if (data.status === "completed" || data.status === "failed") clearInterval(pollRef.current);
      } catch {}
    }, 5000);
    return () => clearInterval(pollRef.current);
  }, [jobId]);

  const timeframes = mode === "swing" ? TIMEFRAMES_SWING : TIMEFRAMES_INTRADAY;

  return (
    <div style={S.container}>
      <div style={S.header}>
        <h1 style={S.title}>BACKTEST ENGINE</h1>
        <p style={S.subtitle}>34 Engines · 10 Knowledge Base · IDX Historical Data</p>
      </div>
      <div style={S.tabRow}>
        {["universe", "single"].map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ ...S.tabBtn, ...(tab === t ? S.tabActive : {}) }}>
            {t === "universe" ? "🌐 Universe Backtest" : "🎯 Single Stock"}
          </button>
        ))}
      </div>
      <div style={S.configCard}>
        <div style={S.configGrid}>
          <div style={S.configItem}>
            <label style={S.label}>MODE</label>
            <div style={S.btnGroup}>
              {MODES.map(m => (
                <button key={m} onClick={() => { setMode(m); setTimeframe("daily"); }}
                  style={{ ...S.optBtn, ...(mode === m ? S.optActive : {}) }}>{m.toUpperCase()}</button>
              ))}
            </div>
          </div>
          <div style={S.configItem}>
            <label style={S.label}>TIMEFRAME</label>
            <div style={S.btnGroup}>
              {timeframes.map(tf => (
                <button key={tf} onClick={() => setTimeframe(tf)}
                  style={{ ...S.optBtn, ...(timeframe === tf ? S.optActive : {}) }}>{tf.toUpperCase()}</button>
              ))}
            </div>
          </div>
          <div style={S.configItem}>
            <label style={S.label}>PERIOD</label>
            <div style={S.btnGroup}>
              {PERIODS.map(p => (
                <button key={p} onClick={() => setPeriod(p)}
                  style={{ ...S.optBtn, ...(period === p ? S.optActive : {}) }}>{p}</button>
              ))}
            </div>
          </div>
          <div style={S.configItem}>
            <label style={S.label}>MIN SCORE</label>
            <div style={S.btnGroup}>
              {MIN_SCORES.map(s => (
                <button key={s} onClick={() => setMinScore(s)}
                  style={{ ...S.optBtn, ...(minScore === s ? S.optActive : {}) }}>{s}</button>
              ))}
            </div>
          </div>
          {tab === "universe" && (
            <div style={S.configItem}>
              <label style={S.label}>UNIVERSE</label>
              <div style={S.btnGroup}>
                {UNIVERSES.map(u => (
                  <button key={u} onClick={() => setUniverse(u)}
                    style={{ ...S.optBtn, ...(universe === u ? S.optActive : {}) }}>Top {u}</button>
                ))}
              </div>
            </div>
          )}
          {tab === "single" && (
            <div style={S.configItem}>
              <label style={S.label}>TICKER</label>
              <input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())}
                style={S.input} placeholder="BBCA" maxLength={6} />
            </div>
          )}
        </div>
        <button onClick={startBacktest} disabled={loading || (jobId && status?.status === "running")} style={S.runBtn}>
          {loading ? "MEMULAI..." : jobId && status?.status === "running" ? "⏳ RUNNING..." : "▶ RUN BACKTEST"}
        </button>
      </div>
      {status?.status === "running" && (
        <div style={S.progressCard}>
          <div style={S.progressHeader}>
            <span style={S.progressMsg}>{status.message}</span>
            <span style={S.progressPct}>{status.progress}%</span>
          </div>
          <div style={S.progressBg}><div style={{ ...S.progressFill, width: `${status.progress}%` }} /></div>
          {status.current_ticker && <p style={S.progressSub}>Processing: {status.current_ticker}</p>}
        </div>
      )}
      {error && <div style={S.errorBox}><strong>ERROR:</strong> {error}</div>}
      {status?.status === "completed" && <ResultsView status={status} />}
      {status?.status === "failed" && <div style={S.errorBox}><strong>FAILED:</strong> {status.message}</div>}
    </div>
  );
}

function ResultsView({ status }) {
  const s = status.summary || status;
  const yearly = status.yearly_breakdown || {};
  const top = status.top_performers || [];
  const trades = status.recent_trades || status.trades || [];
  return (
    <div>
      <div style={S.summaryGrid}>
        {[
          { label: "WINRATE", value: `${s.winrate}%`, color: "#16a34a" },
          { label: "PROFIT FACTOR", value: s.profit_factor, color: "#0ea5e9" },
          { label: "MAX DRAWDOWN", value: `${s.max_drawdown}%`, color: "#dc2626" },
          { label: "FINAL EQUITY", value: `${s.final_equity}%`, color: "#d97706" },
          { label: "TOTAL TRADES", value: s.total_trades, color: "#7c3aed" },
          { label: "AVG WIN", value: `${s.avg_win_pct}%`, color: "#16a34a" },
        ].map((item, i) => (
          <div key={i} style={S.summaryCard}>
            <div style={S.summaryLabel}>{item.label}</div>
            <div style={{ ...S.summaryValue, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>
      {Object.keys(yearly).length > 0 && (
        <div style={S.section}>
          <h3 style={S.sectionTitle}>📅 Yearly Breakdown</h3>
          <div style={S.yearlyGrid}>
            {Object.entries(yearly).sort().map(([year, data]) => (
              <div key={year} style={S.yearCard}>
                <div style={S.yearLabel}>{year}</div>
                <div style={{ color: data.winrate >= 50 ? "#16a34a" : "#dc2626", fontWeight: "bold" }}>{data.winrate}% WR</div>
                <div style={{ fontSize: 11, color: "#64748b" }}>{data.trades} trades</div>
                <div style={{ fontSize: 11, color: data.total_pnl >= 0 ? "#16a34a" : "#dc2626" }}>{data.total_pnl > 0 ? "+" : ""}{data.total_pnl}%</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {top.length > 0 && (
        <div style={S.section}>
          <h3 style={S.sectionTitle}>🏆 Top Performers</h3>
          {top.map((s, i) => (
            <div key={i} style={S.tradeRow}>
              <span style={S.tradeTicker}>#{i+1} {s.ticker}</span>
              <span style={{ color: "#16a34a" }}>{s.winrate}% WR</span>
              <span style={{ color: "#0ea5e9" }}>PF: {s.profit_factor}</span>
              <span style={{ color: "#64748b" }}>{s.total_trades} trades</span>
            </div>
          ))}
        </div>
      )}
      {trades.length > 0 && (
        <div style={S.section}>
          <h3 style={S.sectionTitle}>📋 Recent Trades</h3>
          {trades.slice(0,10).map((t, i) => (
            <div key={i} style={{ ...S.tradeRow, borderLeft: `3px solid ${t.result==="WIN"?"#16a34a":t.result==="LOSS"?"#dc2626":"#d97706"}` }}>
              <span style={S.tradeTicker}>{t.ticker}</span>
              <span style={{ fontSize: 11, color: "#64748b" }}>{t.entry_date} → {t.exit_date}</span>
              <span style={{ color: t.result==="WIN"?"#16a34a":"#dc2626", fontWeight:"bold" }}>{t.pnl_pct>0?"+":""}{t.pnl_pct}%</span>
              <span style={{ fontSize:11, padding:"2px 6px", borderRadius:4, backgroundColor:t.result==="WIN"?"#dcfce7":t.result==="LOSS"?"#fee2e2":"#fef9c3", color:t.result==="WIN"?"#16a34a":t.result==="LOSS"?"#dc2626":"#d97706" }}>{t.result}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const S = {
  container:{fontFamily:"Arial,sans-serif",backgroundColor:"#f1f5f9",minHeight:"100vh",padding:"24px 16px",color:"#1e293b"},
  header:{textAlign:"center",marginBottom:24,borderBottom:"2px solid #e2e8f0",paddingBottom:16},
  title:{color:"#0ea5e9",fontSize:28,margin:0,letterSpacing:4,fontWeight:"bold"},
  subtitle:{color:"#94a3b8",fontSize:12,margin:"4px 0 0",letterSpacing:2},
  tabRow:{display:"flex",gap:8,marginBottom:16,justifyContent:"center"},
  tabBtn:{padding:"10px 24px",border:"1px solid #cbd5e1",backgroundColor:"#fff",color:"#64748b",cursor:"pointer",borderRadius:6,fontSize:13,fontWeight:"600"},
  tabActive:{borderColor:"#0ea5e9",color:"#0ea5e9",backgroundColor:"#e0f2fe"},
  configCard:{backgroundColor:"#fff",border:"1px solid #e2e8f0",borderRadius:10,padding:20,marginBottom:20},
  configGrid:{display:"grid",gap:16,marginBottom:20},
  configItem:{display:"flex",flexDirection:"column",gap:8},
  label:{fontSize:11,fontWeight:"bold",color:"#64748b",letterSpacing:1},
  btnGroup:{display:"flex",gap:6,flexWrap:"wrap"},
  optBtn:{padding:"6px 14px",border:"1px solid #cbd5e1",backgroundColor:"#fff",color:"#64748b",cursor:"pointer",borderRadius:6,fontSize:12,fontWeight:"600"},
  optActive:{borderColor:"#0ea5e9",color:"#0ea5e9",backgroundColor:"#e0f2fe"},
  input:{padding:"8px 12px",border:"1px solid #cbd5e1",borderRadius:6,fontSize:14,fontWeight:"bold",width:120,color:"#0ea5e9"},
  runBtn:{display:"block",width:"100%",padding:"14px 0",backgroundColor:"#0ea5e9",color:"#fff",border:"none",borderRadius:6,fontSize:14,fontWeight:"bold",cursor:"pointer"},
  progressCard:{backgroundColor:"#fff",border:"1px solid #e2e8f0",borderRadius:10,padding:20,marginBottom:20},
  progressHeader:{display:"flex",justifyContent:"space-between",marginBottom:10},
  progressMsg:{fontSize:13,color:"#0ea5e9",fontWeight:"600"},
  progressPct:{fontSize:20,fontWeight:"bold",color:"#0ea5e9"},
  progressBg:{backgroundColor:"#e2e8f0",height:10,borderRadius:5,overflow:"hidden",marginBottom:8},
  progressFill:{height:"100%",backgroundColor:"#0ea5e9",borderRadius:5,transition:"width 0.5s ease",backgroundImage:"linear-gradient(90deg,#0ea5e9,#16a34a)"},
  progressSub:{fontSize:11,color:"#94a3b8",margin:0},
  errorBox:{backgroundColor:"#fee2e2",border:"1px solid #fca5a5",borderRadius:6,padding:16,color:"#dc2626",marginBottom:16,fontSize:13},
  summaryGrid:{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(150px,1fr))",gap:12,marginBottom:20},
  summaryCard:{backgroundColor:"#fff",border:"1px solid #e2e8f0",borderRadius:10,padding:16,textAlign:"center"},
  summaryLabel:{fontSize:10,color:"#94a3b8",fontWeight:"bold",letterSpacing:1,marginBottom:8},
  summaryValue:{fontSize:22,fontWeight:"bold"},
  section:{backgroundColor:"#fff",border:"1px solid #e2e8f0",borderRadius:10,padding:16,marginBottom:16},
  sectionTitle:{margin:"0 0 12px",fontSize:14,color:"#1e293b",fontWeight:"bold"},
  yearlyGrid:{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(100px,1fr))",gap:8},
  yearCard:{backgroundColor:"#f8fafc",border:"1px solid #e2e8f0",borderRadius:8,padding:10,textAlign:"center"},
  yearLabel:{fontSize:13,fontWeight:"bold",color:"#1e293b",marginBottom:4},
  tradeRow:{display:"flex",alignItems:"center",gap:12,padding:"8px 12px",backgroundColor:"#f8fafc",borderRadius:6,fontSize:12,flexWrap:"wrap",marginBottom:6},
  tradeTicker:{fontWeight:"bold",color:"#0ea5e9",minWidth:60},
};
