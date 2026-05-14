from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class BacktestRequest(BaseModel):
    ticker: str
    mode: str = "swing"
    period: str = "1y"

@router.post("/run")
async def run_backtest(req: BacktestRequest):
    try:
        import yfinance as yf
        import pandas as pd
        from app.engines.master_runner import run_all_engines
        from app.knowledge_base import kb_service

        # 1. Ambil data historis
        ticker_yf = f"{req.ticker.upper()}.JK"
        df = yf.download(ticker_yf, period=req.period, interval="1d", progress=False)
        
        if df.empty or len(df) < 30:
            return {"error": f"Data tidak cukup untuk {req.ticker}"}

        # 2. Convert ke format OHLCV
        candles = []
        for date, row in df.iterrows():
            candles.append({
                "date": str(date.date()),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"])
            })

        # 3. Rolling backtest - window 60 candles
        WINDOW = 60
        trades = []
        equity = 100.0
        equity_curve = [{"date": candles[WINDOW]["date"], "equity": equity}]
        
        i = WINDOW
        in_trade = False
        current_trade = None

        while i < len(candles):
            window = candles[max(0, i-WINDOW):i]
            current = candles[i]

            # Check exit jika ada trade aktif
            if in_trade and current_trade:
                price = current["close"]
                entry = current_trade["entry"]
                sl = current_trade["sl"]
                tp1 = current_trade["tp1"]

                hit_sl = price <= sl
                hit_tp = price >= tp1

                if hit_sl or hit_tp:
                    pnl_pct = ((price - entry) / entry) * 100
                    current_trade["exit_price"] = price
                    current_trade["exit_date"] = current["date"]
                    current_trade["pnl_pct"] = round(pnl_pct, 2)
                    current_trade["result"] = "WIN" if hit_tp else "LOSS"
                    equity *= (1 + pnl_pct/100)
                    trades.append(current_trade)
                    equity_curve.append({"date": current["date"], "equity": round(equity, 2)})
                    in_trade = False
                    current_trade = None

            # Generate signal jika tidak ada trade
            if not in_trade and i % 5 == 0:
                try:
                    eng = await run_all_engines(req.ticker, window, req.mode)
                    score = eng.get("composite_score", 0)
                    
                    # RAG boost
                    try:
                        rag = await kb_service.get_kb_context_for_engine("PriceActionEngine", req.ticker)
                        rag_boost = 5 if rag and len(rag) > 100 else 0
                    except:
                        rag_boost = 0

                    total_score = score + rag_boost

                    if total_score >= 65:
                        price = current["close"]
                        atr = _calc_atr_simple(window)
                        sl = round(price - 1.5 * atr)
                        tp1 = round(price + 2.0 * atr)
                        tp2 = round(price + 3.0 * atr)
                        
                        current_trade = {
                            "ticker": req.ticker,
                            "entry_date": current["date"],
                            "entry": price,
                            "sl": sl,
                            "tp1": tp1,
                            "tp2": tp2,
                            "score": round(total_score, 1),
                            "rag_boost": rag_boost
                        }
                        in_trade = True
                except Exception as e:
                    logger.warning(f"Engine error at candle {i}: {e}")

            i += 1

        # 4. Hitung statistik
        if not trades:
            return {"error": "Tidak ada trade yang dihasilkan", "candles": len(candles)}

        wins = [t for t in trades if t["result"] == "WIN"]
        losses = [t for t in trades if t["result"] == "LOSS"]
        winrate = len(wins) / len(trades) * 100
        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 999

        # Max drawdown
        peak = 100.0
        max_dd = 0
        eq = 100.0
        for t in trades:
            eq *= (1 + t["pnl_pct"]/100)
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

        return {
            "ticker": req.ticker,
            "mode": req.mode,
            "period": req.period,
            "total_candles": len(candles),
            "total_trades": len(trades),
            "winrate": round(winrate, 1),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_dd, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "final_equity": round(equity, 2),
            "equity_curve": equity_curve[-20:],
            "trades": trades[-10:]
        }

    except Exception as e:
        logger.error(f"Backtest error: {e}")
        return {"error": str(e)}

def _calc_atr_simple(candles: list, period: int = 14) -> float:
    if len(candles) < period:
        return candles[-1]["close"] * 0.02
    trs = []
    for i in range(1, min(period+1, len(candles))):
        c = candles[-i]
        p = candles[-i-1]
        tr = max(c["high"]-c["low"], abs(c["high"]-p["close"]), abs(c["low"]-p["close"]))
        trs.append(tr)
    return sum(trs) / len(trs)

@router.get("/test/{ticker}")
async def test_data(ticker: str):
    try:
        import yfinance as yf
        ticker_yf = f"{ticker.upper()}.JK"
        df = yf.download(ticker_yf, period="5y", interval="1d", progress=False)
        return {
            "ticker_yf": ticker_yf,
            "rows": len(df),
            "empty": df.empty,
            "first": str(df.index[0].date()) if not df.empty else None,
            "last": str(df.index[-1].date()) if not df.empty else None
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/test-date/{ticker}")
async def test_date_range(ticker: str):
    import httpx, os
    from datetime import datetime, timedelta
    base = os.environ.get("INVESGO_BASE_URL", "https://api.invezgo.com")
    key = os.environ["INVESGO_API_KEY"]
    headers = {"Authorization": f"Bearer {key}"}
    
    results = {}
    # Test berbagai parameter
    tests = [
        {"from": "2010-01-01", "to": "2026-01-01"},
        {"from": "2020-01-01", "to": "2026-01-01"},
        {"startDate": "2010-01-01", "endDate": "2026-01-01"},
        {"start": "2010-01-01", "end": "2026-01-01"},
        {"period": "10y"},
        {"period": "max"},
        {"limit": "5000"},
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
