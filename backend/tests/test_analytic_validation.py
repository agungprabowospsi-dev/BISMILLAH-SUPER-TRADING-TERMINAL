import os
import unittest

os.environ.setdefault("INVESGO_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.api.analytic import (
    ScreenerContext,
    apply_analytic_validation_to_action_plan,
    build_analytic_validation_matrix,
)


def sample_candles():
    rows = []
    for idx in range(1, 22):
        rows.append({
            "date": f"2026-05-{idx:02d}",
            "open": 100,
            "high": 104,
            "low": 99,
            "close": 102,
            "volume": 1_000_000,
        })
    rows[-1] = {"date": "2026-05-22", "open": 102, "high": 110, "low": 101, "close": 109, "volume": 1_600_000}
    return rows


class AnalyticValidationMatrixTest(unittest.TestCase):
    def base_kwargs(self):
        return {
            "market_execution_regime": "NORMAL_GREEN_MARKET",
            "screener_context": ScreenerContext(
                grade="A",
                score=78,
                screener_lane="EXECUTION_CANDIDATE",
                vpa={"score": 76, "state": "VPA_CONFIRMED", "signals": ["BULLISH_EFFORT_CONFIRMED"], "distribution_risk": False},
            ),
            "action_plan": {
                "order_type": "BUY_STOP_BREAKOUT",
                "entry_price": 110,
                "trigger_price": 110,
                "stop_loss": 106,
                "take_profit_1": 116,
                "take_profit_2": 122,
                "take_profit_3": 130,
            },
            "all_engines": {"composite_score": 72, "total_engines": 35, "bullish_count": 7, "bearish_count": 2, "signal": "BUY"},
            "enrichment_verdict": "PROCEED",
            "phase2_verdict": "BUY",
            "wyckoff_phase": "MARKUP",
            "weinstein_stage": 2,
            "vsa_signal": "NO_SUPPLY",
            "money_maker": {"verdict": "STRONG_FLOW_IN", "bfd_score": 4, "risk_flags": [], "score": 78, "phase": "strong_flow_in"},
            "orderbook_execution": {"available": True, "spread_health": "healthy", "liquidity_bias": "bid_dominant", "execution_recommendation": "GO_LIMIT_PULLBACK", "bid_ask_ratio": 1.4},
            "ohlcv": sample_candles(),
            "rvol": 1.6,
            "change_pct": 6.8,
            "mode": "intraday",
        }

    def test_green_market_full_stack_can_be_executable(self):
        validation = build_analytic_validation_matrix(**self.base_kwargs())

        self.assertEqual(validation["final_status"], "EXECUTABLE")
        self.assertEqual(validation["user_position"], "EXECUTABLE BUY")
        self.assertIn("34/35 Engines Baseline", [row["name"] for row in validation["matrix"]])
        self.assertIn("Bandarmology / Money Maker", [row["name"] for row in validation["matrix"]])
        self.assertIn("Orderbook Microstructure", [row["name"] for row in validation["matrix"]])

    def test_bad_market_top_gainer_becomes_conditional(self):
        kwargs = self.base_kwargs()
        kwargs["market_execution_regime"] = "BAD_MARKET_OPPORTUNITY_ONLY"
        kwargs["screener_context"] = ScreenerContext(
            grade="B",
            score=62,
            screener_lane="TOP_GAINER_OPPORTUNITY",
            top_gainer_opportunity={"available": True, "change_pct": 6.8},
            vpa={"score": 70, "state": "VPA_CONFIRMED", "signals": ["HEALTHY_ADVANCE"], "distribution_risk": False},
        )

        validation = build_analytic_validation_matrix(**kwargs)

        self.assertEqual(validation["final_status"], "CONDITIONAL")
        self.assertEqual(validation["user_position"], "WAIT TRIGGER")

    def test_flow_out_hard_blocks_long_entry(self):
        kwargs = self.base_kwargs()
        kwargs["money_maker"] = {"verdict": "FLOW_OUT_AVOID", "bfd_score": 1, "risk_flags": ["RETAIL_EXIT_LIQUIDITY"], "score": 25}

        validation = build_analytic_validation_matrix(**kwargs)
        action = apply_analytic_validation_to_action_plan(kwargs["action_plan"], validation)

        self.assertEqual(validation["final_status"], "REJECTED")
        self.assertEqual(action["order_type"], "NO_LONG_ENTRY")
        self.assertEqual(action["decision_modifier"], "ANALYTIC_VALIDATION_HARD_BLOCK")


if __name__ == "__main__":
    unittest.main()
