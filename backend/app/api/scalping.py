from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
from app.core import invesgo
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/scalping/{ticker}")
async def scalping_ws(websocket: WebSocket, ticker: str):
    await websocket.accept()
    logger.info(f"Scalping WS connected: {ticker}")
    prev_price = None
    try:
        while True:
            try:
                tick = await invesgo.get_tick(ticker)
                current = tick.get("last_price", 0)
                volume  = tick.get("volume", 0)

                signal = "hold"
                level  = "neutral"

                if prev_price:
                    change_pct = (current - prev_price) / prev_price * 100
                    if change_pct > 0.5:
                        signal = "entry"
                        level  = "good"
                    elif change_pct < -0.5:
                        signal = "exit"
                        level  = "bad"

                await websocket.send_json({
                    "ticker": ticker,
                    "price": current,
                    "volume": volume,
                    "signal": signal,
                    "level": level,
                    "bid": tick.get("bid", current),
                    "ask": tick.get("ask", current),
                })
                prev_price = current
            except Exception as e:
                await websocket.send_json({"error": str(e)})

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info(f"Scalping WS disconnected: {ticker}")
