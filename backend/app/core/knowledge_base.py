import logging
from app.knowledge_base.kb_service import ensure_tables_exist

logger = logging.getLogger(__name__)


async def init_knowledge_base():
    try:
        await ensure_tables_exist()
        logger.info("✅ Knowledge Base ready — dynamic mode (unlimited books)")
    except Exception as e:
        logger.error(f"⚠️ Knowledge Base init error: {e}")
        logger.warning("KB akan tetap berjalan — tabel dibuat saat pertama upload")


async def query_knowledge_base(collection_key: str, query: str, n_results: int = 3) -> str:
    from app.knowledge_base.kb_service import search_chunks_for_engine
    collection_to_engine = {
        "price_action": "PriceActionEngine",
        "fibonacci": "FibonacciEngine",
        "candlestick_patterns": "AIPatternRecognitionEngine",
    }
    engine_name = collection_to_engine.get(collection_key, collection_key)
    try:
        chunks = await search_chunks_for_engine(engine_name, query, n_results)
        if not chunks:
            return ""
        return "\n\n".join(c["content"][:500] for c in chunks)
    except Exception as e:
        logger.error(f"KB query error: {e}")
        return ""


# ─────────────────────────────────────────────
# BANDARMOLOGI IDX — Query khusus 3 buku
# ─────────────────────────────────────────────

BANDARMOLOGI_BOOKS = [
    "file_1766768812634",
    "file_1766768868107",
    "E-Book Bandar Flow Secrets",
]

async def query_bandarmologi_kb(query: str, n_results: int = 4) -> str:
    """
    Query khusus 3 buku bandarmologi IDX.
    Dipakai untuk:
    - Analytic GO/NO GO bandar context
    - Engine 6 Retest bandar context
    - RAG Monitor distribution detection
    """
    try:
        from app.knowledge_base.kb_service import get_db_conn
        conn = await get_db_conn()
        try:
            rows = await conn.fetch("""
                SELECT c.content, c.page_number,
                       d.original_name as source
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE (
                    d.original_name LIKE '%file_1766768812634%'
                    OR d.original_name LIKE '%file_1766768868107%'
                    OR d.original_name LIKE '%Bandar Flow Secrets%'
                )
                AND d.status = 'analyzed'
                ORDER BY RANDOM()
                LIMIT $1
            """, n_results)

            if not rows:
                return ""

            parts = []
            for r in rows:
                src = r["source"]
                # Friendly name
                if "file_1766768812634" in src:
                    book = "Bandarmologi IDX Vol.1"
                elif "file_1766768868107" in src:
                    book = "Bandarmologi IDX Vol.2"
                else:
                    book = "Bandar Flow Secrets"
                parts.append(f"[{book} p.{r['page_number']}]\n{r['content'][:600]}")

            return "\n\n---\n\n".join(parts)

        finally:
            await conn.close()

    except Exception as e:
        logger.error(f"Bandarmologi KB query error: {e}")
        return ""


async def query_bandarmologi_specific(
    ticker:       str,
    bandar_score: float,
    phase:        str,
    signal:       str,
) -> str:
    """
    Query bandarmologi KB dengan konteks spesifik saham IDX.
    Dipakai di Analytic untuk GO/NO GO bandar assessment.
    """
    query = (
        f"Saham IDX dengan bandar score {bandar_score:.0f}, "
        f"fase {phase}, signal {signal}. "
        f"Apakah bandar sedang akumulasi atau distribusi? "
        f"Bagaimana ciri-ciri bandar IDX di kondisi ini?"
    )
    return await query_bandarmologi_kb(query, n_results=3)


# ─────────────────────────────────────────────
# QUERY SPESIFIK PER BUKU
# ─────────────────────────────────────────────

BOOK_PATTERNS = {
    "bulkowski":    ["Encyclopedia of Chart Patterns", "Bulkowski"],
    "boroden":      ["Fibonacci Trading", "Boroden"],
    "coulling_vpa": ["Volume Price Analysis", "Anna Coulling"],
    "harris":       ["Trading and Exchanges", "Harris", "Market Microstructure"],
    "dale":         ["ORDER FLOW", "Trader Dale"],
    "murphy":       ["Technical Analysis of the Financial Markets", "Murphy"],
    "setup":        ["Trade Setup Handbook"],
    "lopezdeprado": ["Advances in Financial Machine Learning", "Lopez de Prado"],
}


async def _query_book(book_key: str, query: str, n_results: int = 3) -> str:
    """Query buku spesifik berdasarkan nama pattern"""
    try:
        from app.knowledge_base.kb_service import get_db_conn
        patterns = BOOK_PATTERNS.get(book_key, [])
        if not patterns:
            return ""

        conn = await get_db_conn()
        try:
            # Build WHERE clause untuk match nama buku
            where_parts = " OR ".join([
                f"d.original_name ILIKE '%{p}%'" for p in patterns
            ])
            rows = await conn.fetch(f"""
                SELECT c.content, c.page_number,
                       d.original_name as source
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE ({where_parts})
                AND d.status = 'analyzed'
                ORDER BY RANDOM()
                LIMIT $1
            """, n_results)

            if not rows:
                return ""

            parts = []
            for r in rows:
                parts.append(
                    f"[{book_key.upper()} p.{r['page_number']}]\n{r['content'][:500]}"
                )
            return "\n\n---\n\n".join(parts)

        finally:
            await conn.close()

    except Exception as e:
        logger.error(f"Book query error [{book_key}]: {e}")
        return ""


