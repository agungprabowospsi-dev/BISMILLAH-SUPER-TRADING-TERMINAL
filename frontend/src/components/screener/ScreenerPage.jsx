import React, { useState } from "react";
import { BACKEND_URL } from "../../utils/api";

const MODE_OPTIONS = ["swing", "intraday", "scalping"];

const SIGNAL_COLOR = {
  BUY: "#00e676",
  SELL: "#ff1744",
  HOLD: "#ffd740",
  NEUTRAL: "#90a4ae",
};

export default function ScreenerPage() {
  const [mode, setMode] = useState("swing");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [rawResponse, setRawResponse] = useState(null);

  const runScreener = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setRawResponse(null);

    try {
      const url = `${BACKEND_URL}/api/screener/run`;
      console.log("[SCREENER] Hitting:", url, "mode:", mode);

      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: mode.toLowerCase() }),
      });

      console.log("[SCREENER] HTTP status:", res.status);

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`HTTP ${res.status}: ${errText}`);
      }

      const data = await res.json();
      console.log("[SCREENER] Raw response:", JSON.stringify(data, null, 2));
      setRawResponse(data);

      const stocks =
        data?.top5_stocks ||
        data?.top_stocks ||
        data?.stocks ||
        data?.results ||
        [];

      console.log("[SCREENER] Extracted stocks:", stocks);
      console.log("[SCREENER] Total scanned:", data?.total_scanned);

      setResult({
        session_id: data?.session_id || "N/A",
        mode: data?.mode || mode,
        stocks: Array.isArray(stocks) ? stocks : [],
        total_scanned: data?.total_scanned || 0,
      });
    } catch (err) {
      console.error("[SCREENER] Error:", err);
      setError(err.message || "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>📡 SCREENER</h1>
        <p style={styles.subtitle}>Bismillah Super Trading Terminal</p>
      </div>

      <div style={styles.modeRow}>
        {MODE_OPTIONS.map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              ...styles.modeBtn,
              ...(mode === m ? styles.modeBtnActive : {}),
            }}
          >
            {m.toUpperCase()}
          </button>
        ))}
      </div>

      <button onClick={runScreener} disabled={loading} style={styles.runBtn}>
        {loading ? "⏳ SCANNING..." : "🚀 RUN SCREENER"}
      </button>

      {error && (
        <div style={styles.errorBox}>
          <strong>❌ ERROR:</strong> {error}
          <br />
          <small>Cek console browser untuk detail</small>
        </div>
      )}

      {result && (
        <div style={styles.resultsSection}>
          <div style={styles.metaRow}>
            <span style={styles.metaBadge}>Mode: {result.mode.toUpperCase()}</span>
            <span style={styles.metaBadge}>Scanned: {result.total_scanned}</span>
            <span style={styles.metaBadge}>Session: {result.session_id}</span>
          </div>

          {result.stocks.length === 0 ? (
            <div style={styles.emptyBox}>
              <p>⚠️ Tidak ada saham tersaring.</p>
              <p style={{ fontSize: 12, marginTop: 8 }}>
                Backend returned {result.total_scanned} stocks tapi tidak ada yang masuk filter.
              </p>
              {rawResponse && (
                <pre style={styles.debugPre}>
                  {JSON.stringify(rawResponse, null, 2)}
                </pre>
              )}
            </div>
          ) : (
            <div style={styles.stockGrid}>
              {result.stocks.map((stock, idx) => (
                <StockCard key={stock.ticker || idx} stock={stock} rank={idx + 1} />
              ))}
            </div>
          )}
        </div>
      )}

      {!result && !loading && !error && (
        <div style={styles.initialBox}>
          <p style={{ color: "#546e7a", fontSize: 15 }}>
            Pilih mode dan klik RUN SCREENER untuk mulai scanning saham IDX.
          </p>
        </div>
      )}
    </div>
  );
}

function StockCard({ stock, rank }) {
  const signal = (stock.signal || "NEUTRAL").toUpperCase();
  const signalColor = SIGNAL_COLOR[signal] || SIGNAL_COLOR.NEUTRAL;

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <span style={styles.rank}>#{rank}</span>
        <span style={styles.ticker}>{stock.ticker}</span>
        <span style={{ ...styles.signalBadge, backgroundColor: signalColor + "22", color: signalColor }}>
          {signal}
        </span>
      </div>
      <div style={styles.cardBody}>
        <div style={styles.scoreRow}>
          <span style={styles.scoreLabel}>Score</span>
          <span style={styles.scoreValue}>{Number(stock.score || 0).toFixed(1)}</span>
        </div>
        <div style={styles.priceRow}>
          <span style={styles.priceLabel}>Last Price</span>
          <span style={styles.priceValue}>
            Rp {Number(stock.last_price || 0).toLocaleString("id-ID")}
          </span>
        </div>
        <div style={styles.barBg}>
          <div
            style={{
              ...styles.barFill,
              width: `${Math.min(100, stock.score || 0)}%`,
              backgroundColor: signalColor,
            }}
          />
        </div>
      </div>
    </div>
  );
}

