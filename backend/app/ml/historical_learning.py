import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core import invesgo

logger = logging.getLogger(__name__)

MODE_RULES = {
    "scalping": {"horizon": 1, "tp_pct": 1.5, "sl_pct": 1.0},
    "intraday": {"horizon": 3, "tp_pct": 3.0, "sl_pct": 2.0},
    "daytrading": {"horizon": 3, "tp_pct": 3.0, "sl_pct": 2.0},
    "swing": {"horizon": 20, "tp_pct": 8.0, "sl_pct": 5.0},
}


async def ensure_historical_tables() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
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
        """))
        await db.execute(text("ALTER TABLE ohlcv_daily ADD COLUMN IF NOT EXISTS value FLOAT"))
        await db.execute(text("ALTER TABLE ohlcv_daily ADD COLUMN IF NOT EXISTS freq FLOAT"))
        await db.execute(text("ALTER TABLE ohlcv_daily ADD COLUMN IF NOT EXISTS source VARCHAR(40) DEFAULT 'invesgo'"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv_daily(ticker, date)"))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS historical_features (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                date DATE NOT NULL,
                mode VARCHAR(20) NOT NULL DEFAULT 'swing',
                pattern_key VARCHAR(160) NOT NULL,
                feature_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(ticker, date, mode)
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS historical_outcomes (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                date DATE NOT NULL,
                mode VARCHAR(20) NOT NULL DEFAULT 'swing',
                horizon_days INTEGER NOT NULL,
                tp_pct FLOAT NOT NULL,
                sl_pct FLOAT NOT NULL,
                outcome VARCHAR(20) NOT NULL,
                bars_to_exit INTEGER,
                max_favorable_pct FLOAT,
                max_drawdown_pct FLOAT,
                exit_reason VARCHAR(20),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(ticker, date, mode, horizon_days)
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS empirical_patterns (
                id SERIAL PRIMARY KEY,
                mode VARCHAR(20) NOT NULL,
                pattern_key VARCHAR(160) NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 0,
                win_count INTEGER NOT NULL DEFAULT 0,
                loss_count INTEGER NOT NULL DEFAULT 0,
                timeout_count INTEGER NOT NULL DEFAULT 0,
                winrate FLOAT NOT NULL DEFAULT 0.0,
                avg_mfe_pct FLOAT NOT NULL DEFAULT 0.0,
                avg_drawdown_pct FLOAT NOT NULL DEFAULT 0.0,
                expectancy_pct FLOAT NOT NULL DEFAULT 0.0,
                confidence FLOAT NOT NULL DEFAULT 0.0,
                literature TEXT,
                source VARCHAR(50) NOT NULL DEFAULT 'idx_empirical_memory',
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(mode, pattern_key)
            )
        """))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_historical_features_ticker_date ON historical_features(ticker, date)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_historical_features_mode_pattern ON historical_features(mode, pattern_key)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_historical_outcomes_ticker_date ON historical_outcomes(ticker, date)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_empirical_patterns_mode_winrate ON empirical_patterns(mode, winrate)"))
        await db.commit()