# ── Query functions per use case ──────────────────────────

async def query_bulkowski(query: str, n: int = 2) -> str:
    """
    Encyclopedia of Chart Patterns — Bulkowski
    Untuk: Engine 6 chart pattern, pullback statistics,
           measured move target, win rate per pattern
    """
    return await _query_book("bulkowski", query, n)


async def query_boroden(query: str, n: int = 2) -> str:
    """
    Fibonacci Trading — Boroden
    Untuk: Engine 6 Fibonacci level confirmation,
           price cluster, time target
    """
    return await _query_book("boroden", query, n)


async def query_coulling_vpa(query: str, n: int = 3) -> str:
    """
    VPA Anna Coulling (2 buku)
    Untuk: Engine 5 momentum VSA confirmation,
           effort vs result, stopping volume,
           no demand analysis
    """
    return await _query_book("coulling_vpa", query, n)


async def query_harris_microstructure(query: str, n: int = 2) -> str:
    """
    Trading and Exchanges — Larry Harris
    Untuk: Engine 3 bandar type microstructure,
           market maker behavior, lot size analysis,
           price impact interpretation
    """
    return await _query_book("harris", query, n)


async def query_trader_dale(query: str, n: int = 2) -> str:
    """
    ORDER FLOW Trading Setups — Trader Dale
    Untuk: Scalping orderbook analysis,
           bid/ask imbalance, order flow setup,
           entry precision
    """
    return await _query_book("dale", query, n)


async def query_murphy_ta(query: str, n: int = 2) -> str:
    """
    Technical Analysis — John Murphy
    Untuk: Screener setup type confirmation,
           trend analysis, support/resistance,
           general TA reference
    """
    return await _query_book("murphy", query, n)


async def query_trade_setup(query: str, n: int = 2) -> str:
    """
    Trade Setup Handbook
    Untuk: Analytic GO/NO GO setup criteria,
           entry rules, setup qualification
    """
    return await _query_book("setup", query, n)


async def query_lopezdeprado(query: str, n: int = 2) -> str:
    """
    Advances in Financial ML — Lopez de Prado
    Untuk: ML Engine probability calibration,
           feature importance, statistical edge
    """
    return await _query_book("lopezdeprado", query, n)


async def query_all_technical(query: str, n_per_book: int = 1) -> str:
    """
    Query semua 9 buku teknikal sekaligus.
    Dipakai untuk RAG Monitor Engine 9 yang butuh
    konteks dari semua buku.
    """
    import asyncio
    books = [
        "bulkowski", "boroden", "coulling_vpa",
        "harris", "dale", "murphy", "setup", "lopezdeprado"
    ]

    async def safe_query(book):
        try:
            return await _query_book(book, query, n_per_book)
        except Exception:
            return ""

    results = await asyncio.gather(*[safe_query(b) for b in books])
    parts = [r for r in results if r]
    return "\n\n===\n\n".join(parts[:6])  # max 6 buku per query


async def query_kb_for_engine(engine_name: str, context: str) -> str:
    """
    Router query KB berdasarkan nama engine.
    Memilih buku yang paling relevan per engine.
    """
    engine_book_map = {
        # Engine 3 — Bandar Type
        "BandarTypeClassifier":     ["harris", "coulling_vpa"],
        # Engine 4 — Bandarmologi Monitor
        "BandarmologiMonitor":      ["coulling_vpa"],
        # Engine 5 — Momentum
        "MomentumStrength":         ["coulling_vpa", "murphy"],
        # Engine 6 — Retest
        "RetestClassifier":         ["bulkowski", "boroden"],
        # Engine 7 — TP Probability
        "TPProbability":            ["boroden", "bulkowski"],
        # Engine 9 — RAG Monitor
        "RAGMonitor":               ["harris", "murphy", "setup"],
        # Analytic
        "AnalyticSetup":            ["setup", "murphy"],
        # Screener
        "ScreenerBandarmologi":     ["coulling_vpa", "harris"],
        # Scalping
        "ScalpingOrderflow":        ["dale"],
        # ML
        "MLProbability":            ["lopezdeprado"],
    }

    books = engine_book_map.get(engine_name, ["murphy"])
    import asyncio

    async def safe_q(book):
        try:
            return await _query_book(book, context, 2)
        except Exception:
            return ""

    results = await asyncio.gather(*[safe_q(b) for b in books])
    parts = [r for r in results if r]
    return "\n\n---\n\n".join(parts)
