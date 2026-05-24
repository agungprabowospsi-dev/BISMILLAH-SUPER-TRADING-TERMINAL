import logging
import re
from typing import Dict, List

from app.knowledge_base.kb_service import ensure_tables_exist

logger = logging.getLogger(__name__)


ACTIVE_KB_LITERATURE = [
    "Bandarmologi IDX Vol.1",
    "Bandarmologi IDX Vol.2",
    "E-Book Bandar Flow Secrets",
    "Fibonacci Trading - Carolyn Boroden",
    "A Complete Guide To Volume Price Analysis - Anna Coulling",
    "Encyclopedia of Chart Patterns - Thomas Bulkowski",
    "Technical Analysis of the Financial Markets - John Murphy",
    "Trade Setup Handbook",
    "ORDER FLOW Trading Setups - Trader Dale",
    "Stock Trading & Investing Using Volume Price Analysis - Anna Coulling",
    "Advances in Financial Machine Learning - Marcos Lopez de Prado",
    "Trading and Exchanges / Market Microstructure - Larry Harris",
]

BANDARMOLOGI_BOOKS = [
    "file_1766768812634",
    "file_1766768868107",
    "E-Book Bandar Flow Secrets",
]

BOOK_PATTERNS: Dict[str, List[str]] = {
    "bandarmologi": [
        "file_1766768812634",
        "file_1766768868107",
        "Bandar Flow Secrets",
    ],
    "bulkowski": [
        "Encyclopedia of Chart Patterns",
        "Bulkowski",
    ],
    "boroden": [
        "Fibonacci Trading",
        "Boroden",
    ],
    "coulling_vpa": [
        "Volume Price Analysis",
        "Anna Coulling",
        "Stock Trading & Investing Using Volume Price Analysis",
    ],
    "harris": [
        "Trading and Exchanges",
        "Harris",
        "Market Microstructure",
    ],
    "dale": [
        "ORDER FLOW",
        "Trader Dale",
    ],
    "murphy": [
        "Technical Analysis of the Financial Markets",
        "Murphy",
    ],
    "setup": [
        "Trade Setup Handbook",
    ],
    "lopezdeprado": [
        "Advances in Financial Machine Learning",
        "Lopez",
        "Lopez de Prado",
        "LÃ³pez de Prado",
    ],
}

COLLECTION_TO_ENGINE = {
    "price_action": "PriceActionEngine",
    "fibonacci": "FibonacciEngine",
    "boroden": "FibonacciEngine",
    "carolyn_boroden": "FibonacciEngine",
    "bulkowski": "AIPatternRecognitionEngine",
    "candlestick_patterns": "AIPatternRecognitionEngine",
    "volume": "VolumeIntelligenceEngine",
    "relative_volume": "RelativeVolumeEngine",
    "trend": "TrendStructureEngine",
    "support_resistance": "SupportResistanceEngine",
    "orderbook": "OrderbookEngine",
    "broker_behavior": "BrokerBehaviorEngine",
    "bandarmologi": "BandarmologyEngine",
    "technical": "PriceActionEngine",
    "risk": "RiskManagementEngine",
    "ml": "ProbabilityEngine",
}

COLLECTION_TO_BOOK = {
    "anna_couling": "coulling_vpa",
    "anna_coulling": "coulling_vpa",
    "carolyn_boroden": "boroden",
    "candlestick_patterns": "bulkowski",
}