def _num(row: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            try:
                return float(row.get(key) or 0)
            except Exception:
                continue
    return default


def _candle_date(row: Dict[str, Any]) -> Optional[str]:
    raw = row.get("date") or row.get("time") or row.get("datetime") or row.get("timestamp")
    if not raw:
        return None
    return str(raw)[:10]


def normalize_candle(row: Dict[str, Any], fallback_date: str = "") -> Optional[Dict[str, Any]]:
    d = _candle_date(row) or fallback_date
    close = _num(row, "close", "c")
    if not d or close <= 0:
        return None
    return {
        "date": d,
        "open": _num(row, "open", "o", default=close),
        "high": _num(row, "high", "h", default=close),
        "low": _num(row, "low", "l", default=close),
        "close": close,
        "volume": int(_num(row, "volume", "v")),
        "value": _num(row, "value", "value_idr"),
        "freq": _num(row, "freq", "frequency"),
    }


async def save_ohlcv(ticker: str, candles: List[Dict[str, Any]]) -> int:
    rows = [normalize_candle(c) for c in candles if isinstance(c, dict)]
    rows = [r for r in rows if r]
    if not rows:
        return 0
    async with AsyncSessionLocal() as db:
        for r in rows:
            await db.execute(text("""
                INSERT INTO ohlcv_daily
                    (ticker, date, open, high, low, close, volume, value, freq, source, created_at)
                VALUES
                    (:ticker, :date, :open, :high, :low, :close, :volume, :value, :freq, 'invesgo', NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                    open=EXCLUDED.open,
                    high=EXCLUDED.high,
                    low=EXCLUDED.low,
                    close=EXCLUDED.close,
                    volume=EXCLUDED.volume,
                    value=EXCLUDED.value,
                    freq=EXCLUDED.freq,
                    source='invesgo'
            """), {"ticker": ticker, **r})
        await db.commit()
    return len(rows)


async def load_ohlcv(ticker: str, years: int = 15) -> List[Dict[str, Any]]:
    from_date = (datetime.now() - timedelta(days=years * 366)).strftime("%Y-%m-%d")
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT date, open, high, low, close, volume, value, freq
            FROM ohlcv_daily
            WHERE ticker = :ticker AND date >= :from_date
            ORDER BY date ASC
        """), {"ticker": ticker, "from_date": from_date})
        rows = result.fetchall()
    return [
        {
            "date": str(r[0]),
            "open": float(r[1] or 0),
            "high": float(r[2] or 0),
            "low": float(r[3] or 0),
            "close": float(r[4] or 0),
            "volume": float(r[5] or 0),
            "value": float(r[6] or 0),
            "freq": float(r[7] or 0),
        }
        for r in rows
    ]


async def sync_ticker_history(ticker: str, years: int = 15, force: bool = False) -> Dict[str, Any]:
    await ensure_historical_tables()
    existing = await load_ohlcv(ticker, years=years)
    if existing and not force:
        oldest = existing[0]["date"]
        newest = existing[-1]["date"]
        if len(existing) >= years * 180:
            return {
                "ticker": ticker,
                "status": "cached",
                "rows": len(existing),
                "from_date": oldest,
                "to_date": newest,
            }

    raw = await invesgo.get_ohlcv_daily(ticker, period=f"{years}y")
    saved = await save_ohlcv(ticker, raw if isinstance(raw, list) else [])
    data = await load_ohlcv(ticker, years=years)
    return {
        "ticker": ticker,
        "status": "synced",
        "saved": saved,
        "rows": len(data),
        "from_date": data[0]["date"] if data else None,
        "to_date": data[-1]["date"] if data else None,
    }


def derive_features(candles: List[Dict[str, Any]], idx: int) -> Dict[str, Any]:
    window = candles[max(0, idx - 60):idx + 1]
    current = candles[idx]
    closes = [float(c["close"]) for c in window if c.get("close")]
    vols = [float(c.get("volume") or 0) for c in window]
    if len(closes) < 20:
        raise ValueError("not enough candles")

    close = closes[-1]
    sma20 = mean(closes[-20:])
    sma50 = mean(closes[-50:]) if len(closes) >= 50 else sma20
    ret5 = (close / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else 0
    ret20 = (close / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else 0
    avg_vol20 = mean(vols[-20:]) if len(vols) >= 20 else 0
    rvol = (vols[-1] / avg_vol20) if avg_vol20 else 1
    high20 = max(c["high"] for c in window[-20:])
    low20 = min(c["low"] for c in window[-20:])
    range_pos = (close - low20) / max(high20 - low20, 1e-9)

    trend_state = "uptrend" if close > sma20 > sma50 else "downtrend" if close < sma20 < sma50 else "sideways"
    momentum_state = "strong" if ret20 >= 8 else "weak" if ret20 <= -8 else "neutral"
    volume_state = "surge" if rvol >= 2 else "dry" if rvol < 0.7 else "normal"
    location_state = "near_high" if range_pos >= 0.75 else "near_low" if range_pos <= 0.25 else "midrange"
    pattern_key = f"{trend_state}|{momentum_state}|{volume_state}|{location_state}"

    return {
        "date": current["date"],
        "close": close,
        "sma20": sma20,
        "sma50": sma50,
        "ret5_pct": ret5,
        "ret20_pct": ret20,
        "rvol": rvol,
        "range_pos_20": range_pos,
        "trend_state": trend_state,
        "momentum_state": momentum_state,
        "volume_state": volume_state,
        "location_state": location_state,
        "pattern_key": pattern_key,
    }


def label_outcome(candles: List[Dict[str, Any]], idx: int, mode: str) -> Optional[Dict[str, Any]]:
    rule = MODE_RULES.get(mode, MODE_RULES["swing"])
    entry = float(candles[idx]["close"])
    if entry <= 0:
        return None
    tp_price = entry * (1 + rule["tp_pct"] / 100)
    sl_price = entry * (1 - rule["sl_pct"] / 100)
    horizon = int(rule["horizon"])
    future = candles[idx + 1: idx + 1 + horizon]
    if not future:
        return None

    max_fav = 0.0
    max_dd = 0.0
    for offset, c in enumerate(future, start=1):
        high = float(c["high"])
        low = float(c["low"])
        max_fav = max(max_fav, (high / entry - 1) * 100)
        max_dd = min(max_dd, (low / entry - 1) * 100)
        hit_sl = low <= sl_price
        hit_tp = high >= tp_price
        if hit_sl and hit_tp:
            outcome = "LOSE" if abs((entry - sl_price) / entry) <= abs((tp_price - entry) / entry) else "WIN"
            return {**rule, "outcome": outcome, "bars_to_exit": offset, "exit_reason": "SAME_BAR", "max_favorable_pct": max_fav, "max_drawdown_pct": max_dd}
        if hit_sl:
            return {**rule, "outcome": "LOSE", "bars_to_exit": offset, "exit_reason": "SL", "max_favorable_pct": max_fav, "max_drawdown_pct": max_dd}
        if hit_tp:
            return {**rule, "outcome": "WIN", "bars_to_exit": offset, "exit_reason": "TP", "max_favorable_pct": max_fav, "max_drawdown_pct": max_dd}

    exit_close = float(future[-1]["close"])
    pnl = (exit_close / entry - 1) * 100
    if pnl >= rule["tp_pct"] * 0.35:
        outcome = "WIN"
    elif pnl <= -rule["sl_pct"] * 0.35:
        outcome = "LOSE"
    else:
        outcome = "TIMEOUT"
    return {**rule, "outcome": outcome, "bars_to_exit": horizon, "exit_reason": "TIME", "max_favorable_pct": max_fav, "max_drawdown_pct": max_dd}


async def build_ticker_memory(ticker: str, mode: str = "swing", years: int = 15) -> Dict[str, Any]:
    await ensure_historical_tables()
    candles = await load_ohlcv(ticker, years=years)
    if len(candles) < 90:
        return {"ticker": ticker, "mode": mode, "status": "insufficient_data", "rows": len(candles)}

    feature_rows = []
    outcome_rows = []
    for idx in range(60, len(candles) - MODE_RULES.get(mode, MODE_RULES["swing"])["horizon"]):
        try:
            features = derive_features(candles, idx)
            outcome = label_outcome(candles, idx, mode)
            if outcome:
                feature_rows.append((ticker, features["date"], mode, features["pattern_key"], features))
                outcome_rows.append((ticker, features["date"], mode, outcome))
        except Exception:
            continue

    async with AsyncSessionLocal() as db:
        for t, d, m, pattern_key, features in feature_rows:
            await db.execute(text("""
                INSERT INTO historical_features (ticker, date, mode, pattern_key, feature_json, created_at)
                VALUES (:ticker, :date, :mode, :pattern_key, CAST(:feature_json AS JSONB), NOW())
                ON CONFLICT (ticker, date, mode) DO UPDATE SET
                    pattern_key=EXCLUDED.pattern_key,
                    feature_json=EXCLUDED.feature_json
            """), {
                "ticker": t,
                "date": d,
                "mode": m,
                "pattern_key": pattern_key,
                "feature_json": json.dumps(features),
            })
        for t, d, m, out in outcome_rows:
            await db.execute(text("""
                INSERT INTO historical_outcomes
                    (ticker, date, mode, horizon_days, tp_pct, sl_pct, outcome, bars_to_exit,
                     max_favorable_pct, max_drawdown_pct, exit_reason, created_at)
                VALUES
                    (:ticker, :date, :mode, :horizon, :tp_pct, :sl_pct, :outcome, :bars_to_exit,
                     :max_favorable_pct, :max_drawdown_pct, :exit_reason, NOW())
                ON CONFLICT (ticker, date, mode, horizon_days) DO UPDATE SET
                    outcome=EXCLUDED.outcome,
                    bars_to_exit=EXCLUDED.bars_to_exit,
                    max_favorable_pct=EXCLUDED.max_favorable_pct,
                    max_drawdown_pct=EXCLUDED.max_drawdown_pct,
                    exit_reason=EXCLUDED.exit_reason
            """), {
                "ticker": t,
                "date": d,
                "mode": m,
                "horizon": int(out["horizon"]),
                "tp_pct": float(out["tp_pct"]),
                "sl_pct": float(out["sl_pct"]),
                "outcome": out["outcome"],
                "bars_to_exit": int(out["bars_to_exit"]),
                "max_favorable_pct": float(out["max_favorable_pct"]),
                "max_drawdown_pct": float(out["max_drawdown_pct"]),
                "exit_reason": out["exit_reason"],
            })
        await db.commit()

    mined = await mine_empirical_patterns(mode)
    return {
        "ticker": ticker,
        "mode": mode,
        "status": "learned",
        "rows": len(candles),
        "features": len(feature_rows),
        "outcomes": len(outcome_rows),
        "patterns_updated": mined.get("patterns_updated", 0),
    }


async def mine_empirical_patterns(mode: str = "swing", min_samples: int = 30) -> Dict[str, Any]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT
                f.pattern_key,
                COUNT(*) AS sample_count,
                SUM(CASE WHEN o.outcome = 'WIN' THEN 1 ELSE 0 END) AS win_count,
                SUM(CASE WHEN o.outcome = 'LOSE' THEN 1 ELSE 0 END) AS loss_count,
                SUM(CASE WHEN o.outcome = 'TIMEOUT' THEN 1 ELSE 0 END) AS timeout_count,
                AVG(o.max_favorable_pct) AS avg_mfe_pct,
                AVG(o.max_drawdown_pct) AS avg_drawdown_pct
            FROM historical_features f
            JOIN historical_outcomes o
              ON o.ticker = f.ticker AND o.date = f.date AND o.mode = f.mode
            WHERE f.mode = :mode
            GROUP BY f.pattern_key
            HAVING COUNT(*) >= :min_samples
        """), {"mode": mode, "min_samples": min_samples})
        rows = result.fetchall()

        updated = 0
        for r in rows:
            pattern_key = r[0]
            sample_count = int(r[1] or 0)
            win_count = int(r[2] or 0)
            loss_count = int(r[3] or 0)
            timeout_count = int(r[4] or 0)
            decided = max(win_count + loss_count, 1)
            winrate = win_count / decided * 100
            avg_mfe = float(r[5] or 0)
            avg_dd = float(r[6] or 0)
            expectancy = (winrate / 100 * avg_mfe) + ((1 - winrate / 100) * avg_dd)
            confidence = min(95.0, 35 + min(sample_count, 300) / 300 * 35 + max(0, winrate - 50) * 0.5)
            literature = (
                f"Empirical IDX memory ({mode}): pattern {pattern_key} muncul {sample_count} kali. "
                f"Winrate {winrate:.1f}% dari {decided} decided outcomes, "
                f"avg MFE {avg_mfe:.2f}%, avg drawdown {avg_dd:.2f}%, expectancy {expectancy:.2f}%."
            )
            await db.execute(text("""
                INSERT INTO empirical_patterns
                    (mode, pattern_key, sample_count, win_count, loss_count, timeout_count,
                     winrate, avg_mfe_pct, avg_drawdown_pct, expectancy_pct, confidence, literature, source, updated_at)
                VALUES
                    (:mode, :pattern_key, :sample_count, :win_count, :loss_count, :timeout_count,
                     :winrate, :avg_mfe_pct, :avg_drawdown_pct, :expectancy_pct, :confidence,
                     :literature, 'idx_empirical_memory', NOW())
                ON CONFLICT (mode, pattern_key) DO UPDATE SET
                    sample_count=EXCLUDED.sample_count,
                    win_count=EXCLUDED.win_count,
                    loss_count=EXCLUDED.loss_count,
                    timeout_count=EXCLUDED.timeout_count,
                    winrate=EXCLUDED.winrate,
                    avg_mfe_pct=EXCLUDED.avg_mfe_pct,
                    avg_drawdown_pct=EXCLUDED.avg_drawdown_pct,
                    expectancy_pct=EXCLUDED.expectancy_pct,
                    confidence=EXCLUDED.confidence,
                    literature=EXCLUDED.literature,
                    updated_at=NOW()
            """), {
                "mode": mode,
                "pattern_key": pattern_key,
                "sample_count": sample_count,
                "win_count": win_count,
                "loss_count": loss_count,
                "timeout_count": timeout_count,
                "winrate": round(winrate, 2),
                "avg_mfe_pct": round(avg_mfe, 4),
                "avg_drawdown_pct": round(avg_dd, 4),
                "expectancy_pct": round(expectancy, 4),
                "confidence": round(confidence, 2),
                "literature": literature,
            })
            updated += 1
        await db.commit()
    return {"mode": mode, "patterns_updated": updated}


