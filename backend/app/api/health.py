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
@router.get("/debug/data-module")
async def debug_data_module():
    import subprocess
    result = subprocess.run(
        ["cat", "/app/data/invesgo_connector.py"],
        capture_output=True, text=True
    )
    return {"content": result.stdout, "error": result.stderr}

@router.get("/debug/invesgo-count")
async def debug_invesgo_count():
    from app.core import invesgo
    stocks = await invesgo.get_stock_list()
    total = len(stocks)
    sample = [s.get("code","") for s in stocks[:10]]
    return {"total": total, "sample_10": sample}

@router.get("/debug/invesgo-detail")
async def debug_invesgo_detail():
    from app.core import invesgo
    stocks = await invesgo.get_stock_list()
    total = len(stocks)
    clean = [s.get("code","") for s in stocks if "-" not in s.get("code","") and len(s.get("code","")) <= 6]
    warrant = [s.get("code","") for s in stocks if "-" in s.get("code","")]
    return {
        "total_all": total,
        "total_clean": len(clean),
        "total_warrant": len(warrant),
        "sample_clean": clean[:10],
        "sample_warrant": warrant[:5]
    }
