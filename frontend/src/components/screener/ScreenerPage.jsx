import React, { useState, useEffect, useRef } from "react";
import SystemHealthGauge from "../shared/SystemHealthGauge";
import { BACKEND_URL } from "../../utils/api";
import { useStore } from "../../stores/useStore";

const MODE_OPTIONS = ["swing", "intraday", "scalping"];

const SIGNAL_COLOR = {
  BUY: "#16a34a",
  SELL: "#dc2626",
  HOLD: "#d97706",
  NEUTRAL: "#6b7280",
};

const getInstitutionalRank = (score = 0) => {
  const n = Number(score || 0);
  if (n >= 85) return { grade: "A+", label: "Elite Institutional Setup", color: "#16a34a" };
  if (n >= 75) return { grade: "A", label: "Strong Institutional Setup", color: "#22c55e" };
  if (n >= 65) return { grade: "B+", label: "Early Accumulation Setup", color: "#d97706" };
  if (n >= 55) return { grade: "B", label: "Watchlist Setup", color: "#f59e0b" };
  return { grade: "C", label: "Low Conviction", color: "#6b7280" };
};

const PROGRESS_MESSAGES = [
  "Memuat daftar saham IDX...",
  "Scanning 970 saham...",
  "Menjalankan Price Action Engine...",
  "Menjalankan Trend Structure Engine...",
  "Menjalankan Volume Intelligence...",
  "Menjalankan Order Block Engine...",
  "Menjalankan Bandarmology Engine...",
  "Menghitung composite score...",
  "Memfilter saham score >70...",
  "Menyiapkan hasil...",
];

