import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "money_maker_flow.sqlite3"
DB_PATH = Path(os.environ.get("MONEY_MAKER_FLOW_DB", str(DEFAULT_DB_PATH)))
STORE_BACKEND = os.environ.get("MONEY_MAKER_STORE_BACKEND", "auto").lower()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS money_maker_flow_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            mode TEXT NOT NULL,
            session_key TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            bfd_score INTEGER NOT NULL,
            money_maker_score REAL NOT NULL,
            phase TEXT,
            verdict TEXT,
            top_buyers_json TEXT NOT NULL DEFAULT '[]',
            top_sellers_json TEXT NOT NULL DEFAULT '[]',
            patterns_json TEXT NOT NULL DEFAULT '[]',
            risk_flags_json TEXT NOT NULL DEFAULT '[]',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            components_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(ticker, mode, session_key)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mm_flow_ticker_mode_id ON money_maker_flow_snapshots(ticker, mode, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mm_flow_created_at ON money_maker_flow_snapshots(created_at)")
    conn.commit()


def _json(value: Any, default: Any) -> str:
    try:
        return json.dumps(value if value is not None else default, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return json.dumps(default, separators=(",", ":"), ensure_ascii=False)


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _loads_any(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return default
    return _loads(str(value), default)


def _normalize_snapshot(row: Any, *, source: str, saved: bool = False) -> Dict[str, Any]:
    return {
        "ticker": row["ticker"],
        "mode": row["mode"],
        "session_key": row["session_key"],
        "created_at": row["created_at"],
        "bfd_score": row["bfd_score"],
        "money_maker_score": row["money_maker_score"],
        "phase": row["phase"],
        "verdict": row["verdict"],
        "top_buyers": _loads_any(row["top_buyers_json"], []),
        "top_sellers": _loads_any(row["top_sellers_json"], []),
        "patterns": _loads_any(row["patterns_json"], []),
        "risk_flags": _loads_any(row["risk_flags_json"], []),
        "metrics": _loads_any(row["metrics_json"], {}),
        "components": _loads_any(row["components_json"], {}),
        "persistent": True,
        "persistent_backend": source,
        "saved": saved,
    }


def get_latest_flow_snapshot(ticker: str, mode: str) -> Dict[str, Any]:
    ticker = str(ticker or "").upper()
    mode = str(mode or "swing").lower()
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM money_maker_flow_snapshots
                WHERE ticker = ? AND mode = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (ticker, mode),
            ).fetchone()
        if not row:
            return {}
        return _normalize_snapshot(row, source="sqlite")
    except Exception:
        return {}


def save_flow_snapshot(ticker: str, mode: str, snapshot: Dict[str, Any], retention: int = 500) -> Dict[str, Any]:
    ticker = str(ticker or "").upper()
    mode = str(mode or "swing").lower()
    session_key = str(snapshot.get("session_key") or snapshot.get("date") or snapshot.get("created_at") or "latest")
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO money_maker_flow_snapshots (
                    ticker, mode, session_key, bfd_score, money_maker_score, phase, verdict,
                    top_buyers_json, top_sellers_json, patterns_json, risk_flags_json, metrics_json, components_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, mode, session_key) DO UPDATE SET
                    created_at = datetime('now'),
                    bfd_score = excluded.bfd_score,
                    money_maker_score = excluded.money_maker_score,
                    phase = excluded.phase,
                    verdict = excluded.verdict,
                    top_buyers_json = excluded.top_buyers_json,
                    top_sellers_json = excluded.top_sellers_json,
                    patterns_json = excluded.patterns_json,
                    risk_flags_json = excluded.risk_flags_json,
                    metrics_json = excluded.metrics_json,
                    components_json = excluded.components_json
                """,
                (
                    ticker,
                    mode,
                    session_key,
                    int(snapshot.get("bfd_score") or 0),
                    float(snapshot.get("money_maker_score") or snapshot.get("score") or 0),
                    snapshot.get("phase"),
                    snapshot.get("verdict"),
                    _json(snapshot.get("top_buyers"), []),
                    _json(snapshot.get("top_sellers"), []),
                    _json(snapshot.get("patterns"), []),
                    _json(snapshot.get("risk_flags"), []),
                    _json(snapshot.get("metrics"), {}),
                    _json(snapshot.get("components"), {}),
                ),
            )
            conn.execute(
                """
                DELETE FROM money_maker_flow_snapshots
                WHERE id NOT IN (
                    SELECT id FROM money_maker_flow_snapshots
                    WHERE ticker = ? AND mode = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) AND ticker = ? AND mode = ?
                """,
                (ticker, mode, int(retention), ticker, mode),
            )
            conn.commit()
        latest = get_latest_flow_snapshot(ticker, mode)
        latest["saved"] = True
        latest["db_path"] = str(DB_PATH)
        latest["persistent_backend"] = "sqlite"
        return latest
    except Exception as exc:
        return {"saved": False, "error": str(exc), "db_path": str(DB_PATH)}


def get_flow_history(ticker: str, mode: str, limit: int = 20) -> List[Dict[str, Any]]:
    ticker = str(ticker or "").upper()
    mode = str(mode or "swing").lower()
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM money_maker_flow_snapshots
                WHERE ticker = ? AND mode = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (ticker, mode, int(limit)),
            ).fetchall()
        history = []
        for row in rows:
            history.append({
                "created_at": row["created_at"],
                "session_key": row["session_key"],
                "bfd_score": row["bfd_score"],
                "money_maker_score": row["money_maker_score"],
                "phase": row["phase"],
                "verdict": row["verdict"],
                "patterns": _loads(row["patterns_json"], []),
                "risk_flags": _loads(row["risk_flags_json"], []),
            })
        return history
    except Exception:
        return []


def _postgres_enabled() -> bool:
    if STORE_BACKEND in ("sqlite", "local"):
        return False
    return bool(os.environ.get("DATABASE_URL"))


async def _ensure_postgres_schema() -> None:
    from sqlalchemy import text
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS money_maker_flow_snapshots (
                id BIGSERIAL PRIMARY KEY,
                ticker TEXT NOT NULL,
                mode TEXT NOT NULL,
                session_key TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                bfd_score INTEGER NOT NULL,
                money_maker_score DOUBLE PRECISION NOT NULL,
                phase TEXT,
                verdict TEXT,
                top_buyers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                top_sellers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                patterns_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                risk_flags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                components_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                UNIQUE(ticker, mode, session_key)
            )
        """))
        await db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_mm_flow_ticker_mode_id
            ON money_maker_flow_snapshots(ticker, mode, id DESC)
        """))
        await db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_mm_flow_created_at
            ON money_maker_flow_snapshots(created_at)
        """))
        await db.commit()


