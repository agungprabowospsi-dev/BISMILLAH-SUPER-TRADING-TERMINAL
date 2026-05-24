import unittest

from app.engines.orderbook_microstructure import build_orderbook_execution_overlay, normalize_orderbook


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


if __name__ == "__main__":
    unittest.main()