ENGINE_BOOK_MAP = {
    "PriceActionEngine": ["murphy", "bulkowski", "coulling_vpa"],
    "TrendStructureEngine": ["murphy", "bulkowski"],
    "SupportResistanceEngine": ["murphy", "boroden"],
    "VolumeIntelligenceEngine": ["coulling_vpa", "harris"],
    "RelativeVolumeEngine": ["coulling_vpa"],
    "MultiTimeframeEngine": ["murphy", "setup"],
    "OrderBlockEngine": ["harris", "dale", "setup"],
    "BreakOrderEngine": ["harris", "dale", "setup"],
    "FairValueGapEngine": ["harris", "dale"],
    "LiquidityEngine": ["harris", "dale", "coulling_vpa"],
    "BandarmologyEngine": ["bandarmologi", "coulling_vpa", "harris"],
    "InventoryEngine": ["harris", "coulling_vpa", "bandarmologi"],
    "FlowMappingEngine": ["harris", "dale", "coulling_vpa"],
    "IntradayPositioningEngine": ["dale", "harris", "coulling_vpa"],
    "BrokerBehaviorEngine": ["harris", "coulling_vpa", "dale", "bandarmologi"],
    "ForeignFlowEngine": ["harris", "coulling_vpa", "bandarmologi"],
    "QuantEdgeEngine": ["lopezdeprado", "setup"],
    "OrderbookEngine": ["dale", "harris"],
    "RelativeStrengthEngine": ["murphy", "lopezdeprado"],
    "FibonacciEngine": ["boroden", "murphy"],
    "AIPatternRecognitionEngine": ["bulkowski", "murphy", "coulling_vpa"],
    "SectorRotationEngine": ["murphy", "harris"],
    "MacroMarketEngine": ["murphy", "harris"],
    "MacroEconomicsEngine": ["harris", "lopezdeprado"],
    "GeopoliticsEngine": ["harris"],
    "NewsSentimentEngine": ["harris", "lopezdeprado"],
    "InsiderOwnershipEngine": ["harris"],
    "ProbabilityEngine": ["lopezdeprado", "bulkowski"],
    "TradingSetupEngine": ["setup", "murphy", "bulkowski"],
    "RiskManagementEngine": ["setup", "lopezdeprado"],
    "FinalScorecardEngine": ["setup", "lopezdeprado", "murphy"],
    "AIConfidenceEngine": ["lopezdeprado", "setup"],
    "SmartRotationEngine": ["murphy", "harris"],
    "RealtimeAlertEngine": ["setup", "coulling_vpa"],
    "LiquidityQualityEngine": ["harris", "dale", "coulling_vpa"],
    # Monitoring enhancement aliases.
    "BandarTypeClassifier": ["harris", "coulling_vpa", "bandarmologi"],
    "BandarmologiMonitor": ["bandarmologi", "coulling_vpa"],
    "MomentumStrength": ["coulling_vpa", "murphy"],
    "RetestClassifier": ["bandarmologi", "bulkowski", "boroden"],
    "TPProbability": ["boroden", "bulkowski", "lopezdeprado"],
    "RAGMonitor": ["bandarmologi", "harris", "murphy", "setup"],
    "AnalyticSetup": ["setup", "murphy", "coulling_vpa", "lopezdeprado"],
    "ScreenerBandarmologi": ["bandarmologi", "coulling_vpa", "harris"],
    "ScalpingOrderflow": ["dale", "harris", "coulling_vpa"],
    "MLProbability": ["lopezdeprado"],
}


async def init_knowledge_base():
    try:
        await ensure_tables_exist()
        logger.info("Knowledge Base ready - dynamic mode")
    except Exception as e:
        logger.error(f"Knowledge Base init error: {e}")
        logger.warning("KB tetap berjalan; tabel dibuat saat upload pertama")


def _query_terms(query: str) -> List[str]:
    stop = {"saham", "stock", "idx", "yang", "dan", "atau", "the", "for", "with", "engine"}
    return [
        t.lower() for t in re.findall(r"[A-Za-z0-9_]{3,}", query or "")
        if t.lower() not in stop
    ][:16]


