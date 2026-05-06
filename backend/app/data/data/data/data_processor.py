import logging
from app.data import invesgo_connector as invesgo

logger = logging.getLogger(__name__)

async def get_stock_list():
    try:
        stocks = await invesgo.get_stock_list()
        logger.info(f"Got {len(stocks)} stocks")
        return stocks
    except Exception as e:
        logger.error(f"Failed to get stock list: {e}")
        return []

async def pre_filter_stocks(stocks, mode="swing"):
    filtered = []
    for s in stocks:
        code = s.get("code", "")
        if "-" in code:
            continue
        filtered.append(code)
    logger.info(f"Pre-filter: {len(filtered)} / {len(stocks)} stocks passed")
    return filtered[:50]
