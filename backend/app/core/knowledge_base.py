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
