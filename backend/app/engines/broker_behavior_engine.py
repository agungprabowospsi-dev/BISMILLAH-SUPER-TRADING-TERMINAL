"""
BrokerBehaviorEngine — Top buyer/seller behavior from broker_summary.

REV28 target: expose top 5 buyer + seller behavior for monitoring so
bandarmology signals are based on actual broker flow, not only OHLCV proxy.
"""
from typing import Any, Dict, List

from app.engines.base_engine import BaseEngine, EngineResult

FOREIGN_BROKERS = {"YP", "BK", "RX", "ZP", "AK", "CC", "DB", "MS", "CS", "ML", "DP", "KI", "OD", "LG"}
PREMIUM_LOCAL = {"GS", "MU", "NK", "LS", "EP", "FZ", "YU", "KK", "DH", "PC", "RO", "BW", "GA", "CP"}
RETAIL_BROKERS = {"IF", "PD", "HP", "KS", "FH", "IN", "RB", "ID"}


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _broker_type(code: str) -> str:
    if code in FOREIGN_BROKERS:
        return "foreign"
    if code in PREMIUM_LOCAL:
        return "premium_local"
    if code in RETAIL_BROKERS:
        return "retail"
    return "other"


def _normalize_broker(row: Dict[str, Any]) -> Dict[str, Any]:
    code = str(row.get("code") or row.get("broker_code") or row.get("broker") or "").upper()
    name = row.get("name") or row.get("broker_name") or code
    buy_value = _to_float(row.get("buy_value") or row.get("buy") or row.get("buy_val"))
    sell_value = _to_float(row.get("sell_value") or row.get("sell") or row.get("sell_val"))
    net_value = row.get("net_value")
    if net_value is None:
        net_value = buy_value - sell_value

    return {
        "code": code,
        "name": name,
        "type": _broker_type(code),
        "buy_value": buy_value,
        "sell_value": sell_value,
        "net_value": _to_float(net_value),
    }


