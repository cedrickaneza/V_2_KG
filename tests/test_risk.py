import unittest
from datetime import datetime, timedelta, timezone

from forexbot.risk.manager import RiskConfig, RiskManager
from tests.helpers import candles_from_closes

NOW = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


class TestPositionSizing(unittest.TestCase):
    def test_size_matches_risk_amount(self):
        risk = RiskManager(RiskConfig(risk_per_trade=0.01))
        # equity 10_000, risking 1% = 100; stop 0.0050 away -> 20_000 units
        self.assertEqual(risk.position_size(10_000, 0.0050), 20_000)

    def test_size_capped_at_max_units(self):
        risk = RiskManager(RiskConfig(risk_per_trade=0.02, max_units=50_000))
        self.assertEqual(risk.position_size(1_000_000, 0.0001), 50_000)

    def test_zero_for_degenerate_inputs(self):
        risk = RiskManager()
        self.assertEqual(risk.position_size(10_000, 0.0), 0)
        self.assertEqual(risk.position_size(0.0, 0.001), 0)

    def test_fractional_sizing_for_crypto_scale_prices(self):
        # equity 10_000, risking 0.5% = 50; stop $500 away (BTC-scale) -> 0.1 units.
        # int()-truncating sizing would silently round this to 0 and never trade.
        risk = RiskManager(RiskConfig(risk_per_trade=0.005, max_units=10))
        units = risk.position_size(10_000, 500)
        self.assertAlmostEqual(units, 0.1)
        self.assertGreater(units, 0)

    def test_notional_cap_scales_with_price(self):
        """A tight stop on a cheap coin must not buy a huge position: the
        position's VALUE is capped at max_position_pct of equity."""
        risk = RiskManager(RiskConfig(risk_per_trade=0.005, max_position_pct=0.25))
        # risk $50, stop only $2 away -> raw sizing wants 25 coins;
        # at $100/coin that's $2,500 = 25% of a $10k account -> exactly at cap
        self.assertAlmostEqual(risk.position_size(10_000, 2.0, price=100.0), 25.0)
        # halve the stop -> raw sizing wants 50 coins ($5,000) -> capped to 25
        self.assertAlmostEqual(risk.position_size(10_000, 1.0, price=100.0), 25.0)

    def test_notional_cap_ignored_without_price(self):
        risk = RiskManager(RiskConfig(risk_per_trade=0.005, max_position_pct=0.25))
        self.assertAlmostEqual(risk.position_size(10_000, 1.0), 50.0)

    def test_config_rejects_bad_position_pct(self):
        with self.assertRaises(ValueError):
            RiskConfig(max_position_pct=0.0)
        with self.assertRaises(ValueError):
            RiskConfig(max_position_pct=1.5)

    def test_config_rejects_reckless_risk(self):
        with self.assertRaises(ValueError):
            RiskConfig(risk_per_trade=0.10)  # 10% per trade — never


class TestStopDistance(unittest.TestCase):
    def test_uses_atr_multiple(self):
        risk = RiskManager(RiskConfig(atr_period=5, atr_stop_multiplier=2.0))
        candles = candles_from_closes([1.0, 1.01, 1.0, 1.02, 1.01, 1.03, 1.02, 1.04])
        dist = risk.stop_distance(candles)
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 0)

    def test_none_without_enough_candles(self):
        risk = RiskManager(RiskConfig(atr_period=14))
        candles = candles_from_closes([1.0, 1.01, 1.02])
        self.assertIsNone(risk.stop_distance(candles))


class TestDailyLossLimit(unittest.TestCase):
    def test_blocks_after_daily_loss(self):
        risk = RiskManager(RiskConfig(max_daily_loss_pct=0.02))
        risk.update(NOW, 10_000)
        allowed, _ = risk.can_open_trade(10_000)
        self.assertTrue(allowed)

        risk.update(NOW + timedelta(hours=1), 9_700)  # -3% intraday
        allowed, reason = risk.can_open_trade(9_700)
        self.assertFalse(allowed)
        self.assertIn("daily loss", reason)

    def test_resets_next_day(self):
        risk = RiskManager(RiskConfig(max_daily_loss_pct=0.02))
        risk.update(NOW, 10_000)
        risk.update(NOW + timedelta(hours=1), 9_700)
        risk.update(NOW + timedelta(days=1), 9_700)  # new day, new baseline
        allowed, _ = risk.can_open_trade(9_700)
        self.assertTrue(allowed)


class TestKillSwitch(unittest.TestCase):
    def test_halts_on_max_drawdown_and_latches(self):
        risk = RiskManager(RiskConfig(max_drawdown_pct=0.10))
        risk.update(NOW, 10_000)
        risk.update(NOW + timedelta(hours=1), 8_900)  # -11% from peak
        self.assertTrue(risk.halted)
        allowed, reason = risk.can_open_trade(8_900)
        self.assertFalse(allowed)
        self.assertIn("kill switch", reason)

        # recovery does NOT un-halt: a human must investigate first
        risk.update(NOW + timedelta(hours=2), 9_950)
        self.assertTrue(risk.halted)


if __name__ == "__main__":
    unittest.main()
