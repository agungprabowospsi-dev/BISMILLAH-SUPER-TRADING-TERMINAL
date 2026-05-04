# app/api/health.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
async def health():
    from app.core.knowledge_base import _collections
    from app.core.redis_client import _redis_client
    kb_loaded = all(c.count() > 0 for c in _collections.values()) if _collections else False
    redis_ok = False
    try:
        await _redis_client.ping()
        redis_ok = True
    except:
        pass
    return {
        "status": "ok",
        "engines": 10,
        "kb_loaded": kb_loaded,
        "redis": redis_ok,
        "message": "BISMILLAH — Systems Online 🚀"
    }
