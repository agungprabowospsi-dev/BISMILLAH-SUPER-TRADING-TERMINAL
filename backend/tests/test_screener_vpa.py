import os
import unittest

os.environ.setdefault("INVESGO_API_KEY", "test")

from app.api.screener import analyze_vpa_variables, calc_bfd_presort_score, calc_prefilter_metrics


def candle(open_, high, low, close, volume=1_000_000, date="2026-05-01"):
    return {
        "date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class ScreenerVPATest(unittest.TestCase):
    def base_candles(self):
        return [
            candle(100, 103, 99, 101, date=f"2026-04-{i:02d}")
            for i in range(1, 21)
        ]

    def test_bullish_effort_lifts_vpa_and_presort_score(self):
        ohlcv = self.base_candles()
        ohlcv.append(candle(101, 109, 100, 108, 1_600_000, "2026-05-01"))

        metrics = calc_prefilter_metrics(ohlcv)
        self.assertEqual(metrics["vpa_state"], "VPA_CONFIRMED")
        self.assertIn("BULLISH_EFFORT_CONFIRMED", metrics["vpa_signals"])
        self.assertFalse(metrics["vpa_distribution_risk"])

        base = {
            "rvol": metrics["rvol"],
            "change_pct": metrics["change_pct"],
            "price": metrics["price"],
            "value": metrics["value"],
            "ma5": metrics["ma5"],
            "ma20": metrics["ma20"],
            "candle_bullish": metrics["candle_bullish"],
            "candle_body_pct": metrics["candle_body_pct"],
        }
        with_vpa = calc_bfd_presort_score({**base, "vpa": metrics["vpa"]}, "intraday")
        without_vpa = calc_bfd_presort_score({**base, "vpa": {"score": 50, "signals": []}}, "intraday")
        self.assertGreater(with_vpa, without_vpa)

    def test_upthrust_marks_distribution_risk_without_separate_filter(self):
        ohlcv = self.base_candles()
        ohlcv[-1] = candle(101, 106, 100, 105, 1_000_000, "2026-04-20")
        ohlcv.append(candle(105, 112, 104, 106, 1_600_000, "2026-05-01"))

        vpa = analyze_vpa_variables(ohlcv, rvol=1.6, change_pct=0.95)

        self.assertEqual(vpa["state"], "VPA_DISTRIBUTION_RISK")
        self.assertIn("UPTHRUST", vpa["signals"])
        self.assertTrue(vpa["distribution_risk"])

    def test_no_demand_is_scored_as_warning(self):
        ohlcv = self.base_candles()
        ohlcv[-1] = candle(100, 103, 99, 100, 1_000_000, "2026-04-20")
        ohlcv.append(candle(100, 102, 99, 101, 500_000, "2026-05-01"))

        vpa = analyze_vpa_variables(ohlcv, rvol=0.5, change_pct=1.0)

        self.assertIn("NO_DEMAND", vpa["signals"])
        self.assertLess(vpa["score"], 50)


if __name__ == "__main__":
    unittest.main()
