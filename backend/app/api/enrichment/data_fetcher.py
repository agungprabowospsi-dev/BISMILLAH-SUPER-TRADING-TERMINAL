# enrichment/data_fetcher.py
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 60

class EnrichmentDataError(Exception):
    pass

async def get_enrichment_ohlcv(ticker: str, n: int = 100) -> List[Dict[str, Any]]:
    try:
        from data.invesgo_connector import get_ohlcv_daily
        raw = await get_ohlcv_daily(ticker, period="120d")
        if not raw:
            raise EnrichmentDataError(f"[{ticker}] OHLCV kosong")

        normalized = []
        for bar in raw:
            normalized.append({
                "date":   bar.get("date") or bar.get("t") or "",
                "open":   float(bar.get("open")   or bar.get("o") or 0),
                "high":   float(bar.get("high")   or bar.get("h") or 0),
                "low":    float(bar.get("low")    or bar.get("l") or 0),
                "close":  float(bar.get("close")  or bar.get("c") or 0),
                "volume": float(bar.get("volume") or bar.get("v") or 0),
            })

        normalized = [b for b in normalized if b["close"] > 0]
        result = normalized[-n:] if len(normalized) > n else normalized

        if len(result) < MIN_BARS_REQUIRED:
            raise EnrichmentDataError(
                f"[{ticker}] Data hanya {len(result)} bar, minimum {MIN_BARS_REQUIRED}"
            )

        logger.info(f"[{ticker}] OHLCV enrichment: {len(result)} bar")
        return result

    except EnrichmentDataError:
        raise
    except Exception as e:
        raise EnrichmentDataError(f"[{ticker}] Gagal ambil OHLCV: {e}") from e

def extract_series(ohlcv, field):
    return [b[field] for b in ohlcv]

def extract_tr(ohlcv):
    tr_list = []
    for i in range(len(ohlcv)):
        hl = ohlcv[i]["high"] - ohlcv[i]["low"]
        if i == 0:
            tr_list.append(hl)
        else:
            hpc = abs(ohlcv[i]["high"] - ohlcv[i-1]["close"])
            lpc = abs(ohlcv[i]["low"]  - ohlcv[i-1]["close"])
            tr_list.append(max(hl, hpc, lpc))
    return tr_list