async def get_latest_flow_snapshot_cloud(ticker: str, mode: str) -> Dict[str, Any]:
    if not _postgres_enabled():
        return get_latest_flow_snapshot(ticker, mode)
    ticker = str(ticker or "").upper()
    mode = str(mode or "swing").lower()
    try:
        from sqlalchemy import text
        from app.core.database import AsyncSessionLocal

        await _ensure_postgres_schema()
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT * FROM money_maker_flow_snapshots
                    WHERE ticker = :ticker AND mode = :mode
                    ORDER BY id DESC
                    LIMIT 1
                """),
                {"ticker": ticker, "mode": mode},
            )
            row = result.mappings().first()
        if not row:
            return {}
        return _normalize_snapshot(row, source="postgresql")
    except Exception:
        return get_latest_flow_snapshot(ticker, mode)


async def save_flow_snapshot_cloud(ticker: str, mode: str, snapshot: Dict[str, Any], retention: int = 500) -> Dict[str, Any]:
    if not _postgres_enabled():
        return save_flow_snapshot(ticker, mode, snapshot, retention=retention)
    ticker = str(ticker or "").upper()
    mode = str(mode or "swing").lower()
    session_key = str(snapshot.get("session_key") or snapshot.get("date") or snapshot.get("created_at") or "latest")
    try:
        from sqlalchemy import text
        from app.core.database import AsyncSessionLocal

        await _ensure_postgres_schema()
        params = {
            "ticker": ticker,
            "mode": mode,
            "session_key": session_key,
            "bfd_score": int(snapshot.get("bfd_score") or 0),
            "money_maker_score": float(snapshot.get("money_maker_score") or snapshot.get("score") or 0),
            "phase": snapshot.get("phase"),
            "verdict": snapshot.get("verdict"),
            "top_buyers_json": _json(snapshot.get("top_buyers"), []),
            "top_sellers_json": _json(snapshot.get("top_sellers"), []),
            "patterns_json": _json(snapshot.get("patterns"), []),
            "risk_flags_json": _json(snapshot.get("risk_flags"), []),
            "metrics_json": _json(snapshot.get("metrics"), {}),
            "components_json": _json(snapshot.get("components"), {}),
            "retention": int(retention),
        }
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO money_maker_flow_snapshots (
                        ticker, mode, session_key, bfd_score, money_maker_score, phase, verdict,
                        top_buyers_json, top_sellers_json, patterns_json, risk_flags_json, metrics_json, components_json
                    )
                    VALUES (
                        :ticker, :mode, :session_key, :bfd_score, :money_maker_score, :phase, :verdict,
                        CAST(:top_buyers_json AS JSONB), CAST(:top_sellers_json AS JSONB),
                        CAST(:patterns_json AS JSONB), CAST(:risk_flags_json AS JSONB),
                        CAST(:metrics_json AS JSONB), CAST(:components_json AS JSONB)
                    )
                    ON CONFLICT(ticker, mode, session_key) DO UPDATE SET
                        created_at = NOW(),
                        bfd_score = excluded.bfd_score,
                        money_maker_score = excluded.money_maker_score,
                        phase = excluded.phase,
                        verdict = excluded.verdict,
                        top_buyers_json = excluded.top_buyers_json,
                        top_sellers_json = excluded.top_sellers_json,
                        patterns_json = excluded.patterns_json,
                        risk_flags_json = excluded.risk_flags_json,
                        metrics_json = excluded.metrics_json,
                        components_json = excluded.components_json
                """),
                params,
            )
            await db.execute(
                text("""
                    DELETE FROM money_maker_flow_snapshots
                    WHERE ticker = :ticker
                      AND mode = :mode
                      AND id NOT IN (
                        SELECT id FROM money_maker_flow_snapshots
                        WHERE ticker = :ticker AND mode = :mode
                        ORDER BY id DESC
                        LIMIT :retention
                      )
                """),
                params,
            )
            await db.commit()
        latest = await get_latest_flow_snapshot_cloud(ticker, mode)
        latest["saved"] = True
        latest["persistent_backend"] = "postgresql"
        return latest
    except Exception as exc:
        fallback = save_flow_snapshot(ticker, mode, snapshot, retention=retention)
        fallback["cloud_saved"] = False
        fallback["cloud_error"] = str(exc)
        return fallback


