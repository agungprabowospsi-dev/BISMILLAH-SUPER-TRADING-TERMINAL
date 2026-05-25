import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.core import invesgo


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _range(days: int = 30) -> tuple[str, str]:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"), _today()


async def _safe(coro, default=None, timeout: int = 8):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except Exception:
        return default


def _rows(payload: Any, *keys: str) -> List[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys or ("data", "items", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _flow_members(flow: dict) -> dict:
    out: Dict[str, str] = {}
    if not isinstance(flow, dict):
        return out
    for label in ("gain", "loss", "accum", "dist"):
        for row in _rows(flow.get(label)):
            code = str(row.get("code") or row.get("ticker") or "").upper()
            if code:
                out[code] = label
    return out


def _dominant_brokers(broker_summary: list) -> dict:
    rows = [x for x in (broker_summary or []) if isinstance(x, dict)]
    if not rows:
        return {}
    by_net = sorted(rows, key=lambda x: _num(x.get("net_value")), reverse=True)
    by_sell = sorted(rows, key=lambda x: _num(x.get("net_value")))
    buyer = by_net[0] if by_net else {}
    seller = by_sell[0] if by_sell else {}
    return {
        "buyer_code": buyer.get("code") or buyer.get("broker") or "",
        "buyer_name": buyer.get("name") or buyer.get("broker_name") or "",
        "buyer_net_value": _num(buyer.get("net_value")),
        "seller_code": seller.get("code") or seller.get("broker") or "",
        "seller_name": seller.get("name") or seller.get("broker_name") or "",
        "seller_net_value": _num(seller.get("net_value")),
    }


def _summarize_time_table(rows: list) -> dict:
    rows = _rows(rows)
    if not rows:
        return {"available": False}
    buy = sum(_num(x.get("buy_lot") or x.get("buy") or x.get("buy_volume")) for x in rows[-8:])
    sell = sum(_num(x.get("sell_lot") or x.get("sell") or x.get("sell_volume")) for x in rows[-8:])
    close = _num(rows[-1].get("close") or rows[-1].get("price"))
    open_ = _num(rows[0].get("open") or rows[0].get("price") or close)
    pressure = "buy_pressure" if buy > sell * 1.2 else "sell_pressure" if sell > buy * 1.2 else "balanced"
    return {
        "available": True,
        "rows": len(rows),
        "latest_time": rows[-1].get("time") or rows[-1].get("date"),
        "last_close": close,
        "change_from_first_pct": round(((close - open_) / open_ * 100), 2) if open_ else 0,
        "buy_lot": round(buy, 2),
        "sell_lot": round(sell, 2),
        "pressure": pressure,
    }


def _summarize_momentum(rows: list) -> dict:
    rows = _rows(rows)
    if not rows:
        return {"available": False}
    latest = rows[-1]
    buy_pct = _num(latest.get("buy_percentage"))
    sell_pct = _num(latest.get("sell_percentage"))
    return {
        "available": True,
        "rows": len(rows),
        "latest_time": latest.get("time") or latest.get("date"),
        "buy_percentage": buy_pct,
        "sell_percentage": sell_pct,
        "bias": "buy_momentum" if buy_pct > sell_pct + 10 else "sell_momentum" if sell_pct > buy_pct + 10 else "balanced",
    }


def _summarize_key_stat(payload: dict) -> dict:
    rows = _rows(payload, "rows")
    summary = {"available": bool(rows), "rows": len(rows)}
    wanted = ("roe", "roa", "npm", "der", "eps", "per", "pbv", "revenue", "net income")
    picked = []
    for row in rows:
        name = str(row.get("name") or "").lower()
        if any(w in name for w in wanted):
            values = row.get("values") if isinstance(row.get("values"), list) else []
            latest = values[-1] if values else {}
            picked.append({"name": row.get("name"), "latest": latest.get("amount")})
    summary["selected"] = picked[:8]
    return summary


def _summarize_calendar(payload: dict) -> dict:
    rows = _rows(payload, "data")
    return {
        "available": bool(rows),
        "count": len(rows),
        "items": [
            {
                "code": row.get("code"),
                "type": row.get("type"),
                "payload": row.get("payload"),
            }
            for row in rows[:5]
        ],
    }


def apply_official_enrichment_to_action_plan(action_plan: dict, enrichment: dict) -> dict:
    """Attach official Invezgo guardrails without replacing the base engine decision."""
    action = dict(action_plan or {})
    enrichment = enrichment or {}
    if not enrichment.get("available"):
        action["official_decision_context"] = {"available": False}
        return action

    confirmations = list(action.get("confirmation_needed") or [])
    invalidations = list(action.get("invalidation_rules") or [])
    warnings = [x for x in enrichment.get("warnings") or [] if isinstance(x, dict)]
    time_table = enrichment.get("time_table") or {}
    momentum = enrichment.get("momentum_chart") or {}
    corporate_actions = enrichment.get("corporate_actions") or {}
    broker_stalker = enrichment.get("broker_stalker") or {}

    risk_flags = []
    if time_table.get("pressure") == "sell_pressure":
        risk_flags.append("TIME_TABLE_SELL_PRESSURE")
        confirmations.append("Official Time Table tidak lagi menunjukkan sell pressure.")
        invalidations.append("Official Time Table sell pressure berlanjut saat harga gagal reclaim trigger.")
    elif time_table.get("pressure") == "buy_pressure":
        confirmations.append("Official Time Table tetap buy pressure saat trigger disentuh.")

    if momentum.get("bias") == "sell_momentum":
        risk_flags.append("MOMENTUM_SELL_BIAS")
        confirmations.append("Official Momentum Chart kembali balanced/buy momentum.")
        invalidations.append("Official Momentum sell bias berlanjut bersamaan breakdown support intraday.")
    elif momentum.get("bias") == "buy_momentum":
        confirmations.append("Official Momentum Chart tetap buy momentum saat entry dieksekusi.")

    if int(corporate_actions.get("count") or 0) > 0:
        risk_flags.append("CORPORATE_ACTION_CONTEXT")
        confirmations.append("Corporate action resmi sudah dicek dan tidak mengganggu risk/reward entry.")

    medium_or_high = [x for x in warnings if str(x.get("level", "")).upper() in ("MEDIUM", "HIGH")]
    risk_score = len(set(risk_flags)) + len(medium_or_high)
    base_decision = str(action.get("decision") or "").upper()
    requires_confirmation = risk_score > 0 and base_decision in ("GO", "STRONG GO", "BUY", "ACCUMULATE")

    action["confirmation_needed"] = list(dict.fromkeys(confirmations))
    action["invalidation_rules"] = list(dict.fromkeys(invalidations))
    action["requires_official_confirmation"] = bool(requires_confirmation)
    action["official_decision_context"] = {
        "available": True,
        "policy": "additive_guardrail_no_engine_override",
        "risk_level": "HIGH" if risk_score >= 3 else "MEDIUM" if risk_score else "LOW",
        "risk_flags": sorted(set(risk_flags)),
        "time_table_pressure": time_table.get("pressure"),
        "momentum_bias": momentum.get("bias"),
        "broker_stalker_available_count": broker_stalker.get("available_count", 0),
        "corporate_action_count": corporate_actions.get("count", 0),
        "warning_count": len(warnings),
    }
    if requires_confirmation:
        action["decision_modifier"] = "CONDITIONAL_GO_OFFICIAL_CONFIRMATION_REQUIRED"
        action["next_action"] = (
            "Official Invezgo guardrail aktif; tunggu konfirmasi tambahan sebelum eksekusi. "
            + str(action.get("next_action") or "")
        ).strip()
    elif risk_score:
        action["decision_modifier"] = "OFFICIAL_RISK_CONTEXT_ATTACHED"
    else:
        action["decision_modifier"] = action.get("decision_modifier") or "OFFICIAL_CONTEXT_CLEAR"
    return action


async def enrich_screener_results(results: List[dict], mode: str = "swing") -> dict:
    tickers = [str(x.get("ticker") or x.get("code") or "").upper() for x in results if isinstance(x, dict)]
    tickers = [x for x in tickers if x]
    date = _today()
    from_date, to_date = _range(30)

    top_change, top_foreign, top_accum, top_ritel, sector_rotation, sector_stalker = await asyncio.gather(
        _safe(invesgo.get_top_flow("change", date=date), {}),
        _safe(invesgo.get_top_flow("foreign", date=date), {}),
        _safe(invesgo.get_top_flow("accumulation", date=date), {}),
        _safe(invesgo.get_top_flow("ritel", date=date), {}),
        _safe(invesgo.get_sector_rotation(), {}),
        _safe(invesgo.get_sector_stalker(from_date=from_date, to_date=to_date), {}),
    )

    flow_maps = {
        "top_change": _flow_members(top_change),
        "top_foreign": _flow_members(top_foreign),
        "top_accumulation": _flow_members(top_accum),
        "top_ritel": _flow_members(top_ritel),
    }
    timeframe = "1" if mode == "scalping" else "5" if mode == "intraday" else "D"
    mtf_payloads = await asyncio.gather(*[
        _safe(invesgo.get_multi_timeframe_chart(ticker, timeframe=timeframe), [], timeout=6)
        for ticker in tickers[:5]
    ])
    mtf_map = {ticker: {"available": bool(rows), "rows": len(rows), "timeframe": timeframe} for ticker, rows in zip(tickers[:5], mtf_payloads)}

    for item in results:
        ticker = str(item.get("ticker") or item.get("code") or "").upper()
        item["official_enrichment"] = {
            "flow_tags": {name: fmap.get(ticker) for name, fmap in flow_maps.items() if fmap.get(ticker)},
            "multi_timeframe": mtf_map.get(ticker, {"available": False, "timeframe": timeframe}),
            "liquidity": {
                "value": _num(item.get("_liq_value")),
                "freq": _num(item.get("_liq_freq")),
                "tier": item.get("_idx_tier"),
            },
            "policy": "additive_only_no_decision_override",
        }

    return {
        "available": True,
        "date": date,
        "top_flow_counts": {k: len(v) for k, v in flow_maps.items()},
        "sector_rotation_available": bool(sector_rotation),
        "sector_stalker_available": bool(sector_stalker),
        "quota_policy": "top-flow/sector fetched once per screener run; multi-timeframe only for final top candidates",
    }


async def build_analytic_enrichment(ticker: str, mode: str = "swing", broker_summary: list = None) -> dict:
    ticker = ticker.upper()
    date = _today()
    broker_info = _dominant_brokers(broker_summary or [])
    buyer = broker_info.get("buyer_code")
    seller = broker_info.get("seller_code")

    tasks = [
        _safe(invesgo.get_time_table(ticker, date=date, range_minutes=5), []),
        _safe(invesgo.get_momentum_chart(ticker, date=date, range_minutes=5), []),
        _safe(invesgo.get_intraday_inventory_chart(ticker, date=date, range_minutes=5), {}),
        _safe(invesgo.get_sankey_chart(ticker, date=date), {}),
        _safe(invesgo.get_key_stat(ticker), {}),
        _safe(invesgo.get_corporate_actions(ticker=ticker, limit=5), {}),
    ]
    if buyer:
        tasks.append(_safe(invesgo.get_broker_stalker(buyer, ticker), {}))
    if seller and seller != buyer:
        tasks.append(_safe(invesgo.get_broker_stalker(seller, ticker), {}))

    payloads = await asyncio.gather(*tasks)
    time_table, momentum, intraday_inventory, sankey, key_stat, calendar = payloads[:6]
    broker_stalkers = payloads[6:]

    warnings = []
    tt = _summarize_time_table(time_table)
    mo = _summarize_momentum(momentum)
    if tt.get("pressure") == "sell_pressure":
        warnings.append({"level": "MEDIUM", "type": "TIME_TABLE_SELL_PRESSURE", "message": "Time table menunjukkan sell pressure intraday."})
    if mo.get("bias") == "sell_momentum":
        warnings.append({"level": "MEDIUM", "type": "MOMENTUM_SELL_BIAS", "message": "Momentum chart condong ke sell momentum."})
    cal = _summarize_calendar(calendar)
    if cal.get("count"):
        warnings.append({"level": "LOW", "type": "CORPORATE_ACTION_CONTEXT", "message": "Ada corporate action terkait ticker; cek detail sebelum entry."})

    return {
        "available": True,
        "date": date,
        "time_table": tt,
        "momentum_chart": mo,
        "intraday_inventory_available": bool(intraday_inventory),
        "sankey_available": bool(sankey),
        "broker_stalker": {
            "dominant": broker_info,
            "available_count": sum(1 for x in broker_stalkers if x),
        },
        "key_stat": _summarize_key_stat(key_stat),
        "corporate_actions": cal,
        "warnings": warnings,
        "quota_policy": "cached official enrichment; single ticker only; no decision override",
    }


async def build_monitoring_enrichment(ticker: str, mode: str = "swing", broker_summary: list = None) -> dict:
    enrichment = await build_analytic_enrichment(ticker, mode=mode, broker_summary=broker_summary)
    enrichment["scope"] = "monitoring_warning_context"
    return enrichment
