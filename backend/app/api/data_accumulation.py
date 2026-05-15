"""
Data Accumulation — Cron Job Harian
Simpan candle OHLCV harian ke PostgreSQL untuk training data ML
"""
from fastapi import APIRouter
from datetime import datetime, timedelta
import asyncio, logging
from app.core import invesgo
from app.core.database import get_db

router = APIRouter(prefix="/api/data", tags=["data_accumulation"])
logger = logging.getLogger(__name__)

# LQ45 + saham penting untuk diakumulasi
WATCHLIST = [
    "BBCA","BBRI","BMRI","TLKM","ASII","BYAN","GOTO","UNVR",
    "ICBP","INDF","ANTM","PTBA","ADRO","ESSA","SMGR","PGAS",
    "EXCL","KLBF","MAPI","SIDO","MDKA","AMMN","EMTK","BUKA",
    "ACES","MNCN","SCMA","LSIP","AALI","HRUM"
]

@router.post("/accumulate")
async def accumulate_daily():
    """Jalankan akumulasi data harian — panggil via cron atau manual"""
    results = {"success": [], "failed": [], "total": len(WATCHLIST)}
    today = datetime.now().strftime("%Y-%m-%d")

    async def save_one(ticker):
        try:
            ohlcv = await asyncio.wait_for(
                invesgo.get_ohlcv_daily(ticker, period="5d"), timeout=15
            )
            if not ohlcv:
                results["failed"].append({"ticker": ticker, "reason": "no data"})
                return

            last = ohlcv[-1]
            db = await get_db()
            await db.execute("""
                INSERT INTO ohlcv_daily 
                (ticker, date, open, high, low, close, volume, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                open=EXCLUDED.open, high=EXCLUDED.high,
                low=EXCLUDED.low, close=EXCLUDED.close,
                volume=EXCLUDED.volume
            """,
                ticker,
                last.get("date", today),
                float(last.get("open", 0) or 0),
                float(last.get("high", 0) or 0),
                float(last.get("low", 0) or 0),
                float(last.get("close", 0) or 0),
                float(last.get("volume", 0) or 0),
            )
            results["success"].append(ticker)
        except Exception as e:
            results["failed"].append({"ticker": ticker, "reason": str(e)[:50]})

    # Batch 10 saham parallel
    for i in range(0, len(WATCHLIST), 10):
        batch = WATCHLIST[i:i+10]
        await asyncio.gather(*[save_one(t) for t in batch])
        await asyncio.sleep(1)

    return {
        "status": "ok",
        "date": today,
        "success": len(results["success"]),
        "failed": len(results["failed"]),
        "details": results
    }

@router.get("/status")
async def data_status():
    """Cek status data yang sudah terakumulasi"""
    try:
        db = await get_db()
        rows = await db.fetch("""
            SELECT ticker, COUNT(*) as days, MIN(date) as from_date, MAX(date) as to_date
            FROM ohlcv_daily
            GROUP BY ticker
            ORDER BY days DESC
            LIMIT 20
        """)
        return {
            "status": "ok",
            "tickers": [dict(r) for r in rows],
            "total_tickers": len(rows)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

@router.post("/create-table")
async def create_table():
    """Buat tabel ohlcv_daily kalau belum ada"""
    try:
        db = await get_db()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv_daily (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                date DATE NOT NULL,
                open FLOAT,
                high FLOAT,
                low FLOAT,
                close FLOAT,
                volume BIGINT,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(ticker, date)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv_daily(ticker, date)")
        return {"status": "ok", "message": "Table ohlcv_daily ready"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
