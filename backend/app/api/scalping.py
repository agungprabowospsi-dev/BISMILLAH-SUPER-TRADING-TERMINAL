from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
from app.core import invesgo
from app.core.claude_client import ask_claude
import logging
import numpy as np

logger = logging.getLogger(__name__)
router = APIRouter()

async def analyze_scalping_signal(ticker: str, intraday: dict, ohlcv: list) -> dict:
    """Analisa signal scalping dari data real Invesgo"""
    try:
        bid_price = float(intraday.get("bid_price", 0) or 0)
        offer_price = float(intraday.get("offer_price", 0) or 0)
        bid_lot = float(intraday.get("bid_lot", 0) or 0)
        offer_lot = float(intraday.get("offer_lot", 0) or 0)
        bid_freq = float(intraday.get("bid_freq", 0) or 0)
        offer_freq = float(intraday.get("offer_freq", 0) or 0)
        current = float(intraday.get("close", 0) or intraday.get("last_price", 0) or 0)
        volume = float(intraday.get("volume", 0) or 0)
        avg_price = float(intraday.get("avg", 0) or current)
        high = float(intraday.get("high", 0) or current)
        low = float(intraday.get("low", 0) or current)
        prev = float(intraday.get("prev", 0) or current)

        # Spread analysis
        spread = offer_price - bid_price if bid_price and offer_price else 0
        spread_pct = (spread / bid_price * 100) if bid_price else 0

        # Bid/Ask imbalance
        bid_ask_ratio = bid_lot / offer_lot if offer_lot > 0 else 1
        freq_ratio = bid_freq / offer_freq if offer_freq > 0 else 1

        # Volume analysis dari OHLCV
        volumes = [float(c["volume"] or 0) for c in ohlcv[-20:]] if ohlcv else [volume]
        avg_vol = float(np.mean(volumes)) if volumes else volume
        rvol = volume / avg_vol if avg_vol > 0 else 1

        # Change from prev
        change = current - prev
        change_pct = (change / prev * 100) if prev > 0 else 0

        # Signal logic
        signal = "HOLD"
        level = "NEUTRAL"
        reason = ""

        # Strong buy signal
        if bid_ask_ratio > 3 and freq_ratio > 2 and change_pct > 0.3:
            signal = "ENTRY"
            level = "GOOD"
            reason = f"Bid wall kuat ({bid_ask_ratio:.1f}x), frekuensi beli dominan, momentum positif"
        # Buy signal
        elif bid_ask_ratio > 1.5 and change_pct >= 0:
            signal = "ENTRY"
            level = "GOOD"
            reason = f"Bid dominan ({bid_ask_ratio:.1f}x), tekanan beli terdeteksi"
        # Strong sell signal
        elif bid_ask_ratio < 0.3 and change_pct < -0.3:
            signal = "EXIT"
            level = "BAD"
            reason = f"Ask wall dominan ({bid_ask_ratio:.1f}x), tekanan jual kuat"
        # Sell signal
        elif bid_ask_ratio < 0.7 and change_pct < 0:
            signal = "EXIT"
            level = "BAD"
            reason = f"Offer lebih besar dari bid, momentum negatif"
        # Volume spike
        elif rvol >= 2 and change_pct > 0:
            signal = "ENTRY"
            level = "GOOD"
            reason = f"Volume spike {rvol:.1f}x rata-rata dengan harga naik"
        else:
            signal = "HOLD"
            level = "NEUTRAL"
            reason = "Belum ada sinyal kuat, tunggu konfirmasi"

        # Scalping quality assessment
        is_good_for_scalping = (
            spread_pct < 1.0 and  # Spread tidak terlalu lebar
            rvol >= 0.5 and  # Volume cukup
            bid_lot > 0 and offer_lot > 0  # Ada data orderbook
        )

        return {
            "ticker": ticker,
            "price": current,
            "prev": prev,
            "change": round(change, 0),
            "change_pct": round(change_pct, 2),
            "high": high,
            "low": low,
            "avg": avg_price,
            "volume": volume,
            "rvol": round(rvol, 2),
            "bid": bid_price,
            "ask": offer_price,
            "bid_lot": bid_lot,
            "offer_lot": offer_lot,
            "bid_freq": bid_freq,
            "offer_freq": offer_freq,
            "spread": spread,
            "spread_pct": round(spread_pct, 3),
            "bid_ask_ratio": round(bid_ask_ratio, 2),
            "freq_ratio": round(freq_ratio, 2),
            "signal": signal,
            "level": level,
            "reason": reason,
            "is_good_for_scalping": is_good_for_scalping,
            "scalping_quality": "BAGUS ✅" if is_good_for_scalping else "TIDAK BAGUS ❌",
            "volume_alert": f"Volume spike {rvol:.1f}x rata-rata!" if rvol >= 2 else None,
            "orderbook": {
                "bids": [[bid_price, bid_lot]],
                "asks": [[offer_price, offer_lot]],
            }
        }
    except Exception as e:
        logger.error(f"Scalping analyze error: {e}")
        return {"error": str(e), "signal": "HOLD", "level": "NEUTRAL"}


@router.websocket("/scalping/{ticker}")
async def scalping_ws(websocket: WebSocket, ticker: str):
    await websocket.accept()
    logger.info(f"Scalping WS connected: {ticker}")
    ohlcv_cache = []

    try:
        # Load OHLCV sekali
        try:
            ohlcv_cache = await invesgo.get_ohlcv_daily(ticker)
        except Exception as e:
            logger.warning(f"OHLCV load failed: {e}")

        while True:
            try:
                intraday = await invesgo.get_ohlcv_intraday(ticker, market="RG")
                result = await analyze_scalping_signal(ticker, intraday, ohlcv_cache)
                await websocket.send_json(result)
            except Exception as e:
                await websocket.send_json({"error": str(e), "signal": "HOLD", "level": "NEUTRAL"})

            await asyncio.sleep(5)

    except WebSocketDisconnect:
        logger.info(f"Scalping WS disconnected: {ticker}")


@router.get("/scalping/snapshot/{ticker}")
async def scalping_snapshot(ticker: str):
    """REST endpoint untuk scalping data (fallback dari WS)"""
    try:
        intraday = await invesgo.get_ohlcv_intraday(ticker, market="RG")
        ohlcv = await invesgo.get_ohlcv_daily(ticker)
        result = await analyze_scalping_signal(ticker, intraday, ohlcv)

        # AI analysis
        ai_analysis = await ask_claude(
            system="You are a scalping expert for IDX stocks. Give ultra-concise 2-sentence scalping signal.",
            prompt=f"""
Ticker: {ticker}
Price: {result.get('price')} | Change: {result.get('change_pct')}%
Bid/Ask Ratio: {result.get('bid_ask_ratio')}x | Spread: {result.get('spread_pct')}%
Volume: {result.get('rvol')}x average | Signal: {result.get('signal')}
Reason: {result.get('reason')}

2-sentence scalping analysis: entry price recommendation and exit target.
""",
            max_tokens=100
        )
        result["ai_analysis"] = ai_analysis
        return result
    except Exception as e:
        return {"error": str(e)}
