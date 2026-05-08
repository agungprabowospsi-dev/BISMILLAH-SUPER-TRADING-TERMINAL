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