async def get_empirical_context(ticker: str, mode: str = "swing", candles: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    try:
        source_candles = candles or await load_ohlcv(ticker, years=1)
        if len(source_candles) < 60:
            return {"available": False, "reason": "insufficient_recent_data"}
        features = derive_features(source_candles, len(source_candles) - 1)
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT pattern_key, sample_count, winrate, expectancy_pct, confidence, literature
                FROM empirical_patterns
                WHERE mode = :mode AND pattern_key = :pattern_key
                LIMIT 1
            """), {"mode": mode, "pattern_key": features["pattern_key"]})
            row = result.fetchone()
        if not row:
            return {"available": False, "pattern_key": features["pattern_key"], "features": features}
        return {
            "available": True,
            "pattern_key": row[0],
            "sample_count": int(row[1] or 0),
            "winrate": float(row[2] or 0),
            "expectancy_pct": float(row[3] or 0),
            "confidence": float(row[4] or 0),
            "literature": row[5],
            "features": features,
        }
    except Exception as exc:
        logger.warning(f"Empirical context failed [{ticker}]: {exc}")
        return {"available": False, "reason": str(exc)}


async def query_empirical_literature(query: str, mode: str = "swing", limit: int = 3) -> str:
    """Return mined IDX empirical patterns as compact KB-like literature."""
    terms = [
        t.lower() for t in (query or "").replace("|", " ").replace("_", " ").split()
        if len(t) >= 3
    ][:12]
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT pattern_key, sample_count, winrate, expectancy_pct, confidence, literature
                FROM empirical_patterns
                WHERE mode = :mode
                ORDER BY confidence DESC, sample_count DESC, winrate DESC
                LIMIT 80
            """), {"mode": mode})
            rows = [dict(r._mapping) for r in result.fetchall()]
    except Exception as exc:
        logger.debug(f"Empirical literature unavailable: {exc}")
        return ""

    if not rows:
        return ""

    def rank(row: Dict[str, Any]) -> tuple:
        haystack = f"{row.get('pattern_key', '')} {row.get('literature', '')}".lower()
        lexical = sum(1 for term in terms if term in haystack)
        return (
            lexical,
            float(row.get("confidence") or 0),
            int(row.get("sample_count") or 0),
            float(row.get("winrate") or 0),
        )

    rows.sort(key=rank, reverse=True)
    parts = []
    for row in rows[:limit]:
        parts.append(
            "[IDX_EMPIRICAL_MEMORY]\n"
            f"Pattern: {row.get('pattern_key')}\n"
            f"Sample: {int(row.get('sample_count') or 0)} | "
            f"Winrate: {float(row.get('winrate') or 0):.1f}% | "
            f"Expectancy: {float(row.get('expectancy_pct') or 0):.2f}% | "
            f"Confidence: {float(row.get('confidence') or 0):.1f}\n"
            f"{row.get('literature') or ''}"
        )
    return "\n\n---\n\n".join(parts)


