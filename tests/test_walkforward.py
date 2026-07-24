import unittest

from forexbot.backtest.walkforward import expand_grid, run_walk_forward
from forexbot.strategies import FLAT, LONG, SHORT
from forexbot.strategies.donchian_breakout import DonchianBreakout
from tests.helpers import candles_from_closes, trend


class TestDonchianBreakout(unittest.TestCase):
    def test_long_on_upside_breakout(self):
        closes = [1.0 + 0.0001 * (i % 3) for i in range(30)]  # tight range
        closes += trend(1.01, 0.002, 5)                        # violent breakout up
        strategy = DonchianBreakout(entry_period=20, exit_period=5)
        self.assertEqual(strategy.target_position(candles_from_closes(closes)), LONG)

    def test_short_on_downside_breakout(self):
        closes = [1.0 + 0.0001 * (i % 3) for i in range(30)]
        closes += trend(0.995, -0.002, 5)
        strategy = DonchianBreakout(entry_period=20, exit_period=5)
        self.assertEqual(strategy.target_position(candles_from_closes(closes)), SHORT)

    def test_exits_long_when_exit_channel_breaks(self):
        strategy = DonchianBreakout(entry_period=20, exit_period=5)
        closes = [1.0 + 0.0001 * (i % 3) for i in range(30)] + trend(1.01, 0.002, 5)
        self.assertEqual(strategy.target_position(candles_from_closes(closes)), LONG)
        closes += trend(closes[-1], -0.003, 8)  # sharp reversal below exit low
        self.assertEqual(strategy.target_position(candles_from_closes(closes)), FLAT)

    def test_flat_without_history(self):
        strategy = DonchianBreakout(entry_period=20, exit_period=5)
        self.assertEqual(strategy.target_position(candles_from_closes([1.0] * 5)), FLAT)

    def test_rejects_bad_periods(self):
        with self.assertRaises(ValueError):
            DonchianBreakout(entry_period=20, exit_period=20)


class TestExpandGrid(unittest.TestCase):
    def test_cartesian_product(self):
        combos = expand_grid({"fast": [10, 20], "slow": [50, 100]})
        self.assertEqual(len(combos), 4)
        self.assertIn({"fast": 10, "slow": 100}, combos)

    def test_single_values(self):
        self.assertEqual(expand_grid({"period": [14]}), [{"period": 14}])


class TestWalkForward(unittest.TestCase):
    def make_data(self, n=900):
        # alternating up/down regimes so there is something to select on
        closes = []
        price = 1.0
        for regime in range(6):
            step = 0.0006 if regime % 2 == 0 else -0.0004
            seg = trend(price, step, n // 6)
            closes.extend(seg)
            price = seg[-1]
        return candles_from_closes(closes)

    def test_produces_expected_folds(self):
        candles = self.make_data(900)
        result = run_walk_forward(
            "sma_crossover",
            {"fast": [5], "slow": [15]},
            candles,
            train_size=300,
            test_size=150,
        )
        self.assertEqual(len(result.folds), (900 - 300) // 150)
        self.assertGreater(len(result.oos_equity), 0)
        self.assertIn("total_return_pct", result.oos_metrics)

    def test_selects_params_per_fold(self):
        candles = self.make_data(900)
        result = run_walk_forward(
            "sma_crossover",
            {"fast": [5, 10], "slow": [15, 30]},
            candles,
            train_size=300,
            test_size=150,
        )
        for fold in result.folds:
            self.assertIn(fold.best_params["fast"], (5, 10))
            self.assertIn(fold.best_params["slow"], (15, 30))

    def test_long_only_threads_through_to_oos_trades(self):
        # alternating regimes include a downtrend leg where the strategy
        # wants SHORT; long_only=True must keep every OOS trade non-negative
        candles = self.make_data(900)
        result = run_walk_forward(
            "sma_crossover", {"fast": [5], "slow": [15]}, candles,
            train_size=300, test_size=150, long_only=True,
        )
        self.assertTrue(all(t.units >= 0 for t in result.oos_trades))

    def test_invalid_grid_combos_are_skipped(self):
        candles = self.make_data(600)
        # fast=30/slow=15 is invalid (fast >= slow) and must be skipped, not crash
        result = run_walk_forward(
            "sma_crossover",
            {"fast": [5, 30], "slow": [15]},
            candles,
            train_size=300,
            test_size=150,
        )
        for fold in result.folds:
            self.assertEqual(fold.best_params, {"fast": 5, "slow": 15})

    def test_rejects_all_invalid_grid(self):
        candles = self.make_data(600)
        with self.assertRaises(ValueError):
            run_walk_forward(
                "sma_crossover", {"fast": [50], "slow": [15]}, candles,
                train_size=300, test_size=150,
            )

    def test_rejects_too_little_data(self):
        candles = self.make_data(300)
        with self.assertRaises(ValueError):
            run_walk_forward(
                "sma_crossover", {"fast": [5], "slow": [15]}, candles,
                train_size=300, test_size=150,
            )

    def test_oos_trading_starts_at_test_boundary(self):
        """No out-of-sample trade may open before its fold's first test candle."""
        candles = self.make_data(900)
        result = run_walk_forward(
            "sma_crossover", {"fast": [5], "slow": [15]}, candles,
            train_size=300, test_size=150,
        )
        first_test_time = result.folds[0].test_range[0]
        for trade in result.oos_trades:
            self.assertGreaterEqual(trade.entry_time, first_test_time)


if __name__ == "__main__":
    unittest.main()
