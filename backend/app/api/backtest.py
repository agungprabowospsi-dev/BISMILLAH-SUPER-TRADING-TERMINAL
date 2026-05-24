from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import logging
import asyncio
import json
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()

class BacktestRequest(BaseModel):
    mode: str = "swing"
    timeframe: str = "daily"
    period: str = "5y"
    universe: int = 20
    min_score: float = 65.0

class SingleBacktestRequest(BaseModel):
    ticker: str
    mode: str = "swing"
    timeframe: str = "daily"
    period: str = "1y"
    min_score: float = 65.0

# ── Job storage di Redis ──────────────────────────────────────
def get_redis():
    from app.core.redis_client import get_redis
    return get_redis()

async def save_job(job_id: str, data: dict):
    try:
        r = get_redis()
        await r.setex(f"backtest:{job_id}", 86400, json.dumps(data))
    except Exception as e:
        logger.error(f"Redis save error: {e}")

async def get_job(job_id: str) -> dict:
    try:
        r = get_redis()
        raw = await r.get(f"backtest:{job_id}")
        return json.loads(raw) if raw else None
    except:
        return None

# ── Helper ATR ────────────────────────────────────────────────
def calc_atr(candles: list, period: int = 14) -> float:
    if len(candles) < period + 1:
        return candles[-1]["close"] * 0.02
    trs = []
    for i in range(1, period + 1):
        c = candles[-i]
        p = candles[-i-1]
        tr = max(c["high"]-c["low"], abs(c["high"]-p["close"]), abs(c["low"]-p["close"]))
        trs.append(tr)
    return sum(trs) / len(trs)

def _avg(values: list) -> float:
    return sum(values) / len(values) if values else 0.0

