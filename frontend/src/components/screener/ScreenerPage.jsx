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

const LANE_META = {
  EXECUTION_CANDIDATE: { label: "Execution Candidate", color: "#16a34a", bg: "#f0fdf4" },
  DEFENSIVE_QUALIFIED_CANDIDATE: { label: "Strict Confirm", color: "#d97706", bg: "#fffbeb" },
  TOP_GAINER_OPPORTUNITY: { label: "Top Gainer Opportunity", color: "#0284c7", bg: "#f0f9ff" },
  MANUAL_TOP_GAINER_OPPORTUNITY: { label: "Manual Top Gainer", color: "#16a34a", bg: "#f0fdf4" },
  MANUAL_CONDITIONAL_EXECUTION: { label: "Manual Conditional", color: "#d97706", bg: "#fffbeb" },
  NO_CHASE_RADAR: { label: "No-Chase Radar", color: "#b45309", bg: "#fffbeb" },
  WATCHLIST_ONLY: { label: "Watchlist Only", color: "#64748b", bg: "#f8fafc" },
}

const normalizeStock = (x = {}) => ({
  ...x,
  score: x.final_score ?? x.score ?? 0,
  last_price: x.price ?? x.last_price ?? 0,
})

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
  const [filterIntensity, setFilterIntensity] = useState(75);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [rawResponse, setRawResponse] = useState(null);
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState("");
  const [elapsedSec, setElapsedSec] = useState(0);
  const [manualFile, setManualFile] = useState(null);
  const [manualText, setManualText] = useState("");
  const [manualLoading, setManualLoading] = useState(false);
  const [manualResult, setManualResult] = useState(null);
  const [manualError, setManualError] = useState(null);
  const progressRef = useRef(null);
  const scanStartedAtRef = useRef(0);
  const { sendToAnalytic, sendBatchToAnalytic } = useStore();

  const startProgress = () => {
    setProgress(0);
    setElapsedSec(0);
    setProgressMsg(PROGRESS_MESSAGES[0]);
    scanStartedAtRef.current = Date.now();
    let step = 0;
    progressRef.current = setInterval(() => {
      step += 1;
      const elapsed = Math.floor((Date.now() - scanStartedAtRef.current) / 1000);
      setElapsedSec(elapsed);
      const pct = step <= 9 ? step * 10 : Math.min(97, 90 + Math.floor((step - 9) / 4));
      setProgress(pct);
      setProgressMsg(
        pct >= 90
          ? "Finalisasi response backend..."
          : PROGRESS_MESSAGES[Math.min(step, PROGRESS_MESSAGES.length - 1)]
      );
    }, 3000);
  };

  const stopProgress = () => {
    if (progressRef.current) clearInterval(progressRef.current);
    setProgress(100);
    setProgressMsg("Selesai!");
    setTimeout(() => { setProgress(0); setProgressMsg(""); setElapsedSec(0); }, 1500);
  };

  const runScreener = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setRawResponse(null);
    startProgress();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5 * 60 * 1000);
    try {
      const res = await fetch(`${BACKEND_URL}/api/screener/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ mode: mode.toLowerCase(), limit: 5, include_debug: false, filter_intensity: filterIntensity }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRawResponse(data);
      const stocks = data?.top_5 || data?.top5_stocks || data?.top_stocks || data?.stocks || data?.results || [];
      setResult({
        session_id: data?.session_id || "N/A",
        mode: data?.mode || mode,
        status: data?.status || "ok",
        message: data?.message || "",
        backend_error: data?.error || "",
        market_execution_regime: data?.market_execution_regime || null,
        candidate_count: data?.candidate_count ?? 0,
        scored_count: data?.scored_count ?? 0,
        qualified_count: data?.qualified_count ?? 0,
        strict_candidate_count: data?.strict_candidate_count,
        strict_qualified_count: data?.strict_qualified_count,
        top_gainer_universe_count: data?.top_gainer_universe_count ?? 0,
        opening_feed_fallback_count: data?.opening_feed_fallback_count ?? 0,
        adaptive_prefilter_used: Boolean(data?.adaptive_prefilter_used),
        watchlist_fallback_used: Boolean(data?.watchlist_fallback_used),
        stocks: Array.isArray(stocks) ? stocks.map(normalizeStock) : [],
        execution_candidates: Array.isArray(data?.execution_candidates) ? data.execution_candidates.map(normalizeStock) : [],
        top_gainer_opportunities: Array.isArray(data?.top_gainer_opportunities) ? data.top_gainer_opportunities.map(normalizeStock) : [],
        no_chase_radar: Array.isArray(data?.no_chase_radar) ? data.no_chase_radar.map(normalizeStock) : [],
        total_scanned: data?.universe_count || data?.total_scanned || 0,
      });
    } catch (err) {
      setError(err.name === "AbortError"
        ? "Screener timeout setelah 5 menit. Backend terlalu lama merespons; coba ulang atau turunkan filter intensity."
        : err.message || "Unknown error");
    } finally {
      clearTimeout(timeoutId);
      stopProgress();
      setLoading(false);
    }
  };

  const uploadManualTopGainer = async () => {
    if (!manualFile && !manualText.trim()) {
      setManualError("Belum ada file atau data paste. Klik kotak Upload Excel/CSV sampai nama file tampil, atau paste data asli ke box kanan.");
      return;
    }
    setManualLoading(true);
    setManualError(null);
    setManualResult(null);
    try {
      const form = new FormData();
      form.append("mode", mode.toLowerCase());
      form.append("master_layer", "true");
      if (manualFile) form.append("file", manualFile);
      if (manualText.trim()) form.append("raw_text", manualText.trim());
      const res = await fetch(`${BACKEND_URL}/api/screener/manual-top-gainer/upload`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setManualResult({
        ...data,
        top_3: Array.isArray(data?.top_3) ? data.top_3.map(normalizeStock) : [],
        manual_top_gainer_candidates: Array.isArray(data?.manual_top_gainer_candidates) ? data.manual_top_gainer_candidates.map(normalizeStock) : [],
        execution_candidates: Array.isArray(data?.execution_candidates) ? data.execution_candidates.map(normalizeStock) : [],
        conditional_candidates: Array.isArray(data?.conditional_candidates) ? data.conditional_candidates.map(normalizeStock) : [],
        no_chase_radar: Array.isArray(data?.no_chase_radar) ? data.no_chase_radar.map(normalizeStock) : [],
        rejected_candidates: Array.isArray(data?.rejected_candidates) ? data.rejected_candidates.map(normalizeStock) : [],
      });
    } catch (err) {
      setManualError(err.message || "Upload manual top gainer gagal.");
    } finally {
      setManualLoading(false);
    }
  };

  const clearManualTopGainer = () => {
    setManualFile(null);
    setManualText("");
    setManualResult(null);
    setManualError(null);
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
      <div style={{display:"flex", gap:8, marginBottom:12, alignItems:"center"}}>
        <span style={{fontFamily:"monospace", fontSize:11, color:"#64748b"}}>FILTER INTENSITY:</span>
        {[
          {val:100, label:"100%", desc:"Ketat"},
          {val:75,  label:"75%",  desc:"Sedang"},
          {val:50,  label:"50%",  desc:"Longgar"},
        ].map(opt => (
          <button key={opt.val} onClick={() => setFilterIntensity(opt.val)} style={{
            fontFamily:"monospace", fontSize:11, padding:"4px 12px", borderRadius:6,
            cursor:"pointer", transition:"all 0.2s",
            border: filterIntensity===opt.val ? "1px solid #3b82f6" : "1px solid #cbd5e1",
            background: filterIntensity===opt.val ? "#3b82f6" : "transparent",
            color: filterIntensity===opt.val ? "#fff" : "#64748b",
            fontWeight: filterIntensity===opt.val ? "bold" : "normal",
          }}>
            {opt.label} <span style={{fontSize:9, opacity:0.8}}>{opt.desc}</span>
          </button>
        ))}
      </div>
      <button onClick={runScreener} disabled={loading} style={S.runBtn}>
        {loading ? "SCANNING..." : "RUN SCREENER"}
      </button>

      <section style={S.manualBox}>
        <div style={S.manualHeader}>
          <div>
            <div style={S.manualTitle}>MANUAL TOP GAINER FEED</div>
            <div style={S.manualSubtitle}>Upload Excel/CSV Stockbit atau paste tabel setelah 09.15; terminal pilih Top 3 untuk dikirim ke Analytic.</div>
          </div>
          <span style={S.manualBadge}>hemat token</span>
        </div>
        <div style={S.manualGrid}>
          <div
            style={S.fileDrop}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files?.[0];
              if (file) setManualFile(file);
            }}
          >
            <input
              type="file"
              accept=".xlsx,.xls,.csv,.txt"
              style={S.fileInput}
              onChange={(e) => setManualFile(e.target.files?.[0] || null)}
            />
            <span style={S.fileTitle}>{manualFile ? manualFile.name : "Belum ada file dipilih"}</span>
            <span style={S.fileSub}>Klik di sini untuk pilih file. Nama file harus tampil sebelum score dijalankan.</span>
            <span style={S.fileHint}>Format Stockbit: Symbol, Price(+%), Value, Volume, Freq, Net Foreign</span>
          </div>
          <textarea
            value={manualText}
            onChange={(e) => setManualText(e.target.value)}
            placeholder={"Atau paste tabel di sini, contoh:\nLAJU 75(+25.00%) 2.97B 260.66K 3.49K 252.96M\nWBSA 740(+17.46%) 148.30M 613 189 417K"}
            style={S.manualTextarea}
          />
        </div>
        <div style={S.manualActions}>
          <button onClick={uploadManualTopGainer} disabled={manualLoading || (!manualFile && !manualText.trim())} style={{
            ...S.manualPrimaryBtn,
            ...((manualLoading || (!manualFile && !manualText.trim())) ? S.manualPrimaryBtnDisabled : {}),
          }}>
            {manualLoading ? "PROCESSING..." : "SCORE MANUAL TOP GAINER"}
          </button>
          <button onClick={clearManualTopGainer} disabled={manualLoading} style={S.manualSecondaryBtn}>CLEAR</button>
        </div>
        {manualError && <div style={S.errorBox}><strong>MANUAL FEED ERROR:</strong> {manualError}</div>}
        {manualResult && (
          <div style={S.manualResultBox}>
            <div style={S.metaRow}>
              <span style={S.metaBadge}>Manual Parsed: {manualResult.parsed_count || 0}</span>
              <span style={S.metaBadge}>Source: {manualResult.source || "-"}</span>
              <span style={S.metaBadge}>Mode: {String(manualResult.mode || mode).toUpperCase()}</span>
            </div>
            <div style={S.infoBox}>
              {manualResult.message} {manualResult.quota_policy}
            </div>
            {manualResult.top_3?.length > 0 && (
              <>
                <button
                  onClick={() => sendBatchToAnalytic(manualResult.top_3, mode)}
                  style={S.manualBatchBtn}
                >
                  ANALYZE 3 SAHAM SEKALIGUS
                </button>
                <LanePanel
                  title="Manual Top 3 - Analytic Ready"
                  subtitle="Hanya 3 terbaik dari upload. Klik tombol batch untuk masuk Analytic intraday cepat."
                  stocks={manualResult.top_3}
                  mode={mode}
                  sendToAnalytic={sendToAnalytic}
                />
              </>
            )}
          </div>
        )}
      </section>

      {loading && (
        <div style={S.progressBox}>
          <div style={S.progressHeader}>
            <span style={S.progressMsg}>{progressMsg}</span>
            <span style={S.progressPct}>{progress}%</span>
          </div>
          <div style={S.progressBg}>
            <div style={{ ...S.progressFill, width: `${progress}%` }} />
          </div>
          <p style={S.progressSub}>
            {progress >= 90
              ? `Menunggu response backend... ${elapsedSec}s. Ini bukan freeze; engine sedang finalisasi hasil.`
              : `Scanning saham IDX dengan 11 engines... ${elapsedSec}s`}
          </p>
        </div>
      )}

      {error && <div style={S.errorBox}><strong>ERROR:</strong> {error}</div>}

      {result && !loading && (
        <div style={S.resultsSection}>
          <div style={S.metaRow}>
            <span style={S.metaBadge}>Mode: {result.mode.toUpperCase()}</span>
            <span style={S.metaBadge}>Status: {result.status.toUpperCase()}</span>
            <span style={S.metaBadge}>Scanned: {result.total_scanned}</span>
            <span style={S.metaBadge}>Candidates: {result.candidate_count}</span>
            <span style={S.metaBadge}>Qualified: {result.qualified_count}</span>
            {result.top_gainer_universe_count > 0 && (
              <span style={S.metaBadge}>Top Gainer Lane: {result.top_gainer_universe_count}</span>
            )}
            {result.market_execution_regime?.key && (
              <span style={S.metaBadge}>Regime: {String(result.market_execution_regime.key).replace(/_/g, " ")}</span>
            )}
            <span style={S.metaBadge}>Session: {result.session_id}</span>
          </div>
          {result.opening_feed_fallback_count > 0 && (
            <div style={S.warningBox}>
              <strong>OPENING FEED FALLBACK:</strong> {result.opening_feed_fallback_count} top gainer dipertahankan sebagai radar karena daily OHLCV belum update hari ini. Jangan dianggap entry otomatis sebelum Analytical mengonfirmasi data live, flow, dan orderbook.
            </div>
          )}
          {result.market_execution_regime && (
            <div style={S.regimeBox}>
              <div style={S.regimeTitle}>{result.market_execution_regime.label || result.market_execution_regime.key}</div>
              <div style={S.regimeGrid}>
                <span>IHSG: {Number(result.market_execution_regime.ihsg_change_pct || 0).toFixed(2)}%</span>
                <span>LQ45: {Number(result.market_execution_regime.lq45_change_pct || 0).toFixed(2)}%</span>
                <span>Breadth: {Number(result.market_execution_regime.breadth_pct || 0).toFixed(1)}%</span>
                <span>Top Gainer: {result.market_execution_regime.top_gainer_count || 0}</span>
              </div>
              <p style={S.regimePolicy}>{result.market_execution_regime.policy}</p>
            </div>
          )}
          {(result.status !== "ok" || result.watchlist_fallback_used) && (
            <div style={S.warningBox}>
              <strong>{result.watchlist_fallback_used ? "WATCHLIST MODE:" : "DATA WARNING:"}</strong> {result.message || "Screener berjalan dalam mode aman."}
              {result.backend_error && <div style={{ marginTop: 6, fontSize: 11 }}>{result.backend_error}</div>}
            </div>
          )}
          {result.stocks.length === 0 && result.top_gainer_opportunities.length === 0 && result.no_chase_radar.length === 0 ? (
            <div style={S.emptyBox}>
              <p>{result.candidate_count === 0 ? "Belum ada saham yang lolos prefilter hari ini." : "Belum ada saham yang lolos scoring dan disqualifier hari ini."}</p>
              <p style={{ fontSize: 12, marginTop: 8 }}>
                Backend scan {result.total_scanned} saham; candidate {result.candidate_count}, scored {result.scored_count}, qualified {result.qualified_count}.
              </p>
              {rawResponse?.debug?.prefilter?.reason_counts && (
                <p style={{ fontSize: 12, marginTop: 8 }}>
                  Alasan dominan: {Object.entries(rawResponse.debug.prefilter.reason_counts).map(([k, v]) => `${k} ${v}`).join(", ")}.
                </p>
              )}
              {rawResponse && <pre style={S.debugPre}>{JSON.stringify(rawResponse, null, 2)}</pre>}
            </div>
          ) : (
            <>
              {result.stocks.length > 0 && (
                <LanePanel
                  title="Execution Review"
                  subtitle="Full-variable candidates. Analytical tetap final validator."
                  stocks={result.stocks}
                  mode={mode}
                  sendToAnalytic={sendToAnalytic}
                />
              )}
              {result.top_gainer_opportunities.length > 0 && (
                <LanePanel
                  title="Top Gainer Opportunity"
                  subtitle="Sweet spot 5%-10%. Analytical boleh menjadi conditional buy-stop jika flow valid."
                  stocks={result.top_gainer_opportunities}
                  mode={mode}
                  sendToAnalytic={sendToAnalytic}
                />
              )}
              {result.no_chase_radar.length > 0 && (
                <LanePanel
                  title="No-Chase Radar"
                  subtitle="Mover extended. Jangan market chase; tunggu reset/base baru."
                  stocks={result.no_chase_radar}
                  mode={mode}
                  sendToAnalytic={sendToAnalytic}
                />
              )}
              {result.stocks.length === 0 && (
                <div style={S.infoBox}>
                  Tidak ada saham yang lolos menjadi execution candidate penuh. Namun radar di bawah tetap ditampilkan agar top gainer tidak hilang dari layar.
                </div>
              )}
            </>
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

function LanePanel({ title, subtitle, stocks, mode, sendToAnalytic }) {
  if (!stocks?.length) return null
  return (
    <section style={S.laneSection}>
      <div style={S.laneHeader}>
        <div>
          <div style={S.laneTitle}>{title}</div>
          <div style={S.laneSubtitle}>{subtitle}</div>
        </div>
        <span style={S.laneCount}>{stocks.length}</span>
      </div>
      <div style={S.stockGrid}>
        {stocks.map((stock, idx) => (
          <StockCard key={`${title}-${stock.ticker || idx}`} stock={stock} rank={idx + 1} onClick={() => sendToAnalytic(stock.ticker, mode, stock)} />
        ))}
      </div>
    </section>
  )
}

function StockCard({ stock, rank, onClick }) {
  const signal = (stock.signal || "NEUTRAL").toUpperCase();
  const sc = SIGNAL_COLOR[signal] || SIGNAL_COLOR.NEUTRAL;
  const institutionalRank = getInstitutionalRank(stock.final_score || stock.score || 0);
  const lane = stock.screener_lane || (stock.top_gainer_opportunity?.available ? "TOP_GAINER_OPPORTUNITY" : stock.no_chase_radar ? "NO_CHASE_RADAR" : "EXECUTION_CANDIDATE")
  const laneMeta = LANE_META[lane] || { label: String(lane || "Candidate").replace(/_/g, " "), color: "#64748b", bg: "#f8fafc" }
  return (
    <div style={{ ...S.card, cursor: "pointer" }} onClick={onClick} title={`Analyze ${stock.ticker}`}>
      <div style={S.cardHeader}>
        <span style={S.rank}>#{rank}</span>
        <span style={S.ticker}>{stock.ticker}</span>
        <span style={{ ...S.signalBadge, backgroundColor: sc + "22", color: sc, border: "1px solid " + sc }}>{signal}</span>
      </div>
      <div style={S.cardBody}>
        <div style={{ ...S.laneBadge, color: laneMeta.color, borderColor: laneMeta.color, backgroundColor: laneMeta.bg }}>
          {laneMeta.label}
        </div>

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
        {stock.data_warning && (
          <div style={S.dataWarningBox}>
            {stock.data_warning}
          </div>
        )}
        {stock.top_gainer_opportunity?.available && (
          <div style={S.moverBox}>
            <div style={S.moverTitle}>Top Gainer Sweet Spot</div>
            <div style={S.officialGrid}>
              <span>Rank: #{stock.top_gainer_opportunity.rank || "-"}</span>
              <span>Move: {Number(stock.top_gainer_opportunity.change_pct || stock.change_pct || 0).toFixed(2)}%</span>
              <span>Tier: {String(stock.top_gainer_opportunity.opportunity_tier || "-").replace(/_/g, " ")}</span>
              <span>Bias: {String(stock.top_gainer_opportunity.execution_bias || "-").replace(/_/g, " ")}</span>
              <span>Entry: {stock.top_gainer_opportunity.preferred_entry || "-"}</span>
            </div>
          </div>
        )}
        {stock.manual_master_layer && (
          <div style={S.masterLayerBox}>
            <div style={S.masterLayerTitle}>Master Layer Ultimate</div>
            <div style={S.officialGrid}>
              <span>Status: {String(stock.manual_master_layer.status || "-").replace(/_/g, " ")}</span>
              <span>Score: {Number(stock.manual_master_layer.score || 0).toFixed(1)}</span>
              <span>Pass: {stock.manual_master_layer.pass_count ?? "-"}</span>
              <span>Fail: {stock.manual_master_layer.fail_count ?? "-"}</span>
              <span>Unknown: {stock.manual_master_layer.unknown_count ?? "-"}</span>
              <span>Policy: shortlist only</span>
            </div>
          </div>
        )}
        {stock.top_gainer_opportunity?.radar_only && (
          <div style={S.noChaseBox}>
            <div style={S.noChaseTitle}>No-Chase Top Gainer Radar</div>
            <div style={S.officialGrid}>
              <span>Move: {Number(stock.top_gainer_opportunity.change_pct || stock.change_pct || 0).toFixed(2)}%</span>
              <span>Tier: {String(stock.top_gainer_opportunity.opportunity_tier || "-").replace(/_/g, " ")}</span>
              <span>Bias: {String(stock.top_gainer_opportunity.execution_bias || "-").replace(/_/g, " ")}</span>
              <span>Rule: wait reset/base</span>
            </div>
          </div>
        )}
        {stock.money_maker?.available && (
          <div style={S.moneyMakerBox}>
            <div style={S.moneyMakerTitle}>Money Maker Core</div>
            <div style={S.officialGrid}>
              <span>Score: {Number(stock.money_maker.score || 0).toFixed(1)}</span>
              <span>BFD: {Number(stock.money_maker.bfd_score || 0)}/5</span>
              <span>Phase: {String(stock.money_maker.phase || "-").replace(/_/g, " ")}</span>
              <span>Verdict: {String(stock.money_maker.verdict || "-").replace(/_/g, " ")}</span>
              <span>Pattern: {(stock.money_maker.patterns || [])[0]?.name?.replace(/_/g, " ") || "-"}</span>
              <span>Exec: {String(stock.money_maker.execution_intelligence?.stance || "-").replace(/_/g, " ")}</span>
            </div>
          </div>
        )}
        {stock.official_enrichment && (
          <div style={S.officialBox}>
            <div style={S.officialTitle}>Official Invezgo</div>
            <div style={S.officialGrid}>
              <span>Value: {Number(stock.official_enrichment.liquidity?.value || 0).toLocaleString("id-ID")}</span>
              <span>Freq: {Number(stock.official_enrichment.liquidity?.freq || 0).toLocaleString("id-ID")}</span>
              <span>MTF: {stock.official_enrichment.multi_timeframe?.available ? "ON" : "OFF"}</span>
              <span>Flow: {Object.values(stock.official_enrichment.flow_tags || {}).filter(Boolean).join(", ") || "-"}</span>
            </div>
          </div>
        )}
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
  manualBox: { backgroundColor: "#ffffff", border: "1px solid #bbf7d0", borderRadius: 10, padding: 16, marginBottom: 20, boxShadow: "0 2px 8px rgba(0,0,0,0.05)" },
  manualHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 12 },
  manualTitle: { color: "#15803d", fontSize: 14, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 1.5 },
  manualSubtitle: { color: "#64748b", fontSize: 12, marginTop: 3, lineHeight: 1.45 },
  manualBadge: { border: "1px solid #22c55e", color: "#15803d", backgroundColor: "#f0fdf4", borderRadius: 999, padding: "4px 10px", fontSize: 10, fontWeight: "bold", textTransform: "uppercase", whiteSpace: "nowrap" },
  manualGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 },
  fileDrop: { border: "1px dashed #86efac", backgroundColor: "#f0fdf4", borderRadius: 8, padding: 14, cursor: "pointer", display: "flex", flexDirection: "column", justifyContent: "center", minHeight: 110 },
  fileInput: { display: "block", width: "100%", maxWidth: 420, marginBottom: 10, fontSize: 12, color: "#14532d", backgroundColor: "#ffffff", border: "1px solid #86efac", borderRadius: 6, padding: 8 },
  fileTitle: { color: "#14532d", fontWeight: "bold", fontSize: 13, marginBottom: 6, wordBreak: "break-word" },
  fileSub: { color: "#64748b", fontSize: 11, lineHeight: 1.45 },
  fileHint: { color: "#16a34a", fontSize: 10, lineHeight: 1.45, marginTop: 6, fontWeight: "600" },
  manualTextarea: { minHeight: 110, resize: "vertical", border: "1px solid #cbd5e1", borderRadius: 8, padding: 12, fontSize: 12, color: "#1e293b", fontFamily: "monospace", outline: "none", backgroundColor: "#f8fafc" },
  manualActions: { display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12, marginBottom: 8 },
  manualPrimaryBtn: { padding: "10px 16px", border: "none", borderRadius: 6, backgroundColor: "#16a34a", color: "#ffffff", fontSize: 12, fontWeight: "bold", cursor: "pointer", letterSpacing: 0.5 },
  manualPrimaryBtnDisabled: { backgroundColor: "#94a3b8", cursor: "not-allowed", opacity: 0.65 },
  manualSecondaryBtn: { padding: "10px 16px", border: "1px solid #cbd5e1", borderRadius: 6, backgroundColor: "#ffffff", color: "#64748b", fontSize: 12, fontWeight: "bold", cursor: "pointer", letterSpacing: 0.5 },
  manualBatchBtn: { width: "100%", border: "none", borderRadius: 8, padding: "12px 16px", marginBottom: 12, backgroundColor: "#0ea5e9", color: "#ffffff", fontSize: 13, fontWeight: "bold", letterSpacing: 1, cursor: "pointer" },
  manualResultBox: { borderTop: "1px solid #e2e8f0", paddingTop: 12, marginTop: 8 },
  progressBox: { backgroundColor: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 10, padding: 20, marginBottom: 20, boxShadow: "0 2px 8px rgba(0,0,0,0.06)" },
  progressHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  progressMsg: { fontSize: 13, color: "#0ea5e9", fontWeight: "600" },
  progressPct: { fontSize: 20, fontWeight: "bold", color: "#0ea5e9" },
  progressBg: { backgroundColor: "#e2e8f0", height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 8 },
  progressFill: { height: "100%", backgroundColor: "#0ea5e9", borderRadius: 5, transition: "width 0.5s ease", backgroundImage: "linear-gradient(90deg, #0ea5e9, #16a34a)" },
  progressSub: { fontSize: 11, color: "#94a3b8", margin: 0 },
  errorBox: { backgroundColor: "#fee2e2", border: "1px solid #fca5a5", borderRadius: 6, padding: 16, color: "#dc2626", marginBottom: 16, fontSize: 13 },
  warningBox: { backgroundColor: "#fef3c7", border: "1px solid #f59e0b", borderRadius: 6, padding: 14, color: "#92400e", marginBottom: 16, fontSize: 13 },
  infoBox: { backgroundColor: "#eff6ff", border: "1px solid #93c5fd", borderRadius: 6, padding: 14, color: "#1d4ed8", marginBottom: 16, fontSize: 13 },
  regimeBox: { backgroundColor: "#ffffff", border: "1px solid #bae6fd", borderRadius: 8, padding: 14, marginBottom: 16 },
  regimeTitle: { color: "#0369a1", fontWeight: "bold", fontSize: 13, textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 },
  regimeGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 6, fontSize: 11, color: "#475569", fontFamily: "monospace" },
  regimePolicy: { margin: "8px 0 0", color: "#64748b", fontSize: 12 },
  resultsSection: { marginTop: 8 },
  metaRow: { display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 },
  metaBadge: { backgroundColor: "#e0f2fe", padding: "4px 10px", borderRadius: 4, fontSize: 11, color: "#0369a1", fontWeight: "600", border: "1px solid #bae6fd" },
  emptyBox: { textAlign: "center", padding: 32, border: "1px dashed #cbd5e1", borderRadius: 8, color: "#94a3b8", backgroundColor: "#ffffff" },
  debugPre: { backgroundColor: "#f8fafc", padding: 12, borderRadius: 4, fontSize: 10, color: "#64748b", textAlign: "left", marginTop: 12, maxHeight: 200, overflow: "auto" },
  laneSection: { marginBottom: 18 },
  laneHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 10 },
  laneTitle: { color: "#1e293b", fontSize: 14, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 1 },
  laneSubtitle: { color: "#64748b", fontSize: 12, marginTop: 2 },
  laneCount: { minWidth: 28, height: 28, borderRadius: 14, backgroundColor: "#e0f2fe", color: "#0369a1", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: "bold", fontSize: 12 },
  stockGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 },
  card: { backgroundColor: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 10, overflow: "hidden", boxShadow: "0 2px 8px rgba(0,0,0,0.06)" },
  cardHeader: { display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid #f1f5f9", backgroundColor: "#f8fafc" },
  rank: { color: "#94a3b8", fontSize: 11, minWidth: 24, fontWeight: "bold" },
  ticker: { color: "#0ea5e9", fontWeight: "bold", fontSize: 16, flex: 1, letterSpacing: 1 },
  signalBadge: { padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: "bold", letterSpacing: 1 },
  cardBody: { padding: "12px 16px" },
  laneBadge: { display: "inline-block", border: "1px solid", borderRadius: 5, padding: "3px 7px", fontSize: 10, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 10 },
  scoreRow: { display: "flex", justifyContent: "space-between", marginBottom: 6 },
  scoreLabel: { color: "#94a3b8", fontSize: 12 },
  scoreValue: { color: "#d97706", fontSize: 16, fontWeight: "bold" },
  priceRow: { display: "flex", justifyContent: "space-between", marginBottom: 10 },
  priceLabel: { color: "#94a3b8", fontSize: 12 },
  priceValue: { color: "#1e293b", fontSize: 13, fontWeight: "600" },
  dataWarningBox: { border: "1px solid #f59e0b", backgroundColor: "#fffbeb", color: "#92400e", borderRadius: 6, padding: 8, marginBottom: 10, fontSize: 10, lineHeight: 1.4 },
  officialBox: { border: "1px solid #bbf7d0", backgroundColor: "#f0fdf4", borderRadius: 6, padding: 8, marginBottom: 10 },
  officialTitle: { color: "#15803d", fontSize: 10, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 1, marginBottom: 5 },
  moneyMakerBox: { border: "1px solid #f0abfc", backgroundColor: "#fdf4ff", borderRadius: 6, padding: 8, marginBottom: 10 },
  moneyMakerTitle: { color: "#a21caf", fontSize: 10, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 1, marginBottom: 5 },
  moverBox: { border: "1px solid #fdba74", backgroundColor: "#fff7ed", borderRadius: 6, padding: 8, marginBottom: 10 },
  moverTitle: { color: "#c2410c", fontSize: 10, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 1, marginBottom: 5 },
  masterLayerBox: { border: "1px solid #86efac", backgroundColor: "#f0fdf4", borderRadius: 6, padding: 8, marginBottom: 10 },
  masterLayerTitle: { color: "#15803d", fontSize: 10, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 1, marginBottom: 5 },
  noChaseBox: { border: "1px solid #f59e0b", backgroundColor: "#fffbeb", borderRadius: 6, padding: 8, marginBottom: 10 },
  noChaseTitle: { color: "#b45309", fontSize: 10, fontWeight: "bold", textTransform: "uppercase", letterSpacing: 1, marginBottom: 5 },
  officialGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, color: "#475569", fontSize: 10, fontFamily: "monospace" },
  barBg: { backgroundColor: "#e2e8f0", height: 5, borderRadius: 3, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 3, transition: "width 0.5s ease" },
  initialBox: { textAlign: "center", padding: 48, border: "1px dashed #cbd5e1", borderRadius: 8, backgroundColor: "#ffffff" },
};
