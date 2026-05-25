from typing import Any, Dict, List

from app.core.money_maker_store import get_latest_flow_snapshot, save_flow_snapshot
from app.engines.orderbook_microstructure import normalize_orderbook


FOREIGN_BROKERS = {"YP", "BK", "RX", "ZP", "AK", "CC", "DB", "MS", "CS", "ML", "DP", "KI", "OD", "LG"}
STRONG_LOCAL_BROKERS = {"GS", "MU", "NK", "LS", "EP", "FZ", "YU", "KK", "DH", "PC", "RO", "BW", "GA", "CP", "BB", "MG", "IF"}
RETAIL_BROKERS = {"XL", "XC", "YP", "PD", "IF", "HP", "KS", "FH", "IN", "RB", "ID"}
GOVERNMENT_LINKED_BROKERS = {"CC"}


MODE_PROFILES = {
    "swing": {
        "volume": 0.16,
        "value": 0.16,
        "broker": 0.28,
        "foreign": 0.16,
        "orderbook": 0.08,
        "structure": 0.10,
        "official": 0.06,
        "entry_label": "FLOW_FOLLOWER_SWING",
    },
    "intraday": {
        "volume": 0.17,
        "value": 0.15,
        "broker": 0.22,
        "foreign": 0.10,
        "orderbook": 0.16,
        "structure": 0.08,
        "official": 0.12,
        "entry_label": "FLOW_FOLLOWER_INTRADAY",
    },
    "scalping": {
        "volume": 0.16,
        "value": 0.10,
        "broker": 0.16,
        "foreign": 0.06,
        "orderbook": 0.26,
        "structure": 0.06,
        "official": 0.20,
        "entry_label": "FLOW_FOLLOWER_SCALPING",
    },
}

