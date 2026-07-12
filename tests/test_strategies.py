import unittest

from forexbot.strategies import FLAT, LONG, SHORT, build_strategy
from forexbot.strategies.rsi_mean_reversion import RsiMeanReversion
from forexbot.strategies.sma_crossover import SmaCrossover
from tests.helpers import candles_from_closes, trend


class TestSmaCrossover(unittest.TestCase):
    def test_long_in_uptrend(self):
        candles = candles_from_closes(trend(1.0, 0.001, 80))
        strategy = SmaCrossover(fast=5, slow=20)
        self.assertEqual(strategy.target_position(candles), LONG)

    def test_short_in_downtrend(self):
        candles = candles_from_closes(trend(1.2, -0.001, 80))
        strategy = SmaCrossover(fast=5, slow=20)
        self.assertEqual(strategy.target_position(candles), SHORT)

    def test_flat_without_enough_history(self):
        candles = candles_from_closes(trend(1.0, 0.001, 10))
        strategy = SmaCrossover(fast=5, slow=20)
        self.assertEqual(strategy.target_position(candles), FLAT)

    def test_rejects_fast_ge_slow(self):
        with self.assertRaises(ValueError):
            SmaCrossover(fast=50, slow=20)


class TestRsiMeanReversion(unittest.TestCase):
    def test_goes_long_after_selloff_and_exits_at_neutral(self):
        strategy = RsiMeanReversion(period=5, oversold=30, overbought=70, exit_level=50)
        # steady decline -> RSI collapses -> expect LONG
        closes = trend(1.10, -0.0015, 40)
        candles = candles_from_closes(closes)
        self.assertEqual(strategy.target_position(candles), LONG)

        # strong recovery -> RSI back above exit level -> expect FLAT
        closes += trend(closes[-1], 0.0020, 30)
        candles = candles_from_closes(closes)
        self.assertEqual(strategy.target_position(candles), FLAT)

    def test_goes_short_after_rally(self):
        strategy = RsiMeanReversion(period=5)
        candles = candles_from_closes(trend(1.10, 0.0015, 40))
        self.assertEqual(strategy.target_position(candles), SHORT)

    def test_reset_clears_state(self):
        strategy = RsiMeanReversion(period=5)
        candles = candles_from_closes(trend(1.10, 0.0015, 40))
        strategy.target_position(candles)
        strategy.reset()
        self.assertEqual(strategy._stance, FLAT)

    def test_rejects_bad_thresholds(self):
        with self.assertRaises(ValueError):
            RsiMeanReversion(oversold=80, overbought=70)


class TestFactory(unittest.TestCase):
    def test_builds_by_name_with_params(self):
        strategy = build_strategy("sma_crossover", {"fast": 7, "slow": 21})
        self.assertEqual(strategy.fast, 7)
        self.assertEqual(strategy.slow, 21)

    def test_unknown_name(self):
        with self.assertRaises(ValueError):
            build_strategy("does_not_exist")


if __name__ == "__main__":
    unittest.main()