def _rank_rows(rows: List[dict], query: str, limit: int) -> List[dict]:
    terms = _query_terms(query)

    def score(row: dict) -> tuple:
        text = (row.get("content") or "").lower()
        source = (row.get("source") or row.get("source_document") or "").lower()
        relevance = sum(3 if term in source else 1 for term in terms if term in text or term in source)
        early_page_bonus = max(0, 3 - int(row.get("page_number") or 0) // 100)
        return (relevance, early_page_bonus, -int(row.get("chunk_index") or 0))

    ranked = sorted(rows, key=score, reverse=True)
    selected = []
    seen_sources = set()
    for row in ranked:
        src = row.get("source") or row.get("source_document") or ""
        if src in seen_sources and len(selected) < min(limit, 4):
            continue
        selected.append(row)
        seen_sources.add(src)
        if len(selected) >= limit:
            break
    return selected


async def query_knowledge_base(collection_key: str, query: str = "", n_results: int = 3, top_k: int = None) -> str:
    """Compatibility router for old collection names and direct engine names."""
    from app.knowledge_base.kb_service import search_chunks_for_engine

    if top_k is not None:
        n_results = top_k
    if not query:
        query = collection_key
        collection_key = "technical"

    book_key = COLLECTION_TO_BOOK.get(collection_key)
    if book_key:
        book_text = await _query_book(book_key, query, n_results)
        if book_text:
            return book_text

    engine_name = COLLECTION_TO_ENGINE.get(collection_key, collection_key)
    try:
        chunks = await search_chunks_for_engine(engine_name, query, n_results)
        if chunks:
            return "\n\n".join(c["content"][:500] for c in chunks)
        return await query_kb_for_engine(engine_name, query)
    except Exception as e:
        logger.error(f"KB query error: {e}")
        return ""


async def _query_book(book_key: str, query: str, n_results: int = 3) -> str:
    try:
        from app.knowledge_base.kb_service import get_db_conn

        patterns = BOOK_PATTERNS.get(book_key, [])
        if not patterns:
            return ""

        conn = await get_db_conn()
        try:
            conditions = " OR ".join(
                f"d.original_name ILIKE ${i + 1}" for i in range(len(patterns))
            )
            rows = await conn.fetch(f"""
                SELECT c.content, c.page_number, c.chunk_index, d.original_name as source
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE ({conditions})
                  AND d.status = 'analyzed'
                LIMIT ${len(patterns) + 1}
            """, *[f"%{p}%" for p in patterns], max(n_results * 12, 30))
        finally:
            await conn.close()

        ranked = _rank_rows([dict(r) for r in rows], query, n_results)
        return "\n\n---\n\n".join(
            f"[{book_key.upper()} p.{r['page_number']}]\n{r['content'][:500]}"
            for r in ranked
        )
    except Exception as e:
        logger.error(f"Book query error [{book_key}]: {e}")
        return ""


async def query_bandarmologi_kb(query: str, n_results: int = 4) -> str:
    text = await _query_book("bandarmologi", query, n_results)
    if not text:
        return ""
    return text.replace("[BANDARMOLOGI", "[BANDARMOLOGI IDX")


async def query_bandarmologi_specific(ticker: str, bandar_score: float, phase: str, signal: str) -> str:
    query = (
        f"Saham IDX {ticker} dengan bandar score {bandar_score:.0f}, "
        f"fase {phase}, signal {signal}. Apakah bandar sedang akumulasi "
        f"atau distribusi dan apa konfirmasi lanjutannya?"
    )
    return await query_bandarmologi_kb(query, n_results=3)


async def query_bulkowski(query: str, n: int = 2) -> str:
    return await _query_book("bulkowski", query, n)


async def query_boroden(query: str, n: int = 2) -> str:
    return await _query_book("boroden", query, n)


async def query_coulling_vpa(query: str, n: int = 3) -> str:
    return await _query_book("coulling_vpa", query, n)


async def query_harris_microstructure(query: str, n: int = 2) -> str:
    return await _query_book("harris", query, n)


async def query_trader_dale(query: str, n: int = 2) -> str:
    return await _query_book("dale", query, n)


async def query_murphy_ta(query: str, n: int = 2) -> str:
    return await _query_book("murphy", query, n)


async def query_trade_setup(query: str, n: int = 2) -> str:
    return await _query_book("setup", query, n)


async def query_lopezdeprado(query: str, n: int = 2) -> str:
    return await _query_book("lopezdeprado", query, n)


async def query_all_technical(query: str, n_per_book: int = 1) -> str:
    import asyncio

    books = ["bulkowski", "boroden", "coulling_vpa", "harris", "dale", "murphy", "setup", "lopezdeprado"]

    async def safe_query(book):
        try:
            return await _query_book(book, query, n_per_book)
        except Exception:
            return ""

    parts = [r for r in await asyncio.gather(*[safe_query(b) for b in books]) if r]
    return "\n\n===\n\n".join(parts[:8])


async def query_kb_for_engine(engine_name: str, context: str) -> str:
    import asyncio

    books = ENGINE_BOOK_MAP.get(engine_name, ["murphy", "setup"])

    async def safe_q(book):
        try:
            return await _query_book(book, context, 2)
        except Exception:
            return ""

    parts = [r for r in await asyncio.gather(*[safe_q(b) for b in books]) if r]
    return "\n\n---\n\n".join(parts)