const styles = {
  container: {
    fontFamily: "'Courier New', monospace",
    backgroundColor: "#0a0e1a",
    minHeight: "100vh",
    padding: "24px 16px",
    color: "#e0e0e0",
  },
  header: {
    textAlign: "center",
    marginBottom: 24,
    borderBottom: "1px solid #1a2a4a",
    paddingBottom: 16,
  },
  title: { color: "#00e5ff", fontSize: 28, margin: 0, letterSpacing: 4 },
  subtitle: { color: "#546e7a", fontSize: 12, margin: "4px 0 0", letterSpacing: 2 },
  modeRow: { display: "flex", gap: 8, justifyContent: "center", marginBottom: 16 },
  modeBtn: {
    padding: "8px 20px",
    border: "1px solid #1a2a4a",
    backgroundColor: "#0d1220",
    color: "#546e7a",
    cursor: "pointer",
    borderRadius: 4,
    fontSize: 12,
    letterSpacing: 1,
  },
  modeBtnActive: { borderColor: "#00e5ff", color: "#00e5ff", backgroundColor: "#00e5ff11" },
  runBtn: {
    display: "block",
    width: "100%",
    maxWidth: 320,
    margin: "0 auto 24px",
    padding: "14px 0",
    backgroundColor: "#00e5ff",
    color: "#0a0e1a",
    border: "none",
    borderRadius: 4,
    fontSize: 14,
    fontWeight: "bold",
    letterSpacing: 2,
    cursor: "pointer",
    fontFamily: "'Courier New', monospace",
  },
  errorBox: {
    backgroundColor: "#ff174422",
    border: "1px solid #ff1744",
    borderRadius: 4,
    padding: 16,
    color: "#ff6b6b",
    marginBottom: 16,
    fontSize: 13,
  },
  resultsSection: { marginTop: 8 },
  metaRow: { display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 },
  metaBadge: {
    backgroundColor: "#1a2a4a",
    padding: "4px 10px",
    borderRadius: 4,
    fontSize: 11,
    color: "#90caf9",
  },
  emptyBox: {
    textAlign: "center",
    padding: 32,
    border: "1px dashed #1a2a4a",
    borderRadius: 8,
    color: "#546e7a",
  },
  debugPre: {
    backgroundColor: "#0d1220",
    padding: 12,
    borderRadius: 4,
    fontSize: 10,
    color: "#90a4ae",
    textAlign: "left",
    marginTop: 12,
    maxHeight: 200,
    overflow: "auto",
  },
  stockGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: 12,
  },
  card: {
    backgroundColor: "#0d1220",
    border: "1px solid #1a2a4a",
    borderRadius: 8,
    overflow: "hidden",
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "12px 16px",
    borderBottom: "1px solid #1a2a4a",
    backgroundColor: "#0a0e1a",
  },
  rank: { color: "#546e7a", fontSize: 11, minWidth: 24 },
  ticker: { color: "#00e5ff", fontWeight: "bold", fontSize: 16, flex: 1, letterSpacing: 1 },
  signalBadge: {
    padding: "2px 8px",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: "bold",
    letterSpacing: 1,
    border: "1px solid transparent",
  },
  cardBody: { padding: "12px 16px" },
  scoreRow: { display: "flex", justifyContent: "space-between", marginBottom: 6 },
  scoreLabel: { color: "#546e7a", fontSize: 12 },
  scoreValue: { color: "#ffd740", fontSize: 16, fontWeight: "bold" },
  priceRow: { display: "flex", justifyContent: "space-between", marginBottom: 10 },
  priceLabel: { color: "#546e7a", fontSize: 12 },
  priceValue: { color: "#e0e0e0", fontSize: 13 },
  barBg: { backgroundColor: "#1a2a4a", height: 4, borderRadius: 2, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 2, transition: "width 0.5s ease" },
  initialBox: {
    textAlign: "center",
    padding: 48,
    border: "1px dashed #1a2a4a",
    borderRadius: 8,
  },
};
