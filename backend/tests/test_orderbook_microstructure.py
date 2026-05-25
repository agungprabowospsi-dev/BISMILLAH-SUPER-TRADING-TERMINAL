import unittest
import os

os.environ.setdefault("INVESGO_API_KEY", "test")

from app.engines.orderbook_microstructure import build_orderbook_execution_overlay, normalize_orderbook
from app.core.official_enrichment import apply_official_enrichment_to_action_plan
from app.core.money_maker import _FLOW_MEMORY, analyze_money_maker_context, apply_money_maker_to_action_plan


class OrderbookMicrostructureTest(unittest.TestCase):
    def test_top10_rows_generate_limit_overlay_without_overriding_decision(self):
        raw = {
            "levels": [
                {"bid": 6475, "bid_lot": 35, "bid_freq": 4, "ask": 6500, "ask_lot": 39, "ask_freq": 3},
                {"bid": 6450, "bid_lot": 247, "bid_freq": 26, "ask": 6525, "ask_lot": 29, "ask_freq": 7},
                {"bid": 6425, "bid_lot": 52, "bid_freq": 10, "ask": 6550, "ask_lot": 41, "ask_freq": 2},
                {"bid": 6400, "bid_lot": 322, "bid_freq": 46, "ask": 6575, "ask_lot": 3, "ask_freq": 2},
            ]
        }

        normalized = normalize_orderbook(raw)
        overlay = build_orderbook_execution_overlay(raw, {"order_type": "LIMIT_PULLBACK"}, "intraday")

        self.assertTrue(normalized["available"])
        self.assertEqual(normalized["best_bid"], 6475)
        self.assertEqual(normalized["best_ask"], 6500)
        self.assertEqual(overlay["overlay_policy"], "additive_only_no_decision_override")
        self.assertEqual(overlay["liquidity_bias"], "bid_dominant")
        self.assertEqual(overlay["execution_recommendation"], "GO_LIMIT_PULLBACK")
        self.assertEqual(overlay["suggested_limit_entry"], 6475)

    def test_official_orderbook_keys_are_normalized(self):
        raw = {
            "bid1price": 6475,
            "bid1lot": 35,
            "bid1freq": 4,
            "offer1price": 6500,
            "offer1lot": 39,
            "offer1freq": 3,
            "source": "official_order_book",
        }

        normalized = normalize_orderbook(raw)

        self.assertTrue(normalized["available"])
        self.assertEqual(normalized["best_bid"], 6475)
        self.assertEqual(normalized["best_ask"], 6500)
        self.assertEqual(normalized["source"], "official_order_book")

    def test_official_enrichment_adds_decision_guardrails_without_override(self):
        action = {
            "decision": "GO",
            "confirmation_needed": ["RVOL >= 1.3"],
            "invalidation_rules": ["Close below support"],
            "next_action": "Wait for trigger.",
        }
        enrichment = {
            "available": True,
            "time_table": {"pressure": "sell_pressure"},
            "momentum_chart": {"bias": "sell_momentum"},
            "broker_stalker": {"available_count": 1},
            "corporate_actions": {"count": 1},
            "warnings": [{"level": "MEDIUM", "type": "MOMENTUM_SELL_BIAS"}],
        }

        guarded = apply_official_enrichment_to_action_plan(action, enrichment)

        self.assertEqual(guarded["decision"], "GO")
        self.assertTrue(guarded["requires_official_confirmation"])
        self.assertEqual(guarded["decision_modifier"], "CONDITIONAL_GO_OFFICIAL_CONFIRMATION_REQUIRED")
        self.assertIn("MOMENTUM_SELL_BIAS", guarded["official_decision_context"]["risk_flags"])
        self.assertGreater(len(guarded["confirmation_needed"]), 1)

    def test_money_maker_flow_out_overrides_bullish_long_plan(self):
        ohlcv = [
            {"open": 100, "high": 103, "low": 99, "close": 101, "volume": 1_000_000},
            {"open": 101, "high": 104, "low": 100, "close": 102, "volume": 1_100_000},
            {"open": 102, "high": 104, "low": 101, "close": 102, "volume": 2_400_000},
        ]
        broker_summary = [
            {"code": "BK", "buy_value": 1_000_000_000, "sell_value": 6_000_000_000, "net_value": -5_000_000_000},
            {"code": "PD", "buy_value": 3_000_000_000, "sell_value": 500_000_000, "net_value": 2_500_000_000},
        ]

        money_maker = analyze_money_maker_context(
            ticker="TEST",
            mode="swing",
            ohlcv=ohlcv,
            engine_result={"composite_score": 72},
            broker_summary=broker_summary,
            official_enrichment={"available": True, "time_table": {"pressure": "sell_pressure"}, "momentum_chart": {"bias": "sell_momentum"}},
        )
        action = apply_money_maker_to_action_plan({"decision": "GO", "order_type": "MARKET_ORDER"}, money_maker)

        self.assertEqual(money_maker["verdict"], "FLOW_OUT_AVOID")
        self.assertEqual(action["decision"], "NO GO")
        self.assertEqual(action["order_type"], "NO_LONG_ENTRY")

    def test_money_maker_detects_hidden_accumulation_and_retail_absorption(self):
        ohlcv = [
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1_000_000},
            {"open": 101, "high": 102, "low": 100, "close": 101, "volume": 1_050_000},
            {"open": 101, "high": 102, "low": 100, "close": 102, "volume": 2_000_000},
        ]
        broker_summary = [
            {"code": "BK", "buy_value": 6_000_000_000, "sell_value": 1_000_000_000, "net_value": 5_000_000_000},
            {"code": "PD", "buy_value": 500_000_000, "sell_value": 3_000_000_000, "net_value": -2_500_000_000},
        ]

        money_maker = analyze_money_maker_context(
            ticker="ACCU",
            mode="swing",
            ohlcv=ohlcv,
            engine_result={"composite_score": 62},
            broker_summary=broker_summary,
        )
        names = {p["name"] for p in money_maker["patterns"]}

        self.assertIn("HIDDEN_ACCUMULATION", names)
        self.assertIn("RETAIL_DUMP_ABSORPTION", names)
        self.assertGreaterEqual(money_maker["bfd_score"], 3)

    def test_money_maker_memory_detects_bfd_reversal(self):
        strong = analyze_money_maker_context(
            ticker="MEMX",
            mode="intraday",
            ohlcv=[
                {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1_000_000},
                {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 2_200_000},
            ],
            engine_result={"composite_score": 70},
            broker_summary=[{"code": "BK", "buy_value": 7_000_000_000, "sell_value": 1_000_000_000, "net_value": 6_000_000_000}],
            orderbook={"bid_price": 100, "bid_lot": 2500, "offer_price": 101, "offer_lot": 1000},
            official_enrichment={"available": True, "time_table": {"pressure": "buy_pressure"}, "momentum_chart": {"bias": "buy_momentum"}},
        )
        weak = analyze_money_maker_context(
            ticker="MEMX",
            mode="intraday",
            ohlcv=[
                {"open": 102, "high": 103, "low": 100, "close": 101, "volume": 1_000_000},
                {"open": 101, "high": 101, "low": 98, "close": 99, "volume": 2_500_000},
            ],
            engine_result={"composite_score": 68},
            broker_summary=[{"code": "BK", "buy_value": 500_000_000, "sell_value": 6_000_000_000, "net_value": -5_500_000_000}],
            official_enrichment={"available": True, "time_table": {"pressure": "sell_pressure"}, "momentum_chart": {"bias": "sell_momentum"}},
        )

        self.assertGreaterEqual(strong["bfd_score"], 4)
        self.assertTrue(weak["flow_memory"]["flow_reversal_alert"])
        self.assertIn("BFD_FLOW_REVERSAL", weak["risk_flags"])

    def test_money_maker_memory_persists_after_runtime_memory_clear(self):
        ticker = "PERS"
        first = analyze_money_maker_context(
            ticker=ticker,
            mode="swing",
            ohlcv=[
                {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1_000_000},
                {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 2_200_000},
            ],
            engine_result={"composite_score": 70},
            broker_summary=[{"code": "BK", "buy_value": 7_000_000_000, "sell_value": 1_000_000_000, "net_value": 6_000_000_000}],
            orderbook={"bid_price": 100, "bid_lot": 2500, "offer_price": 101, "offer_lot": 1000},
            official_enrichment={"available": True, "time_table": {"pressure": "buy_pressure"}, "momentum_chart": {"bias": "buy_momentum"}},
        )
        _FLOW_MEMORY.clear()
        second = analyze_money_maker_context(
            ticker=ticker,
            mode="swing",
            ohlcv=[
                {"open": 101, "high": 102, "low": 100, "close": 101, "volume": 1_000_000},
                {"open": 101, "high": 101, "low": 98, "close": 99, "volume": 2_500_000},
            ],
            engine_result={"composite_score": 68},
            broker_summary=[{"code": "BK", "buy_value": 500_000_000, "sell_value": 6_000_000_000, "net_value": -5_500_000_000}],
            official_enrichment={"available": True, "time_table": {"pressure": "sell_pressure"}, "momentum_chart": {"bias": "sell_momentum"}},
        )

        self.assertTrue(first["flow_memory"]["persistent_saved"])
        self.assertEqual(second["flow_memory"]["prev_bfd_score"], first["bfd_score"])
        self.assertIn(second["flow_memory"]["memory_source"], ("runtime+sqlite", "sqlite"))


if __name__ == "__main__":
    unittest.main()