export default function ScreenerPage() {
  const [mode, setMode] = useState("swing");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [rawResponse, setRawResponse] = useState(null);
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState("");
  const progressRef = useRef(null);
  const { sendToAnalytic } = useStore();

  const startProgress = () => {
    setProgress(0);
    setProgressMsg(PROGRESS_MESSAGES[0]);
    let step = 0;
    progressRef.current = setInterval(() => {
      step += 1;
      const pct = Math.min(90, step * 10);
      setProgress(pct);
      setProgressMsg(PROGRESS_MESSAGES[Math.min(step, PROGRESS_MESSAGES.length - 1)]);
    }, 3000);
  };

  const stopProgress = () => {
    if (progressRef.current) clearInterval(progressRef.current);
    setProgress(100);
    setProgressMsg("Selesai!");
    setTimeout(() => { setProgress(0); setProgressMsg(""); }, 1500);
  };

  const runScreener = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setRawResponse(null);
    startProgress();
    try {
      const res = await fetch(`${BACKEND_URL}/api/screener/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: mode.toLowerCase(), limit: 5, include_debug: false }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRawResponse(data);
      const stocks = data?.top_5 || data?.top5_stocks || data?.top_stocks || data?.stocks || data?.results || [];
      setResult({
        session_id: data?.session_id || "N/A",
        mode: data?.mode || mode,
        stocks: Array.isArray(stocks)
          ? stocks.map((x) => ({
              ...x,
              score: x.final_score ?? x.score ?? 0,
              last_price: x.price ?? x.last_price ?? 0,
            }))
          : [],
        total_scanned: data?.universe_count || data?.total_scanned || 0,
      });
    } catch (err) {
      setError(err.message || "Unknown error");
    } finally {
      stopProgress();
      setLoading(false);
    }
  };

  return (
    <div style={S.container}>
      <div style={S.header}>
        <h1 style={S.title}>SCREENER</h1>
        <p style={S.subtitle}>Bismillah Super Trading Terminal</p>
      </div>
      <SystemHealthGauge/>
      <div style={S.modeRow}>
        {MODE_OPTIONS.map((m) => (
          <button key={m} onClick={() => setMode(m)} style={{ ...S.modeBtn, ...(mode === m ? S.modeBtnActive : {}) }}>
            {m.toUpperCase()}
          </button>
        ))}
      </div>
      <button onClick={runScreener} disabled={loading} style={S.runBtn}>
        {loading ? "SCANNING..." : "RUN SCREENER"}
      </button>

      {loading && (
        <div style={S.progressBox}>
          <div style={S.progressHeader}>
            <span style={S.progressMsg}>{progressMsg}</span>
            <span style={S.progressPct}>{progress}%</span>
          </div>
          <div style={S.progressBg}>
            <div style={{ ...S.progressFill, width: `${progress}%` }} />
          </div>
          <p style={S.progressSub}>Scanning 970 saham IDX dengan 11 engines...</p>
        </div>
      )}

      {error && <div style={S.errorBox}><strong>ERROR:</strong> {error}</div>}

      {result && !loading && (
        <div style={S.resultsSection}>
          <div style={S.metaRow}>
            <span style={S.metaBadge}>Mode: {result.mode.toUpperCase()}</span>
            <span style={S.metaBadge}>Scanned: {result.total_scanned}</span>
            <span style={S.metaBadge}>Session: {result.session_id}</span>
          </div>
          {result.stocks.length === 0 ? (
            <div style={S.emptyBox}>
              <p>Tidak ada saham dengan score lebih dari 70 hari ini.</p>
              <p style={{ fontSize: 12, marginTop: 8 }}>Backend returned {result.total_scanned} stocks tapi tidak ada yang masuk filter.</p>
              {rawResponse && <pre style={S.debugPre}>{JSON.stringify(rawResponse, null, 2)}</pre>}
            </div>
          ) : (
            <div style={S.stockGrid}>
              {result.stocks.map((stock, idx) => (
                <StockCard key={stock.ticker || idx} stock={stock} rank={idx + 1} onClick={() => sendToAnalytic(stock.ticker)} />
              ))}
            </div>
          )}
        </div>
      )}

      {!result && !loading && !error && (
        <div style={S.initialBox}>
          <p style={{ color: "#6b7280" }}>Pilih mode dan klik RUN SCREENER untuk mulai scanning saham IDX.</p>
        </div>
      )}
    </div>
  );
}

function StockCard({ stock, rank, onClick }) {
  const signal = (stock.signal || "NEUTRAL").toUpperCase();
  const sc = SIGNAL_COLOR[signal] || SIGNAL_COLOR.NEUTRAL;
  const institutionalRank = getInstitutionalRank(stock.final_score || stock.score || 0);
  return (
    <div style={{ ...S.card, cursor: "pointer" }} onClick={onClick} title={`Analyze ${stock.ticker}`}>
      <div style={S.cardHeader}>
        <span style={S.rank}>#{rank}</span>
        <span style={S.ticker}>{stock.ticker}</span>
        <span style={{ ...S.signalBadge, backgroundColor: sc + "22", color: sc, border: "1px solid " + sc }}>{signal}</span>
      </div>
      <div style={S.cardBody}>

        <div
          style={{
            background: institutionalRank.color + "22",
            border: "1px solid " + institutionalRank.color,
            color: institutionalRank.color,
            borderRadius: 8,
            padding: "8px 10px",
            marginBottom: 10,
          }}
        >
          <div style={{ fontSize: 18, fontWeight: "bold" }}>
            {institutionalRank.grade}
          </div>

          <div style={{ fontSize: 11 }}>
            {institutionalRank.label}
          </div>
        </div>
        <div style={S.scoreRow}><span style={S.scoreLabel}>Score</span><span style={S.scoreValue}>{Number(stock.final_score || stock.score || 0).toFixed(1)}</span></div>
        <div style={S.priceRow}><span style={S.priceLabel}>Last Price</span><span style={S.priceValue}>Rp {Number(stock.price || stock.last_price || 0).toLocaleString("id-ID")}</span></div>
        <div style={S.barBg}><div style={{ ...S.barFill, width: Math.min(100, stock.final_score || stock.score || 0) + "%", backgroundColor: sc }} /></div>
      </div>
    </div>
  );
}

const S = {
  container: { fontFamily: "Arial, sans-serif", backgroundColor: "#f1f5f9", minHeight: "100vh", padding: "24px 16px", color: "#1e293b" },
  header: { textAlign: "center", marginBottom: 24, borderBottom: "2px solid #e2e8f0", paddingBottom: 16 },
  title: { color: "#0ea5e9", fontSize: 28, margin: 0, letterSpacing: 4, fontWeight: "bold" },
  subtitle: { color: "#94a3b8", fontSize: 12, margin: "4px 0 0", letterSpacing: 2 },
  modeRow: { display: "flex", gap: 8, justifyContent: "center", marginBottom: 16 },
  modeBtn: { padding: "8px 20px", border: "1px solid #cbd5e1", backgroundColor: "#ffffff", color: "#64748b", cursor: "pointer", borderRadius: 6, fontSize: 12, fontWeight: "600" },
  modeBtnActive: { borderColor: "#0ea5e9", color: "#0ea5e9", backgroundColor: "#e0f2fe" },
  runBtn: { display: "block", width: "100%", maxWidth: 320, margin: "0 auto 24px", padding: "14px 0", backgroundColor: "#0ea5e9", color: "#ffffff", border: "none", borderRadius: 6, fontSize: 14, fontWeight: "bold", cursor: "pointer" },
  progressBox: { backgroundColor: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 10, padding: 20, marginBottom: 20, boxShadow: "0 2px 8px rgba(0,0,0,0.06)" },
  progressHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  progressMsg: { fontSize: 13, color: "#0ea5e9", fontWeight: "600" },
  progressPct: { fontSize: 20, fontWeight: "bold", color: "#0ea5e9" },
  progressBg: { backgroundColor: "#e2e8f0", height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 8 },
  progressFill: { height: "100%", backgroundColor: "#0ea5e9", borderRadius: 5, transition: "width 0.5s ease", backgroundImage: "linear-gradient(90deg, #0ea5e9, #16a34a)" },
  progressSub: { fontSize: 11, color: "#94a3b8", margin: 0 },
  errorBox: { backgroundColor: "#fee2e2", border: "1px solid #fca5a5", borderRadius: 6, padding: 16, color: "#dc2626", marginBottom: 16, fontSize: 13 },
  resultsSection: { marginTop: 8 },
  metaRow: { display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 },
  metaBadge: { backgroundColor: "#e0f2fe", padding: "4px 10px", borderRadius: 4, fontSize: 11, color: "#0369a1", fontWeight: "600", border: "1px solid #bae6fd" },
  emptyBox: { textAlign: "center", padding: 32, border: "1px dashed #cbd5e1", borderRadius: 8, color: "#94a3b8", backgroundColor: "#ffffff" },
  debugPre: { backgroundColor: "#f8fafc", padding: 12, borderRadius: 4, fontSize: 10, color: "#64748b", textAlign: "left", marginTop: 12, maxHeight: 200, overflow: "auto" },
  stockGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 },
  card: { backgroundColor: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 10, overflow: "hidden", boxShadow: "0 2px 8px rgba(0,0,0,0.06)" },
  cardHeader: { display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid #f1f5f9", backgroundColor: "#f8fafc" },
  rank: { color: "#94a3b8", fontSize: 11, minWidth: 24, fontWeight: "bold" },
  ticker: { color: "#0ea5e9", fontWeight: "bold", fontSize: 16, flex: 1, letterSpacing: 1 },
  signalBadge: { padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: "bold", letterSpacing: 1 },
  cardBody: { padding: "12px 16px" },
  scoreRow: { display: "flex", justifyContent: "space-between", marginBottom: 6 },
  scoreLabel: { color: "#94a3b8", fontSize: 12 },
  scoreValue: { color: "#d97706", fontSize: 16, fontWeight: "bold" },
  priceRow: { display: "flex", justifyContent: "space-between", marginBottom: 10 },
  priceLabel: { color: "#94a3b8", fontSize: 12 },
  priceValue: { color: "#1e293b", fontSize: 13, fontWeight: "600" },
  barBg: { backgroundColor: "#e2e8f0", height: 5, borderRadius: 3, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 3, transition: "width 0.5s ease" },
  initialBox: { textAlign: "center", padding: 48, border: "1px dashed #cbd5e1", borderRadius: 8, backgroundColor: "#ffffff" },
};