def summarize_broker_behavior(broker_rows: List[Dict[str, Any]], top_n: int = 5) -> Dict[str, Any]:
    if not broker_rows:
        return {
            "score": 50.0,
            "signal": "neutral",
            "pressure": "neutral",
            "reason": "no broker_summary data",
            "top_buyers": [],
            "top_sellers": [],
        }

    brokers = [_normalize_broker(row) for row in broker_rows if isinstance(row, dict)]
    brokers = [b for b in brokers if b["buy_value"] or b["sell_value"] or b["net_value"]]
    if not brokers:
        return {
            "score": 50.0,
            "signal": "neutral",
            "pressure": "neutral",
            "reason": "zero broker values",
            "top_buyers": [],
            "top_sellers": [],
        }

    total_buy = sum(b["buy_value"] for b in brokers)
    total_sell = sum(b["sell_value"] for b in brokers)
    total_value = total_buy + total_sell
    total_net = sum(b["net_value"] for b in brokers)

    top_buyers = sorted(brokers, key=lambda b: b["buy_value"], reverse=True)[:top_n]
    top_sellers = sorted(brokers, key=lambda b: b["sell_value"], reverse=True)[:top_n]
    net_buyers = sorted(brokers, key=lambda b: b["net_value"], reverse=True)[:top_n]
    net_sellers = sorted(brokers, key=lambda b: b["net_value"])[:top_n]

    top_buy_value = sum(b["buy_value"] for b in top_buyers)
    top_sell_value = sum(b["sell_value"] for b in top_sellers)
    top_buy_share = top_buy_value / total_buy if total_buy else 0.0
    top_sell_share = top_sell_value / total_sell if total_sell else 0.0

    smart_net = sum(
        b["net_value"]
        for b in brokers
        if b["type"] in ("foreign", "premium_local")
    )
    retail_net = sum(b["net_value"] for b in brokers if b["type"] == "retail")

    score = 50.0
    pressure = "neutral"
    if smart_net > 0 and total_net > 0:
        score = 72.0
        pressure = "accumulation"
    if smart_net > 0 and retail_net < 0 and total_net > 0:
        score = 82.0
        pressure = "smart_accumulation"
    if smart_net < 0 and total_net < 0:
        score = 28.0
        pressure = "distribution"
    if smart_net < 0 and retail_net > 0:
        score = 18.0
        pressure = "retail_exit_liquidity"

    if top_buy_share >= 0.65 and pressure in ("accumulation", "smart_accumulation"):
        score = min(90.0, score + 6.0)
    if top_sell_share >= 0.65 and pressure in ("distribution", "retail_exit_liquidity"):
        score = max(10.0, score - 6.0)

    signal = "bullish" if score >= 60 else "bearish" if score <= 40 else "neutral"

    def public_row(broker: Dict[str, Any]) -> Dict[str, Any]:
        buy = broker["buy_value"]
        sell = broker["sell_value"]
        net = broker["net_value"]
        return {
            "code": broker["code"],
            "name": broker["name"],
            "type": broker["type"],
            "buy_value": round(buy, 2),
            "sell_value": round(sell, 2),
            "net_value": round(net, 2),
            "buy_bil": round(buy / 1e9, 2),
            "sell_bil": round(sell / 1e9, 2),
            "net_bil": round(net / 1e9, 2),
        }

    dominant_buyer = top_buyers[0] if top_buyers else {}
    dominant_seller = top_sellers[0] if top_sellers else {}

    return {
        "score": round(score, 2),
        "signal": signal,
        "pressure": pressure,
        "total_buy_bil": round(total_buy / 1e9, 2),
        "total_sell_bil": round(total_sell / 1e9, 2),
        "total_net_bil": round(total_net / 1e9, 2),
        "smart_money_net_bil": round(smart_net / 1e9, 2),
        "retail_net_bil": round(retail_net / 1e9, 2),
        "top5_buy_share_pct": round(top_buy_share * 100, 1),
        "top5_sell_share_pct": round(top_sell_share * 100, 1),
        "dominant_buyer": public_row(dominant_buyer) if dominant_buyer else {},
        "dominant_seller": public_row(dominant_seller) if dominant_seller else {},
        "top_buyers": [public_row(b) for b in top_buyers],
        "top_sellers": [public_row(b) for b in top_sellers],
        "net_buyers": [public_row(b) for b in net_buyers],
        "net_sellers": [public_row(b) for b in net_sellers],
    }


class BrokerBehaviorEngine(BaseEngine):
    def __init__(self):
        super().__init__("BrokerBehaviorEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            broker_rows = (
                kwargs.get("broker_summary_raw")
                or kwargs.get("broker_data_raw")
                or kwargs.get("broker_rows")
                or []
            )
            behavior = summarize_broker_behavior(broker_rows, top_n=5)

            pressure = behavior.get("pressure", "neutral")
            total_net = behavior.get("total_net_bil", 0)
            smart_net = behavior.get("smart_money_net_bil", 0)
            dominant_buyer = behavior.get("dominant_buyer", {}).get("code", "-")
            dominant_seller = behavior.get("dominant_seller", {}).get("code", "-")

            if behavior.get("reason"):
                rationale = f"Broker behavior unavailable: {behavior['reason']}."
            elif behavior["signal"] == "bullish":
                rationale = (
                    f"Broker behavior {pressure}: top buyer {dominant_buyer}, "
                    f"smart money net {smart_net:+.2f}B, total net {total_net:+.2f}B."
                )
            elif behavior["signal"] == "bearish":
                rationale = (
                    f"Broker behavior {pressure}: top seller {dominant_seller}, "
                    f"smart money net {smart_net:+.2f}B, total net {total_net:+.2f}B."
                )
            else:
                rationale = (
                    f"Broker behavior neutral: top buyer {dominant_buyer}, "
                    f"top seller {dominant_seller}, total net {total_net:+.2f}B."
                )

            return EngineResult(
                engine_name=self.name,
                score=behavior.get("score", 50.0),
                signal=behavior.get("signal", "neutral"),
                confidence=80.0 if broker_rows else 0.0,
                rationale=rationale,
                data=behavior,
            )
        except Exception as e:
            return self._safe_result(str(e))