def snapshot_from_money_maker(money_maker: Dict[str, Any]) -> Dict[str, Any]:
    mm = money_maker or {}
    broker = mm.get("broker") or {}
    top_buyers = [x.get("code") for x in broker.get("net_buyers", [])[:5] if isinstance(x, dict) and x.get("code")]
    top_sellers = [x.get("code") for x in broker.get("net_sellers", [])[:5] if isinstance(x, dict) and x.get("code")]
    return {
        "session_key": f"{str(mm.get('ticker') or '').upper()}:{str(mm.get('mode') or 'swing').lower()}:latest",
        "bfd_score": mm.get("bfd_score"),
        "money_maker_score": mm.get("score"),
        "phase": mm.get("phase"),
        "verdict": mm.get("verdict"),
        "top_buyers": top_buyers,
        "top_sellers": top_sellers,
        "patterns": [x.get("name") for x in mm.get("patterns", [])[:8] if isinstance(x, dict) and x.get("name")],
        "risk_flags": mm.get("risk_flags", []),
        "metrics": mm.get("metrics", {}),
        "components": mm.get("components", {}),
    }


async def save_money_maker_cloud(money_maker: Dict[str, Any], retention: int = 500) -> Dict[str, Any]:
    mm = money_maker or {}
    if not mm.get("available"):
        return {"saved": False, "reason": "money_maker_unavailable"}
    snapshot = snapshot_from_money_maker(mm)
    return await save_flow_snapshot_cloud(mm.get("ticker"), mm.get("mode"), snapshot, retention=retention)