def fast_historical_score(window: list, mode: str) -> float:
    """Fast deterministic score for repeated historical backtest windows."""
    if len(window) < 30:
        return 0.0

    closes = [float(c.get("close", 0) or 0) for c in window]
    highs = [float(c.get("high", 0) or 0) for c in window]
    lows = [float(c.get("low", 0) or 0) for c in window]
    volumes = [float(c.get("volume", 0) or 0) for c in window]
    close = closes[-1]
    prev = closes[-2] if len(closes) > 1 else close
    if close <= 0 or prev <= 0:
        return 0.0

    ma5 = _avg(closes[-5:])
    ma20 = _avg(closes[-20:])
    ma50 = _avg(closes[-50:]) if len(closes) >= 50 else ma20
    vol20 = _avg(volumes[-20:])
    vol_ratio = volumes[-1] / vol20 if vol20 else 1.0
    momentum_3 = (close - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 and closes[-4] else 0
    momentum_10 = (close - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 and closes[-11] else 0
    range20_high = max(highs[-20:])
    range20_low = min(lows[-20:])
    range_pos = (close - range20_low) / max(range20_high - range20_low, 1)
    atr = calc_atr(window)
    atr_pct = atr / close * 100 if close else 0

    score = 45.0
    if close > ma20:
        score += 8
    if ma20 > ma50:
        score += 8
    if ma5 > ma20:
        score += 6
    if 0.3 <= momentum_3 <= 6:
        score += 7
    elif momentum_3 < -1:
        score -= 8
    if 1 <= momentum_10 <= 15:
        score += 7
    elif momentum_10 < -3:
        score -= 8
    if 1.2 <= vol_ratio <= 3.5:
        score += 8
    elif vol_ratio < 0.7:
        score -= 5
    if 0.55 <= range_pos <= 0.9:
        score += 7
    elif range_pos > 0.96:
        score -= 4
    if mode == "intraday" and 1.0 <= atr_pct <= 6.0:
        score += 4
    elif atr_pct > 10:
        score -= 6

    return round(max(0.0, min(100.0, score)), 2)

# ── Core backtest per saham ───────────────────────────────────
async def backtest_single(ticker: str, candles: list, mode: str, min_score: float) -> dict:
    from app.engines.master_runner import run_all_engines
    from app.knowledge_base import kb_service

    WINDOW = 60
    trades = []
    equity = 100.0
    equity_curve = []
    in_trade = False
    current_trade = None
    hold_days = 0
    MAX_HOLD = 10 if mode == "swing" else 1

    i = WINDOW
    while i < len(candles):
        current = candles[i]
        window = candles[max(0, i-WINDOW):i]

        # Check exit
        if in_trade and current_trade:
            hold_days += 1
            price = current["close"]
            entry = current_trade["entry"]
            atr_entry = current_trade.get("atr_entry", entry * 0.02)

            # ── Trailing SL: geser SL ke breakeven setelah profit > 1x ATR ──
            current_pnl = ((price - entry) / entry) * 100
            if current_pnl >= (atr_entry / entry * 100) and current_trade["sl"] < entry:
                current_trade["sl"] = round(entry * 1.003)  # breakeven + 0.3% buffer

            hit_sl = price <= current_trade["sl"]
            hit_tp = price >= current_trade["tp1"]
            hit_max = hold_days >= MAX_HOLD

            if hit_sl or hit_tp or hit_max:
                pnl_pct = ((price - entry) / entry) * 100

                # ── Dynamic threshold: komisi IDX 2x (beli+jual) ~0.35% ──
                commission = 0.35
                net_pnl = pnl_pct - commission
                min_win_threshold = 2.0   # minimal net profit untuk dianggap WIN
                loss_threshold = -1.0     # expired rugi > 1% tetap LOSS

                if hit_tp:
                    result = "WIN"
                elif hit_sl:
                    result = "LOSS"
                elif hit_max:
                    if net_pnl >= min_win_threshold:
                        result = "WIN"       # expired tapi profit cukup = WIN
                    elif net_pnl <= loss_threshold:
                        result = "LOSS"      # expired tapi rugi = LOSS
                    else:
                        result = "EXPIRED"   # zona abu-abu (0% - 2%)

                current_trade.update({
                    "exit_price": price,
                    "exit_date": current["date"],
                    "pnl_pct": round(pnl_pct, 2),
                    "net_pnl_pct": round(net_pnl, 2),
                    "result": result,
                    "hold_days": hold_days,
                    "exit_reason": "TP" if hit_tp else ("SL" if hit_sl else "MAX_HOLD")
                })
                equity *= (1 + net_pnl/100)
                trades.append(current_trade)
                equity_curve.append({"date": current["date"], "equity": round(equity, 2)})
                in_trade = False
                current_trade = None
                hold_days = 0

        # Generate signal setiap 3 candle
        if not in_trade and i % 3 == 0:
            try:
                if mode == "intraday":
                    score = fast_historical_score(window, mode)
                    rag_boost = 0
                else:
                    eng = await run_all_engines(ticker, window, mode)
                    score = eng.get("composite_score", 0)

                    # RAG boost
                    try:
                        rag = await kb_service.get_kb_context_for_engine("PriceActionEngine", ticker)
                        rag_boost = 5 if rag and len(rag) > 100 else 0
                    except:
                        rag_boost = 0

                total_score = score + rag_boost

                if total_score >= min_score:
                    price = current["close"]
                    atr = calc_atr(window)
                    sl_mult = 1.5 if mode == "swing" else 1.0
                    tp_mult = 2.0 if mode == "swing" else 1.5
                    current_trade = {
                        "ticker": ticker,
                        "entry_date": current["date"],
                        "entry": price,
                        "atr_entry": atr,   # simpan ATR untuk trailing SL
                        "sl": round(price - sl_mult * atr),
                        "tp1": round(price + tp_mult * atr),
                        "tp2": round(price + (tp_mult + 1) * atr),
                        "score": round(total_score, 1),
                        "rag_boost": rag_boost,
                        "mode": mode
                    }
                    in_trade = True
                    hold_days = 0
            except Exception as e:
                logger.warning(f"Engine error {ticker} candle {i}: {e}")

        i += 1

    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    expireds = [t for t in trades if t["result"] == "EXPIRED"]

    total_decided = len(wins) + len(losses)  # exclude EXPIRED dari winrate
    winrate = len(wins) / total_decided * 100 if total_decided > 0 else 0

    avg_win = sum(t["net_pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["net_pnl_pct"] for t in losses) / len(losses) if losses else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 999

    # Expectancy per trade
    wr = winrate / 100
    expectancy = (wr * avg_win) + ((1 - wr) * avg_loss) if total_decided > 0 else 0

    return {
        "ticker": ticker,
        "total_trades": len(trades),
        "total_wins": len(wins),
        "total_losses": len(losses),
        "total_expired": len(expireds),
        "winrate": round(winrate, 1),
        "profit_factor": round(profit_factor, 2),
        "expectancy_pct": round(expectancy, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "final_equity": round(equity, 2),
        "trades": trades
    }

# ── Universe Backtest Background Job ─────────────────────────
async def run_universe_backtest(job_id: str, req: BacktestRequest):
    from app.core import invesgo

    await save_job(job_id, {
        "status": "running",
        "progress": 0,
        "message": "Memulai universe backtest...",
        "started_at": datetime.now().isoformat()
    })

    try:
        # 1. Ambil daftar saham
        await save_job(job_id, {"status": "running", "progress": 5, "message": "Mengambil daftar saham IDX..."})
        stock_list = await invesgo.get_stock_list()

        # Filter liquid stocks
        tickers = []
        for s in stock_list:
            code = s.get("code") or s.get("ticker") or s.get("symbol")
            if code:
                tickers.append(code)

        # Limit universe
        tickers = tickers[:req.universe]
        total = len(tickers)

        await save_job(job_id, {
            "status": "running",
            "progress": 10,
            "message": f"Memproses {total} saham...",
            "total_stocks": total
        })

        # 2. Backtest per saham
        all_results = []
        all_trades = []

        for idx, ticker in enumerate(tickers):
            try:
                progress = 10 + int((idx / total) * 80)
                await save_job(job_id, {
                    "status": "running",
                    "progress": progress,
                    "message": f"Backtesting {ticker} ({idx+1}/{total})...",
                    "current_ticker": ticker
                })

                candles = await invesgo.get_ohlcv_daily(ticker, period=req.period)
                if not candles or len(candles) < 80:
                    continue

                formatted = [{
                    "date": str(c.get("date",""))[:10],
                    "open": float(c.get("open") or 0),
                    "high": float(c.get("high") or 0),
                    "low": float(c.get("low") or 0),
                    "close": float(c.get("close") or 0),
                    "volume": float(c.get("volume") or 0)
                } for c in candles]

                result = await backtest_single(ticker, formatted, req.mode, req.min_score)
                if result["total_trades"] > 0:
                    all_results.append(result)
                    all_trades.extend(result["trades"])

                await asyncio.sleep(0.1)

            except Exception as e:
                logger.warning(f"Skip {ticker}: {e}")
                continue

        # 3. Aggregate statistik
        await save_job(job_id, {"status": "running", "progress": 92, "message": "Menghitung statistik..."})

        if not all_trades:
            await save_job(job_id, {"status": "failed", "progress": 100, "message": "Tidak ada trade yang dihasilkan"})
            return

        total_trades = len(all_trades)
        wins = [t for t in all_trades if t["result"] == "WIN"]
        losses = [t for t in all_trades if t["result"] == "LOSS"]
        expireds = [t for t in all_trades if t["result"] == "EXPIRED"]

        # Winrate hanya dari trade yang decided (WIN/LOSS), exclude EXPIRED
        total_decided = len(wins) + len(losses)
        winrate = len(wins) / total_decided * 100 if total_decided > 0 else 0

        avg_win = sum(t["net_pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["net_pnl_pct"] for t in losses) / len(losses) if losses else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 999

        # Expectancy per trade
        wr = winrate / 100
        expectancy = (wr * avg_win) + ((1 - wr) * avg_loss) if total_decided > 0 else 0

        # Max drawdown pakai net_pnl
        equity = 100.0
        peak = 100.0
        max_dd = 0
        for t in sorted(all_trades, key=lambda x: x.get("exit_date","")):
            equity *= (1 + t["net_pnl_pct"]/100)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Per tahun breakdown
        yearly = {}
        for t in all_trades:
            year = t.get("exit_date","")[:4]
            if year not in yearly:
                yearly[year] = {"trades": 0, "wins": 0, "losses": 0, "expireds": 0, "total_pnl": 0}
            yearly[year]["trades"] += 1
            if t["result"] == "WIN":
                yearly[year]["wins"] += 1
            elif t["result"] == "LOSS":
                yearly[year]["losses"] += 1
            else:
                yearly[year]["expireds"] += 1
            yearly[year]["total_pnl"] += t["net_pnl_pct"]

        yearly_summary = {
            y: {
                "trades": d["trades"],
                "wins": d["wins"],
                "losses": d["losses"],
                "expireds": d["expireds"],
                "winrate": round(d["wins"] / max(d["wins"] + d["losses"], 1) * 100, 1),
                "total_pnl": round(d["total_pnl"], 2)
            } for y, d in yearly.items() if d["trades"] > 0
        }

        # Top performers
        top_stocks = sorted(all_results, key=lambda x: x["winrate"], reverse=True)[:10]

        final_result = {
            "status": "completed",
            "progress": 100,
            "message": "Backtest selesai!",
            "completed_at": datetime.now().isoformat(),
            "config": {
                "mode": req.mode,
                "timeframe": req.timeframe,
                "period": req.period,
                "universe": req.universe,
                "min_score": req.min_score,
                "signal_engine": "fast_historical_score" if req.mode == "intraday" else "full_engine_stack"
            },
            "summary": {
                "total_stocks_tested": len(all_results),
                "total_trades": total_trades,
                "total_wins": len(wins),
                "total_losses": len(losses),
                "total_expired": len(expireds),
                "winrate": round(winrate, 1),
                "profit_factor": round(profit_factor, 2),
                "expectancy_pct": round(expectancy, 2),
                "max_drawdown": round(max_dd, 1),
                "avg_win_pct": round(avg_win, 2),
                "avg_loss_pct": round(avg_loss, 2),
                "final_equity": round(equity, 2)
            },
            "yearly_breakdown": yearly_summary,
            "top_performers": top_stocks[:5],
            "recent_trades": sorted(all_trades, key=lambda x: x.get("exit_date",""), reverse=True)[:20]
        }

        await save_job(job_id, final_result)

    except Exception as e:
        logger.error(f"Universe backtest error: {e}")
        await save_job(job_id, {"status": "failed", "progress": 0, "message": str(e)})

# ── API Endpoints ─────────────────────────────────────────────
@router.post("/universe/start")
async def start_universe_backtest(req: BacktestRequest, background_tasks: BackgroundTasks):
    job_id = f"bt_{uuid.uuid4().hex[:8]}"
    background_tasks.add_task(run_universe_backtest, job_id, req)
    return {
        "job_id": job_id,
        "message": "Backtest dimulai di background",
        "status_url": f"/api/backtest/status/{job_id}",
        "config": req.dict()
    }

@router.get("/status/{job_id}")
async def get_backtest_status(job_id: str):
    job = await get_job(job_id)
    if not job:
        return {"error": "Job tidak ditemukan"}
    return job

@router.post("/single/run")
async def run_single_backtest(req: SingleBacktestRequest, background_tasks: BackgroundTasks):
    job_id = f"bt_{uuid.uuid4().hex[:8]}"

    async def single_job(job_id, req):
        from app.core import invesgo
        await save_job(job_id, {"status": "running", "progress": 10, "message": f"Mengambil data {req.ticker}..."})
        try:
            candles = await invesgo.get_ohlcv_daily(req.ticker, period=req.period)
            if not candles or len(candles) < 30:
                await save_job(job_id, {"status": "failed", "message": "Data tidak cukup"})
                return
            formatted = [{
                "date": str(c.get("date",""))[:10],
                "open": float(c.get("open") or 0),
                "high": float(c.get("high") or 0),
                "low": float(c.get("low") or 0),
                "close": float(c.get("close") or 0),
                "volume": float(c.get("volume") or 0)
            } for c in candles]
            await save_job(job_id, {"status": "running", "progress": 30, "message": "Menjalankan 34 engines..."})
            result = await backtest_single(req.ticker, formatted, req.mode, req.min_score)
            result["status"] = "completed"
            result["progress"] = 100
            result["config"] = req.dict()
            await save_job(job_id, result)
        except Exception as e:
            await save_job(job_id, {"status": "failed", "message": str(e)})

    background_tasks.add_task(single_job, job_id, req)
    return {"job_id": job_id, "message": f"Backtest {req.ticker} dimulai", "status_url": f"/api/backtest/status/{job_id}"}

@router.get("/test-date/{ticker}")
async def test_date_range(ticker: str):
    import httpx, os
    base = os.environ.get("INVESGO_BASE_URL", "https://api.invezgo.com")
    key = os.environ["INVESGO_API_KEY"]
    headers = {"Authorization": f"Bearer {key}"}
    results = {}
    tests = [
        {"from": "2010-01-01", "to": "2026-01-01"},
        {"from": "2020-01-01", "to": "2026-01-01"},
        {"period": "10y"},
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        for params in tests:
            try:
                r = await client.get(f"{base}/analysis/chart/stock/{ticker}", headers=headers, params=params)
                data = r.json()
                count = len(data) if isinstance(data, list) else "not list"
                first = data[0].get("date","?")[:10] if isinstance(data, list) and data else "?"
                results[str(params)] = f"{count} candles, first={first}"
            except Exception as e:
                results[str(params)] = f"ERROR: {str(e)[:50]}"
    return results

@router.get("/market-test")
async def test_market():
    from app.core import invesgo
    results = {}
    try:
        results["market_summary"] = await invesgo.get_market_summary()
    except Exception as e:
        results["market_summary"] = str(e)[:100]
    try:
        results["sector_rotation"] = await invesgo.get_sector_rotation()
    except Exception as e:
        results["sector_rotation"] = str(e)[:100]
    try:
        composite = await invesgo.get_chart_composite()
        results["composite_candles"] = len(composite) if isinstance(composite, list) else composite
    except Exception as e:
        results["composite_candles"] = str(e)[:100]
    try:
        results["foreign_net"] = await invesgo.get_foreign_net()
    except Exception as e:
        results["foreign_net"] = str(e)[:100]
    return results

@router.get("/top-test")
async def test_top():
    import httpx, os
    base = os.environ.get("INVESGO_BASE_URL", "https://api.invezgo.com")
    key = os.environ["INVESGO_API_KEY"]
    headers = {"Authorization": f"Bearer {key}"}
    results = {}
    tests = [
        ("top-change", {}),
        ("top-change", {"sort": "gainer"}),
        ("top-change", {"type": "gainer"}),
        ("top-change", {"filter": "gainer"}),
        ("market/top-gainer", {}),
        ("top-gainer", {}),
        ("top-change/gainer", {}),
    ]
    async with httpx.AsyncClient(timeout=10) as client:
        for ep, params in tests:
            try:
                r = await client.get(f"{base}/analysis/{ep}", headers=headers, params=params)
                data = r.json()
                if r.status_code == 200:
                    count = len(data) if isinstance(data, list) else "dict"
                    results[f"{ep}?{params}"] = f"✅ {count}"
                else:
                    results[f"{ep}?{params}"] = f"❌ {r.status_code}"
            except Exception as e:
                results[f"{ep}?{params}"] = f"❌ {str(e)[:40]}"
    return results

@router.get("/index-test")
async def test_all_indices():
    import httpx, os
    base = os.environ.get("INVESGO_BASE_URL", "https://api.invezgo.com")
    key = os.environ["INVESGO_API_KEY"]
    headers = {"Authorization": f"Bearer {key}"}
    results = {}

    indices = [
        "IHSG","LQ45","IDX30","IDXSMC","IDXBUMN",
        "IDXVESTA","IDXG30","IDXHIDIV","IDXESGL",
        "IDXBASIC","IDXCYC","IDXNONCYC","IDXENERGY",
        "IDXFINANCE","IDXHEALTH","IDXINDUST","IDXINFRA",
        "IDXPROPERT","IDXTECHNO","IDXTRANS"
    ]

    async with httpx.AsyncClient(timeout=15) as client:
        for idx in indices:
            try:
                r = await client.get(f"{base}/analysis/intraday-index/{idx}", headers=headers)
                if r.status_code == 200:
                    d = r.json()
                    results[idx] = f"✅ close={d.get('close')} chg={d.get('change_pct','?')}"
                else:
                    results[idx] = f"❌ {r.status_code}"
            except Exception as e:
                results[idx] = f"❌ {str(e)[:30]}"
    return results