async def get_learning_status(limit: int = 25) -> Dict[str, Any]:
    await ensure_historical_tables()
    async with AsyncSessionLocal() as db:
        ohlcv = await db.execute(text("""
            SELECT ticker, COUNT(*) AS rows, MIN(date), MAX(date)
            FROM ohlcv_daily
            GROUP BY ticker
            ORDER BY rows DESC
            LIMIT :limit
        """), {"limit": limit})
        patterns = await db.execute(text("""
            SELECT mode, COUNT(*) AS patterns, AVG(winrate) AS avg_winrate
            FROM empirical_patterns
            GROUP BY mode
            ORDER BY mode
        """))
    return {
        "ohlcv": [
            {"ticker": r[0], "rows": int(r[1] or 0), "from_date": str(r[2]), "to_date": str(r[3])}
            for r in ohlcv.fetchall()
        ],
        "patterns": [
            {"mode": r[0], "patterns": int(r[1] or 0), "avg_winrate": round(float(r[2] or 0), 2)}
            for r in patterns.fetchall()
        ],
    }


async def sync_many(tickers: List[str], years: int = 15, force: bool = False, concurrency: int = 3) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(ticker: str):
        async with sem:
            try:
                return await sync_ticker_history(ticker.upper(), years=years, force=force)
            except Exception as exc:
                return {"ticker": ticker.upper(), "status": "error", "error": str(exc)[:160]}

    return await asyncio.gather(*[one(t) for t in tickers])


async def get_stock_universe(limit: int = 50) -> List[str]:
    """Pick a liquid-ish universe from cached Invesgo stock list."""
    rows = await invesgo.get_stock_list()
    candidates = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        code = row.get("code") or row.get("ticker") or row.get("symbol") or row.get("stock_code")
        if not code or "-" in str(code) or len(str(code)) > 6:
            continue
        liquidity = _num(row, "value", "value_idr") + (_num(row, "freq", "frequency") * 1_000_000)
        candidates.append((str(code).upper(), liquidity))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [code for code, _ in candidates[:max(1, limit)]]
