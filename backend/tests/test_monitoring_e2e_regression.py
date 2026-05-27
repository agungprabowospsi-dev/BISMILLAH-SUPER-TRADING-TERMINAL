import os
import unittest

os.environ.setdefault("INVESGO_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import monitoring


async def fake_get_tick(ticker):
    return {"last_price": 101.0}


async def fake_engine_context(ticker, mode="swing"):
    return {
        "engines_used": True,
        "engine_scope": "monitoring_bridge",
        "total_engines": 8,
        "composite_score": 62.0,
        "signal": "bullish",
        "bullish_count": 3,
        "bearish_count": 1,
        "rag_used": True,
        "rag_context_count": 2,
        "bandarmology_included": True,
        "broker_behavior_included": True,
        "orderbook_included": True,
        "orderbook_execution": {
            "available": True,
            "execution_recommendation": "GO_LIMIT_PULLBACK",
            "overlay_policy": "additive_only_no_decision_override",
        },
        "engine_details": {
            "BrokerBehaviorEngine": {
                "engine": "BrokerBehaviorEngine",
                "score": 70,
                "signal": "bullish",
                "data": {"pressure": "accumulation", "smart_money_net_bil": 2.0},
            }
        },
    }


class MonitoringE2ERegressionTest(unittest.TestCase):
    def setUp(self):
        monitoring._active_monitors.clear()
        monitoring.invesgo.get_tick = fake_get_tick
        monitoring.get_monitoring_engine_context = fake_engine_context
        self.app = FastAPI()
        self.app.include_router(monitoring.router, prefix="/api/monitoring")
        self.client = TestClient(self.app)

    def test_unified_monitoring_contract_roundtrip(self):
        payload = {
            "ticker": "bbca",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "take_profit_1": 110,
            "mode": "intraday",
            "lot": 2,
            "broker": "Unit Test",
            "engine_scores": [{"engine": "BrokerBehaviorEngine", "score": 70}],
            "analytic_context": {
                "go_no_go": "WAIT",
                "action_plan": {
                    "order_type": "WAIT_CLOSE_CONFIRMATION",
                    "trigger_price": 105,
                    "invalidation_price": 95,
                },
                "orderbook_execution": {
                    "execution_recommendation": "GO_LIMIT_PULLBACK",
                    "overlay_policy": "additive_only_no_decision_override",
                },
            },
        }

        started = self.client.post("/api/monitoring/start", json=payload)
        self.assertEqual(started.status_code, 200, started.text)
        body = started.json()
        monitoring_id = body["monitoring_id"]
        self.assertEqual(body["position"]["ticker"], "BBCA")
        self.assertEqual(body["position"]["engine_scores"], {"BrokerBehaviorEngine": 70.0})

        active = self.client.get("/api/monitoring/active")
        self.assertEqual(active.status_code, 200, active.text)
        self.assertEqual(active.json()["count"], 1)
        self.assertEqual(active.json()["monitors"][0]["monitoring_id"], monitoring_id)

        checked = self.client.post("/api/monitoring/check", json=payload)
        self.assertEqual(checked.status_code, 200, checked.text)
        checked_body = checked.json()
        self.assertTrue(checked_body["engine_context"]["broker_behavior_included"])
        self.assertTrue(checked_body["engine_context"]["orderbook_included"])
        self.assertEqual(checked_body["position_guard"]["state"], "POSITION_ACTIVE")
        self.assertTrue(checked_body["position_guard"]["post_buy_only"])
        self.assertIn("tp1_confidence", checked_body["tp_sl_confidence"])
        self.assertIn("sl_risk_confidence", checked_body["tp_sl_confidence"])
        self.assertEqual(
            checked_body["tp_sl_confidence"]["scope"],
            "post_buy_position_guardian",
        )
        self.assertEqual(
            checked_body["engine_context"]["orderbook_execution"]["overlay_policy"],
            "additive_only_no_decision_override",
        )
        self.assertTrue(any(w.get("type") == "ANALYTIC_DECISION_CONTEXT" for w in checked_body["warnings"]))

        status = self.client.get(f"/api/monitoring/status/{monitoring_id}")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["monitoring_id"], monitoring_id)

        removed = self.client.post("/api/monitoring/remove", json={"monitoring_id": monitoring_id})
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["removed"], 1)


if __name__ == "__main__":
    unittest.main()