_FLOW_MEMORY: Dict[str, Dict[str, Any]] = {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _avg(values: List[float]) -> float:
    values = [x for x in values if x is not None]
    return sum(values) / len(values) if values else 0.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _broker_type(code: str) -> str:
    code = str(code or "").upper()
    if code in GOVERNMENT_LINKED_BROKERS:
        return "government_linked_proxy"
    if code in FOREIGN_BROKERS:
        return "foreign"
    if code in STRONG_LOCAL_BROKERS:
        return "strong_local"
    if code in RETAIL_BROKERS:
        return "retail"
    return "other"


def _normalize_broker(row: Dict[str, Any]) -> Dict[str, Any]:
    code = str(row.get("code") or row.get("broker_code") or row.get("broker") or "").upper()
    buy_value = _num(row.get("buy_value") or row.get("buy") or row.get("buy_val"))
    sell_value = _num(row.get("sell_value") or row.get("sell") or row.get("sell_val"))
    buy_lot = _num(row.get("buy_lot") or row.get("buy_volume") or row.get("buy_vol"))
    sell_lot = _num(row.get("sell_lot") or row.get("sell_volume") or row.get("sell_vol"))
    net_value = row.get("net_value")
    if net_value is None:
        net_value = buy_value - sell_value
    return {
        "code": code,
        "type": _broker_type(code),
        "buy_value": buy_value,
        "sell_value": sell_value,
        "buy_lot": buy_lot,
        "sell_lot": sell_lot,
        "net_value": _num(net_value),
        "avg_buy": _num(row.get("buy_avg") or row.get("avg_buy") or row.get("b_avg")),
        "avg_sell": _num(row.get("sell_avg") or row.get("avg_sell") or row.get("s_avg")),
    }


def _ohlcv_metrics(ohlcv: List[Dict[str, Any]], screener_item: Dict[str, Any] = None) -> Dict[str, float]:
    rows = [x for x in (ohlcv or []) if isinstance(x, dict)]
    if not rows:
        return {"vsr": 1.0, "vii": 1.0, "change_pct": _num((screener_item or {}).get("change_pct"))}
    last = rows[-1]
    volumes = [_num(x.get("volume")) for x in rows[-10:]]
    closes = [_num(x.get("close")) for x in rows[-10:]]
    values = [
        _num(x.get("value") or x.get("turnover") or x.get("volume")) * _num(x.get("close"), 1.0)
        for x in rows[-10:]
    ]
    last_volume = _num(last.get("volume"))
    last_value = _num(last.get("value") or last.get("turnover") or last_volume * _num(last.get("close"), 1.0))
    avg_vol = _avg(volumes[:-1]) or _avg(volumes) or 1.0
    avg_value = _avg(values[:-1]) or _avg(values) or 1.0
    prev_close = _num(rows[-2].get("close")) if len(rows) >= 2 else _num(last.get("open") or last.get("close"))
    close = _num(last.get("close"))
    change_pct = ((close - prev_close) / prev_close * 100) if prev_close else _num((screener_item or {}).get("change_pct"))
    high_lookback = max((_num(x.get("high")) for x in rows[-20:]), default=close)
    low_lookback = min((_num(x.get("low")) for x in rows[-20:]), default=close)
    range_pct = ((high_lookback - low_lookback) / close * 100) if close else 0.0
    return {
        "vsr": last_volume / avg_vol if avg_vol else 1.0,
        "vii": last_value / avg_value if avg_value else 1.0,
        "change_pct": change_pct,
        "range_pct": range_pct,
        "close": close,
        "high_lookback": high_lookback,
        "low_lookback": low_lookback,
    }


def _broker_metrics(broker_summary: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [_normalize_broker(x) for x in (broker_summary or []) if isinstance(x, dict)]
    rows = [x for x in rows if x["buy_value"] or x["sell_value"] or x["net_value"]]
    if not rows:
        return {
            "available": False,
            "broker_score": 50.0,
            "bcs": 0.0,
            "strong_net": 0.0,
            "retail_net": 0.0,
            "foreign_net": 0.0,
            "government_linked_net": 0.0,
            "top_buyers": [],
            "top_sellers": [],
        }

    total_buy = sum(x["buy_value"] for x in rows)
    total_sell = sum(x["sell_value"] for x in rows)
    total_net = sum(x["net_value"] for x in rows)
    top_buyers = sorted(rows, key=lambda x: x["buy_value"], reverse=True)[:5]
    top_sellers = sorted(rows, key=lambda x: x["sell_value"], reverse=True)[:5]
    net_buyers = sorted(rows, key=lambda x: x["net_value"], reverse=True)[:5]
    net_sellers = sorted(rows, key=lambda x: x["net_value"])[:5]
    top3_net_buy = sum(max(0.0, x["net_value"]) for x in net_buyers[:3])
    bcs = top3_net_buy / total_buy if total_buy else 0.0

    strong_types = {"foreign", "strong_local", "government_linked_proxy"}
    strong_net = sum(x["net_value"] for x in rows if x["type"] in strong_types)
    retail_net = sum(x["net_value"] for x in rows if x["type"] == "retail")
    foreign_net = sum(x["net_value"] for x in rows if x["type"] == "foreign")
    government_linked_net = sum(x["net_value"] for x in rows if x["type"] == "government_linked_proxy")

    broker_score = 50.0
    if strong_net > 0:
        broker_score += 14
    if strong_net > 0 and retail_net < 0:
        broker_score += 16
    if bcs >= 0.40:
        broker_score += 12
    elif bcs >= 0.25:
        broker_score += 6
    if strong_net < 0:
        broker_score -= 18
    if strong_net < 0 and retail_net > 0:
        broker_score -= 18
    if sum(max(0.0, abs(x["net_value"])) for x in net_sellers[:3]) > max(total_buy, 1) * 0.35 and total_net < 0:
        broker_score -= 8

    def public(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "code": row["code"],
            "type": row["type"],
            "buy_bil": round(row["buy_value"] / 1e9, 2),
            "sell_bil": round(row["sell_value"] / 1e9, 2),
            "net_bil": round(row["net_value"] / 1e9, 2),
            "avg_buy": row["avg_buy"],
            "avg_sell": row["avg_sell"],
        }

    weighted_value = sum(max(0.0, x["buy_value"]) for x in net_buyers[:5])
    bandar_avg = (
        sum(max(0.0, x["buy_value"]) * x["avg_buy"] for x in net_buyers[:5] if x["avg_buy"] > 0) / weighted_value
        if weighted_value else 0.0
    )
    return {
        "available": True,
        "broker_score": round(_clamp(broker_score), 2),
        "bcs": round(bcs, 4),
        "total_buy_bil": round(total_buy / 1e9, 2),
        "total_sell_bil": round(total_sell / 1e9, 2),
        "total_net_bil": round(total_net / 1e9, 2),
        "strong_net_bil": round(strong_net / 1e9, 2),
        "retail_net_bil": round(retail_net / 1e9, 2),
        "foreign_net_bil": round(foreign_net / 1e9, 2),
        "government_linked_net_bil": round(government_linked_net / 1e9, 2),
        "bandar_avg_price": round(bandar_avg, 2),
        "top_buyers": [public(x) for x in top_buyers],
        "top_sellers": [public(x) for x in top_sellers],
        "net_buyers": [public(x) for x in net_buyers],
        "net_sellers": [public(x) for x in net_sellers],
    }


def _orderbook_metrics(orderbook: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_orderbook(orderbook or {})
    bids = normalized.get("bids") or []
    asks = normalized.get("asks") or []
    if not bids or not asks:
        return {"available": False, "orderbook_score": 50.0, "bodr": 1.0}
    total_bid = sum(_num(x.get("lot")) for x in bids[:10])
    total_ask = sum(_num(x.get("lot")) for x in asks[:10])
    bodr = total_bid / total_ask if total_ask else 1.0
    score = 50.0
    if bodr >= 1.8:
        score += 24
    elif bodr >= 1.2:
        score += 14
    elif bodr < 0.7:
        score -= 20
    elif bodr < 1.0:
        score -= 8
    if _num(normalized.get("spread_pct")) > 1.2:
        score -= 8
    return {
        "available": True,
        "orderbook_score": round(_clamp(score), 2),
        "bodr": round(bodr, 3),
        "spread_pct": normalized.get("spread_pct", 0),
        "best_bid": normalized.get("best_bid", 0),
        "best_ask": normalized.get("best_ask", 0),
        "source": normalized.get("source"),
    }


def _official_score(official_enrichment: Dict[str, Any]) -> Dict[str, Any]:
    data = official_enrichment or {}
    if not data.get("available"):
        return {"available": False, "official_score": 50.0, "risk_flags": []}
    score = 50.0
    risk_flags = []
    tt = data.get("time_table") or {}
    mo = data.get("momentum_chart") or {}
    ca = data.get("corporate_actions") or {}
    if tt.get("pressure") == "buy_pressure":
        score += 14
    elif tt.get("pressure") == "sell_pressure":
        score -= 18
        risk_flags.append("TIME_TABLE_SELL_PRESSURE")
    if mo.get("bias") == "buy_momentum":
        score += 14
    elif mo.get("bias") == "sell_momentum":
        score -= 18
        risk_flags.append("MOMENTUM_SELL_BIAS")
    if int(ca.get("count") or 0) > 0:
        score -= 4
        risk_flags.append("CORPORATE_ACTION_CONTEXT")
    for warning in data.get("warnings") or []:
        if isinstance(warning, dict) and str(warning.get("level", "")).upper() in ("MEDIUM", "HIGH"):
            score -= 4
    return {
        "available": True,
        "official_score": round(_clamp(score), 2),
        "risk_flags": risk_flags,
        "time_table_pressure": tt.get("pressure"),
        "momentum_bias": mo.get("bias"),
        "corporate_action_count": ca.get("count", 0),
    }


def _structure_score(engine_result: Dict[str, Any], bandarmology: Dict[str, Any], pattern: Dict[str, Any]) -> Dict[str, Any]:
    score = _num((engine_result or {}).get("composite_score"), 50.0)
    phase = str((bandarmology or {}).get("phase") or "").lower()
    if phase in ("accumulation", "early_accumulation", "markup", "accumulation_late"):
        score += 8
    if phase in ("distribution", "decline", "markdown"):
        score -= 18
    if pattern and _num(pattern.get("score")) >= 65:
        score += 5
    return {"structure_score": round(_clamp(score), 2), "phase_hint": phase or "unknown"}


def _range_contraction(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(rows) < 8:
        return {"available": False, "contracting": False, "ratio": 1.0}
    recent = rows[-4:]
    previous = rows[-8:-4]

    def candle_range(row: Dict[str, Any]) -> float:
        close = _num(row.get("close"), 1.0)
        return ((_num(row.get("high")) - _num(row.get("low"))) / close * 100) if close else 0.0

    recent_avg = _avg([candle_range(x) for x in recent])
    previous_avg = _avg([candle_range(x) for x in previous])
    ratio = recent_avg / previous_avg if previous_avg else 1.0
    return {
        "available": True,
        "contracting": ratio <= 0.75,
        "ratio": round(ratio, 3),
        "recent_range_pct": round(recent_avg, 2),
        "previous_range_pct": round(previous_avg, 2),
    }


def _pattern_row(name: str, score: float, polarity: str, reason: str, evidence: List[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "score": round(_clamp(score), 2),
        "polarity": polarity,
        "reason": reason,
        "evidence": evidence,
    }


def _detect_money_maker_patterns(
    *,
    mode: str,
    ohlcv: List[Dict[str, Any]],
    ohlcv_m: Dict[str, Any],
    broker_m: Dict[str, Any],
    order_m: Dict[str, Any],
    official_m: Dict[str, Any],
    memory: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows = [x for x in (ohlcv or []) if isinstance(x, dict)]
    patterns: List[Dict[str, Any]] = []
    contraction = _range_contraction(rows)
    close = _num(ohlcv_m.get("close"))
    high = _num(ohlcv_m.get("high_lookback"))
    low = _num(ohlcv_m.get("low_lookback"))
    change_pct = _num(ohlcv_m.get("change_pct"))
    vsr = _num(ohlcv_m.get("vsr"), 1.0)
    vii = _num(ohlcv_m.get("vii"), 1.0)
    strong_net = _num(broker_m.get("strong_net_bil"))
    retail_net = _num(broker_m.get("retail_net_bil"))
    foreign_net = _num(broker_m.get("foreign_net_bil"))
    bcs = _num(broker_m.get("bcs"))
    bodr = _num(order_m.get("bodr"), 1.0)
    tt_pressure = official_m.get("time_table_pressure")
    momentum_bias = official_m.get("momentum_bias")
    near_resistance = bool(close and high and close >= high * 0.96)
    near_support = bool(close and low and close <= low * 1.06)
    range_pct = _num(ohlcv_m.get("range_pct"))
    prior_close = _num(rows[-8].get("close")) if len(rows) >= 8 else close
    prior_drop_pct = ((close - prior_close) / prior_close * 100) if prior_close else 0.0

    if (
        mode == "swing"
        and contraction.get("contracting")
        and near_resistance
        and vsr >= 1.2
        and strong_net > 0
        and bcs >= 0.25
    ):
        patterns.append(_pattern_row(
            "LAUNCHPAD_CANDIDATE",
            82,
            "bullish",
            "Range menyempit di dekat resistance dengan broker kuat akumulasi.",
            ["range_contraction", "near_resistance", "strong_broker_accumulation"],
        ))

    if (
        mode == "swing"
        and prior_drop_pct <= -6
        and near_support
        and vsr >= 1.2
        and strong_net > 0
        and range_pct <= 18
    ):
        patterns.append(_pattern_row(
            "DROP_BASE_RALLY_CANDIDATE",
            76,
            "bullish",
            "Harga drop lalu base di support, volume/value mulai hidup, broker kuat menampung.",
            ["prior_drop", "support_base", "strong_broker_accumulation"],
        ))

    if (
        vsr >= 1.35
        and vii >= 1.2
        and abs(change_pct) <= (3.0 if mode == "swing" else 1.8 if mode == "intraday" else 1.2)
        and strong_net > 0
    ):
        patterns.append(_pattern_row(
            "HIDDEN_ACCUMULATION",
            84,
            "bullish",
            "Volume/value naik tapi harga ditahan; indikasi akumulasi senyap.",
            ["volume_value_expansion", "price_control", "strong_net_buy"],
        ))

    if strong_net > 0 and retail_net < 0 and bcs >= 0.25:
        patterns.append(_pattern_row(
            "RETAIL_DUMP_ABSORPTION",
            86,
            "bullish",
            "Broker kuat menampung saat broker retail/lemah membuang barang.",
            ["strong_hands_buy", "retail_sell", "broker_concentration"],
        ))

    if bodr >= 1.8 and strong_net <= 0 and tt_pressure == "sell_pressure":
        patterns.append(_pattern_row(
            "FAKE_BID_WALL_RISK",
            22,
            "bearish",
            "Bid terlihat tebal tetapi flow resmi/broker tidak mendukung.",
            ["thick_bid", "weak_broker_support", "sell_pressure"],
        ))

    if vsr >= 1.8 and change_pct <= 1.0 and (strong_net < 0 or tt_pressure == "sell_pressure" or momentum_bias == "sell_momentum"):
        patterns.append(_pattern_row(
            "CLIMAX_DISTRIBUTION",
            12,
            "bearish",
            "Volume besar tetapi harga tidak maju; potensi distribusi di area ramai.",
            ["high_volume", "price_stall", "sell_flow"],
        ))

    if strong_net < 0 and retail_net > 0:
        patterns.append(_pattern_row(
            "RETAIL_EXIT_LIQUIDITY",
            10,
            "bearish",
            "Broker kuat keluar saat retail menjadi penampung.",
            ["strong_net_sell", "retail_net_buy"],
        ))

    if foreign_net < -1 and strong_net > 0:
        patterns.append(_pattern_row(
            "FOREIGN_LOCAL_DIVERGENCE",
            42,
            "caution",
            "Local/strong broker akumulasi tetapi asing net sell; butuh konfirmasi lanjutan.",
            ["foreign_sell", "local_support"],
        ))
    elif foreign_net > 1 and strong_net < 0:
        patterns.append(_pattern_row(
            "FOREIGN_LOCAL_DIVERGENCE",
            38,
            "caution",
            "Asing net buy tetapi broker kuat agregat melepas; flow belum sinkron.",
            ["foreign_buy", "local_distribution"],
        ))

    prev_buyers = set(memory.get("prev_top_buyers") or [])
    prev_verdict = str(memory.get("prev_verdict") or "")
    current_sellers = {x.get("code") for x in broker_m.get("net_sellers", [])[:5] if x.get("code")}
    flipped = sorted(prev_buyers.intersection(current_sellers))
    if flipped or (prev_verdict in ("STRONG_FLOW_IN", "EARLY_FLOW") and strong_net < 0):
        patterns.append(_pattern_row(
            "BROKER_FLIP_DISTRIBUTION",
            18,
            "bearish",
            "Broker yang sebelumnya menopang mulai muncul di sisi jual.",
            ["broker_flip"] + flipped[:3],
        ))

    if (
        contraction.get("contracting")
        and abs(change_pct) <= 2.0
        and strong_net > 0
        and (vii >= 1.1 or bcs >= 0.25)
        and not near_resistance
    ):
        patterns.append(_pattern_row(
            "PRE_MARKUP_SILENCE",
            78,
            "bullish",
            "Harga masih diam tetapi range menyempit dan uang kuat mulai masuk.",
            ["range_contraction", "quiet_price", "early_money_flow"],
        ))

    return sorted(patterns, key=lambda x: x["score"], reverse=True)


def _flow_memory_key(ticker: str, mode: str) -> str:
    return f"{str(ticker or '').upper()}:{str(mode or 'swing').lower()}"


def _peek_flow_memory(ticker: str, mode: str) -> Dict[str, Any]:
    runtime = dict(_FLOW_MEMORY.get(_flow_memory_key(ticker, mode), {}))
    if runtime:
        runtime["memory_source"] = "runtime"
        return runtime
    persisted = get_latest_flow_snapshot(ticker, mode)
    if persisted:
        return {
            "bfd_score": persisted.get("bfd_score"),
            "verdict": persisted.get("verdict"),
            "phase": persisted.get("phase"),
            "top_buyers": persisted.get("top_buyers", []),
            "top_sellers": persisted.get("top_sellers", []),
            "patterns": persisted.get("patterns", []),
            "risk_flags": persisted.get("risk_flags", []),
            "created_at": persisted.get("created_at"),
            "memory_source": "sqlite",
            "persistent": True,
        }
    return {}


def _memory_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if not snapshot:
        return {}
    return {
        "bfd_score": snapshot.get("bfd_score"),
        "verdict": snapshot.get("verdict"),
        "phase": snapshot.get("phase"),
        "top_buyers": snapshot.get("top_buyers", []),
        "top_sellers": snapshot.get("top_sellers", []),
        "patterns": snapshot.get("patterns", []),
        "risk_flags": snapshot.get("risk_flags", []),
        "created_at": snapshot.get("created_at"),
        "memory_source": snapshot.get("memory_source") or snapshot.get("persistent_backend") or "external",
        "persistent": bool(snapshot.get("persistent") or snapshot.get("persistent_backend")),
    }


def _commit_flow_memory(ticker: str, mode: str, snapshot: Dict[str, Any], previous_snapshot: Dict[str, Any] = None) -> Dict[str, Any]:
    key = _flow_memory_key(ticker, mode)
    prev = _memory_view(previous_snapshot or {}) or dict(_FLOW_MEMORY.get(key, {}))
    if not prev:
        persisted_prev = get_latest_flow_snapshot(ticker, mode)
        if persisted_prev:
            prev = _memory_view(persisted_prev)
    prev_bfd = _num(prev.get("bfd_score"))
    now_bfd = _num(snapshot.get("bfd_score"))
    delta = now_bfd - prev_bfd if prev else 0.0
    current = {
        "ticker": str(ticker or "").upper(),
        "mode": str(mode or "swing").lower(),
        "prev_bfd_score": prev.get("bfd_score"),
        "bfd_delta": round(delta, 2),
        "prev_verdict": prev.get("verdict"),
        "prev_phase": prev.get("phase"),
        "prev_top_buyers": prev.get("top_buyers", []),
        "prev_top_sellers": prev.get("top_sellers", []),
        "flow_reversal_alert": bool(prev and prev_bfd >= 4 and now_bfd <= 2),
        "improving_flow": bool(prev and delta >= 2),
        "weakening_flow": bool(prev and delta <= -2),
        "memory_available": bool(prev),
        "previous_memory_source": prev.get("memory_source"),
    }
    _FLOW_MEMORY[key] = {
        "bfd_score": snapshot.get("bfd_score"),
        "verdict": snapshot.get("verdict"),
        "phase": snapshot.get("phase"),
        "top_buyers": snapshot.get("top_buyers", []),
        "top_sellers": snapshot.get("top_sellers", []),
    }
    persisted = save_flow_snapshot(ticker, mode, snapshot)
    current["persistent_saved"] = bool(persisted.get("saved"))
    current["persistent_db_path"] = persisted.get("db_path")
    current["persistent_backend"] = persisted.get("persistent_backend", "sqlite")
    current["memory_source"] = "runtime+sqlite" if current.get("memory_available") else "sqlite"
    return current


def _execution_intelligence(mode: str, score: float, verdict: str, patterns: List[Dict[str, Any]], order_m: Dict[str, Any], official_m: Dict[str, Any]) -> Dict[str, Any]:
    mode_l = str(mode or "swing").lower()
    bearish_patterns = {p["name"] for p in patterns if p.get("polarity") == "bearish"}
    bullish_patterns = {p["name"] for p in patterns if p.get("polarity") == "bullish"}
    bodr = _num(order_m.get("bodr"), 1.0)
    spread = _num(order_m.get("spread_pct"))
    tt = official_m.get("time_table_pressure")
    momentum = official_m.get("momentum_bias")

    if verdict == "FLOW_OUT_AVOID" or bearish_patterns:
        return {
            "stance": "NO_LONG_ENTRY",
            "preferred_order": "NO_LONG_ENTRY",
            "reason": "Money maker flow membaca distribusi/flow out.",
            "size_hint": "0%",
            "mode_rule": mode_l,
        }

    if mode_l == "scalping":
        ok = bodr >= 1.2 and spread <= 0.8 and momentum != "sell_momentum"
        return {
            "stance": "FAST_CONFIRMATION" if ok else "WAIT_MICRO_CONFIRMATION",
            "preferred_order": "MARKET_MOMENTUM" if ok and score >= 72 else "LIMIT_ONLY",
            "reason": "Scalping harus sinkron dengan bid pressure, spread, dan momentum.",
            "size_hint": "small-fast" if ok else "0-20%",
            "mode_rule": "scalping_orderbook_first",
        }

    if mode_l == "intraday":
        ok = (tt in ("buy_pressure", None)) and momentum != "sell_momentum" and bodr >= 1.0
        return {
            "stance": "TRIGGER_READY" if ok and score >= 68 else "WAIT_INTRADAY_TRIGGER",
            "preferred_order": "BUY_STOP_OR_LIMIT_RETEST" if ok else "LIMIT_RETEST_ONLY",
            "reason": "Intraday butuh time table/momentum tidak melawan saat trigger disentuh.",
            "size_hint": "30-50%" if ok and score >= 72 else "10-30%",
            "mode_rule": "intraday_time_table_momentum",
        }

    launchpad = "LAUNCHPAD_CANDIDATE" in bullish_patterns or "PRE_MARKUP_SILENCE" in bullish_patterns
    return {
        "stance": "ACCUMULATE_ON_RETEST" if launchpad or score >= 68 else "WATCHLIST",
        "preferred_order": "LIMIT_ACCUMULATION_OR_BUY_STOP_BREAKOUT" if launchpad else "LIMIT_RETEST",
        "reason": "Swing mengutamakan average bandar, base, dan trigger breakout/retest.",
        "size_hint": "20-30% initial, add on confirmation" if score >= 64 else "watch only",
        "mode_rule": "swing_flow_then_structure",
    }


def _doctrine_context(score: float, bfd_score: int, verdict: str, patterns: List[Dict[str, Any]], structure_m: Dict[str, Any]) -> Dict[str, Any]:
    flags: List[str] = []
    rules: List[str] = []
    bearish = {p["name"] for p in patterns if p.get("polarity") == "bearish"}
    bullish = {p["name"] for p in patterns if p.get("polarity") == "bullish"}
    structure_score = _num(structure_m.get("structure_score"), 50.0)

    if structure_score >= 65 and verdict == "FLOW_OUT_AVOID":
        flags.append("TA_BULLISH_BUT_FLOW_DISTRIBUTION")
        rules.append("Reject/avoid: technical bullish tidak valid jika money maker distribusi.")
    if verdict in ("STRONG_FLOW_IN", "EARLY_FLOW") and structure_score < 60:
        flags.append("FLOW_STRONG_WAIT_TECHNICAL_TRIGGER")
        rules.append("Prepare, bukan chase: flow kuat tapi tunggu trigger/retest struktur.")
    if bfd_score >= 4:
        rules.append("BFD >=4: flow follower zone, gunakan scaling sesuai mode.")
    if bfd_score <= 2 and verdict == "FLOW_OUT_AVOID":
        rules.append("BFD <=2 dengan flow out: exit/avoid cepat, jangan tunggu rebound palsu.")
    if "CLIMAX_DISTRIBUTION" in bearish:
        flags.append("CLIMAX_DISTRIBUTION_DOCTRINE")
        rules.append("Volume besar di puncak tanpa price progress adalah distribusi sampai terbukti sebaliknya.")
    if "RETAIL_DUMP_ABSORPTION" in bullish:
        rules.append("Retail dump absorbed by strong broker: prioritas watchlist/entry bertahap.")
    return {
        "flags": sorted(set(flags)),
        "rules": list(dict.fromkeys(rules)),
        "source": "embedded_idx_bandarmology_doctrine_from_attached_pdfs",
    }


def analyze_money_maker_context(
    *,
    ticker: str,
    mode: str,
    ohlcv: List[Dict[str, Any]] = None,
    engine_result: Dict[str, Any] = None,
    broker_summary: List[Dict[str, Any]] = None,
    orderbook: Dict[str, Any] = None,
    official_enrichment: Dict[str, Any] = None,
    bandarmology: Dict[str, Any] = None,
    foreign_flow: Dict[str, Any] = None,
    pattern: Dict[str, Any] = None,
    screener_item: Dict[str, Any] = None,
    previous_snapshot: Dict[str, Any] = None,
) -> Dict[str, Any]:
    mode_l = str(mode or "swing").lower()
    profile = MODE_PROFILES.get(mode_l, MODE_PROFILES["swing"])
    ohlcv_m = _ohlcv_metrics(ohlcv or [], screener_item=screener_item)
    broker_m = _broker_metrics(broker_summary or [])
    order_m = _orderbook_metrics(orderbook or {})
    official_m = _official_score(official_enrichment or {})
    structure_m = _structure_score(engine_result or {}, bandarmology or {}, pattern or {})
    memory_prev = _memory_view(previous_snapshot or {}) or _peek_flow_memory(ticker, mode_l)

    volume_score = _clamp(50 + (ohlcv_m["vsr"] - 1.0) * 24)
    value_score = _clamp(50 + (ohlcv_m["vii"] - 1.0) * 26)
    foreign_score = _num((foreign_flow or {}).get("score"), 50.0)
    if broker_m.get("foreign_net_bil", 0) > 1:
        foreign_score = max(foreign_score, 68)
    elif broker_m.get("foreign_net_bil", 0) < -1:
        foreign_score = min(foreign_score, 32)

    components = {
        "volume": round(volume_score, 2),
        "value": round(value_score, 2),
        "broker": broker_m["broker_score"],
        "foreign": round(_clamp(foreign_score), 2),
        "orderbook": order_m["orderbook_score"],
        "structure": structure_m["structure_score"],
        "official": official_m["official_score"],
    }
    score = sum(components[k] * profile[k] for k in profile if k in components)
    patterns = _detect_money_maker_patterns(
        mode=mode_l,
        ohlcv=ohlcv or [],
        ohlcv_m=ohlcv_m,
        broker_m=broker_m,
        order_m=order_m,
        official_m=official_m,
        memory=memory_prev,
    )
    bullish_patterns = [p for p in patterns if p.get("polarity") == "bullish"]
    bearish_patterns = [p for p in patterns if p.get("polarity") == "bearish"]
    caution_patterns = [p for p in patterns if p.get("polarity") == "caution"]
    if bullish_patterns:
        score += min(10.0, sum(_num(p.get("score")) - 60 for p in bullish_patterns if _num(p.get("score")) > 60) / 6)
    if bearish_patterns:
        score -= min(18.0, sum(60 - _num(p.get("score")) for p in bearish_patterns if _num(p.get("score")) < 60) / 4)
    if caution_patterns:
        score -= 3.0

    risk_flags = list(official_m.get("risk_flags") or [])
    evidence = []
    if ohlcv_m["vsr"] >= 1.5:
        evidence.append("volume_expansion")
    if ohlcv_m["vii"] >= 1.3:
        evidence.append("value_expansion")
    if broker_m.get("bcs", 0) >= 0.4:
        evidence.append("broker_concentration")
    if broker_m.get("strong_net_bil", 0) > 0 and broker_m.get("retail_net_bil", 0) < 0:
        evidence.append("strong_hands_absorb_retail")
    if order_m.get("bodr", 1.0) >= 1.2:
        evidence.append("bid_offer_buyer_pressure")
    if components["foreign"] >= 60:
        evidence.append("foreign_or_institutional_support")
    for pattern_item in bullish_patterns[:3]:
        evidence.append(pattern_item["name"].lower())

    phase_hint = structure_m.get("phase_hint")
    distribution_pressure = (
        broker_m.get("strong_net_bil", 0) < 0
        or "TIME_TABLE_SELL_PRESSURE" in risk_flags
        or "MOMENTUM_SELL_BIAS" in risk_flags
        or bool(bearish_patterns)
    )
    climax_risk = ohlcv_m["vsr"] >= 1.8 and ohlcv_m["change_pct"] < 1.0 and distribution_pressure
    if broker_m.get("strong_net_bil", 0) < 0 and broker_m.get("retail_net_bil", 0) > 0:
        risk_flags.append("RETAIL_EXIT_LIQUIDITY")
    if climax_risk:
        risk_flags.append("CLIMAX_DISTRIBUTION_RISK")
    for pattern_item in bearish_patterns:
        risk_flags.append(pattern_item["name"])

    if distribution_pressure and score < 58:
        phase = "distribution_trap"
    elif phase_hint in ("distribution", "decline", "markdown"):
        phase = "markdown_or_distribution"
    elif score >= 78 and len(evidence) >= 4:
        phase = "strong_flow_in"
    elif score >= 64 and len(evidence) >= 3:
        phase = "early_flow"
    elif score >= 55:
        phase = "watch_flow"
    else:
        phase = "no_clear_flow"

    bfd_score = 0
    bfd_score += 1 if ohlcv_m["vsr"] >= 1.5 else 0
    bfd_score += 1 if ohlcv_m["vii"] >= 1.3 else 0
    bfd_score += 1 if broker_m.get("bcs", 0) >= 0.4 or broker_m.get("strong_net_bil", 0) > 0 else 0
    bfd_score += 1 if order_m.get("bodr", 1.0) >= 1.2 else 0
    bfd_score += 1 if components["foreign"] >= 60 or official_m.get("time_table_pressure") == "buy_pressure" else 0
    if phase in ("distribution_trap", "markdown_or_distribution"):
        bfd_score = min(bfd_score, 2)

    if phase == "strong_flow_in":
        verdict = "STRONG_FLOW_IN"
    elif phase == "early_flow":
        verdict = "EARLY_FLOW"
    elif phase in ("distribution_trap", "markdown_or_distribution"):
        verdict = "FLOW_OUT_AVOID"
    elif phase == "watch_flow":
        verdict = "WATCH_FLOW"
    else:
        verdict = "NO_CLEAR_FLOW"
    doctrine = _doctrine_context(score, bfd_score, verdict, patterns, structure_m)
    execution = _execution_intelligence(mode_l, score, verdict, patterns, order_m, official_m)
    memory = _commit_flow_memory(
        ticker,
        mode_l,
        {
            "session_key": f"{str(ticker or '').upper()}:{mode_l}:latest",
            "bfd_score": bfd_score,
            "money_maker_score": round(_clamp(score), 2),
            "verdict": verdict,
            "phase": phase,
            "top_buyers": [x.get("code") for x in broker_m.get("net_buyers", [])[:5] if x.get("code")],
            "top_sellers": [x.get("code") for x in broker_m.get("net_sellers", [])[:5] if x.get("code")],
            "patterns": [x.get("name") for x in patterns[:8] if x.get("name")],
            "risk_flags": sorted(set(risk_flags)),
            "metrics": {
                "vsr": round(ohlcv_m["vsr"], 2),
                "vii": round(ohlcv_m["vii"], 2),
                "change_pct": round(ohlcv_m["change_pct"], 2),
                "bodr": order_m.get("bodr", 1.0),
                "bcs": broker_m.get("bcs", 0.0),
            },
            "components": components,
        },
        previous_snapshot=memory_prev,
    )
    if memory.get("flow_reversal_alert"):
        risk_flags.append("BFD_FLOW_REVERSAL")
    if memory.get("weakening_flow"):
        risk_flags.append("BFD_WEAKENING_FLOW")

    warnings = []
    if "RETAIL_EXIT_LIQUIDITY" in risk_flags:
        warnings.append({"level": "HIGH", "type": "RETAIL_EXIT_LIQUIDITY", "message": "Broker kuat distribusi saat retail menampung; hindari jadi exit liquidity."})
    if "CLIMAX_DISTRIBUTION_RISK" in risk_flags:
        warnings.append({"level": "HIGH", "type": "CLIMAX_DISTRIBUTION_RISK", "message": "Volume tinggi tetapi harga tidak maju; potensi distribusi puncak."})
    if phase == "early_flow":
        warnings.append({"level": "LOW", "type": "EARLY_FLOW", "message": "Flow awal terdeteksi; tunggu trigger sesuai mode sebelum entry penuh."})
    if memory.get("flow_reversal_alert"):
        warnings.append({"level": "HIGH", "type": "BFD_FLOW_REVERSAL", "message": "BFD turun dari zona kuat ke <=2; potensi flow reversal, lindungi posisi."})
    for pattern_item in bearish_patterns[:3]:
        warnings.append({"level": "HIGH", "type": pattern_item["name"], "message": pattern_item["reason"]})

    sizing = {
        "swing": "20-30% awal saat BFD >=3, tambah saat breakout/retest valid.",
        "intraday": "Mulai kecil saat trigger intraday valid, tambah hanya jika time table dan momentum tetap mendukung.",
        "scalping": "Eksekusi cepat hanya saat spread sehat, bid refill aktif, dan momentum belum berbalik.",
    }.get(mode_l, "Gunakan scaling bertahap mengikuti validasi flow.")

    return {
        "available": True,
        "ticker": str(ticker or "").upper(),
        "mode": mode_l,
        "score": round(_clamp(score), 2),
        "bfd_score": int(bfd_score),
        "phase": phase,
        "verdict": verdict,
        "entry_label": profile["entry_label"],
        "evidence": evidence,
        "risk_flags": sorted(set(risk_flags)),
        "patterns": patterns,
        "doctrine": doctrine,
        "execution_intelligence": execution,
        "flow_memory": memory,
        "components": components,
        "metrics": {
            "vsr": round(ohlcv_m["vsr"], 2),
            "vii": round(ohlcv_m["vii"], 2),
            "change_pct": round(ohlcv_m["change_pct"], 2),
            "bodr": order_m.get("bodr", 1.0),
            "bcs": broker_m.get("bcs", 0.0),
            "bandar_avg_price": broker_m.get("bandar_avg_price", 0),
            "current_vs_bandar_avg_pct": round(
                ((_num(ohlcv_m.get("close")) - broker_m.get("bandar_avg_price", 0)) / broker_m.get("bandar_avg_price", 1) * 100)
                if broker_m.get("bandar_avg_price", 0) else 0,
                2,
            ),
        },
        "broker": broker_m,
        "orderbook": order_m,
        "official": official_m,
        "sizing_plan": sizing,
        "warnings": warnings,
        "policy": "money_maker_first_uses_35_engines_plus_kb_as_evidence",
    }


def apply_money_maker_to_action_plan(action_plan: Dict[str, Any], money_maker: Dict[str, Any]) -> Dict[str, Any]:
    action = dict(action_plan or {})
    mm = money_maker or {}
    if not mm.get("available"):
        action["money_maker_context"] = {"available": False}
        return action

    confirmations = list(action.get("confirmation_needed") or [])
    invalidations = list(action.get("invalidation_rules") or [])
    phase = mm.get("phase")
    verdict = mm.get("verdict")
    base_decision = str(action.get("decision") or "").upper()

    action["money_maker_context"] = {
        "available": True,
        "score": mm.get("score"),
        "bfd_score": mm.get("bfd_score"),
        "phase": phase,
        "verdict": verdict,
        "risk_flags": mm.get("risk_flags", []),
        "patterns": [p.get("name") for p in mm.get("patterns", [])[:5] if isinstance(p, dict)],
        "doctrine_flags": (mm.get("doctrine") or {}).get("flags", []),
        "execution_stance": (mm.get("execution_intelligence") or {}).get("stance"),
        "policy": mm.get("policy"),
    }
    action["money_maker_score"] = mm.get("score")
    action["bfd_score"] = mm.get("bfd_score")
    action["flow_phase"] = phase

    execution = mm.get("execution_intelligence") or {}
    doctrine = mm.get("doctrine") or {}
    if verdict == "FLOW_OUT_AVOID" or execution.get("stance") == "NO_LONG_ENTRY":
        action["decision"] = "NO GO"
        action["order_type"] = "NO_LONG_ENTRY"
        action["setup_type"] = "NO_LONG_ENTRY"
        action["decision_modifier"] = "MONEY_MAKER_FLOW_OUT"
        action["next_action"] = "Money Maker Core membaca distribusi/flow out; jangan entry long sampai flow balik akumulasi."
        invalidations.append("Broker kuat tetap net sell atau BFD <=2.")
    elif verdict in ("STRONG_FLOW_IN", "EARLY_FLOW") and base_decision in ("GO", "STRONG GO"):
        action["decision_modifier"] = f"{verdict}_CONFIRMED"
        confirmations.append("BFD tetap >=4 saat trigger dieksekusi.")
        confirmations.append("Broker kuat tetap dominan net buy, bukan berbalik distribusi.")
    elif verdict in ("STRONG_FLOW_IN", "EARLY_FLOW") and base_decision in ("WAIT", "NEUTRAL", ""):
        action["decision_modifier"] = f"{verdict}_WAIT_TECHNICAL_TRIGGER"
        action["requires_money_maker_confirmation"] = True
        confirmations.append("Tunggu technical trigger/retest valid agar tidak masuk terlalu dini.")
    elif verdict == "NO_CLEAR_FLOW" and base_decision in ("GO", "STRONG GO"):
        action["decision_modifier"] = "GO_WITH_WEAK_FLOW_CONTEXT"
        action["requires_money_maker_confirmation"] = True
        confirmations.append("Money maker flow belum jelas; tunggu minimal BFD >=3.")

    if mm.get("sizing_plan"):
        action["scaling_plan"] = mm["sizing_plan"]
    if execution.get("preferred_order") and action.get("order_type") not in ("NO_LONG_ENTRY", "NO_MARKET_ENTRY"):
        action["money_maker_preferred_order"] = execution["preferred_order"]
    if execution.get("reason"):
        confirmations.append(execution["reason"])
    for rule in doctrine.get("rules") or []:
        confirmations.append(rule)
    for flag in mm.get("risk_flags") or []:
        invalidations.append(f"Money maker risk flag aktif: {flag}")

    action["confirmation_needed"] = list(dict.fromkeys(confirmations))
    action["invalidation_rules"] = list(dict.fromkeys(invalidations))
    return action
