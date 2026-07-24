import unittest

from forexbot.indicators import atr, ema, rsi, sma
from tests.helpers import candles_from_closes


class TestSma(unittest.TestCase):
    def test_values(self):
        result = sma([1, 2, 3, 4, 5], 3)
        self.assertEqual(result[:2], [None, None])
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)
        self.assertAlmostEqual(result[4], 4.0)

    def test_output_length_matches_input(self):
        self.assertEqual(len(sma([1.0] * 10, 4)), 10)

    def test_short_input(self):
        self.assertEqual(sma([1, 2], 5), [None, None])


class TestEma(unittest.TestCase):
    def test_seeded_with_sma(self):
        result = ema([2, 4, 6, 8], 2)
        self.assertIsNone(result[0])
        self.assertAlmostEqual(result[1], 3.0)  # sma of first 2

    def test_converges_to_constant(self):
        result = ema([5.0] * 50, 10)
        self.assertAlmostEqual(result[-1], 5.0)


class TestRsi(unittest.TestCase):
    def test_all_gains_is_100(self):
        values = list(range(1, 31))
        result = rsi(values, 14)
        self.assertAlmostEqual(result[-1], 100.0)

    def test_all_losses_near_zero(self):
        values = list(range(31, 1, -1))
        result = rsi(values, 14)
        self.assertLess(result[-1], 1.0)

    def test_warmup_is_none(self):
        result = rsi([1.0] * 20, 14)
        self.assertTrue(all(v is None for v in result[:14]))
        self.assertIsNotNone(result[14])


class TestAtr(unittest.TestCase):
    def test_positive_on_moving_prices(self):
        candles = candles_from_closes([1.0, 1.01, 1.0, 1.02, 1.01, 1.03] * 5)
        result = atr(candles, 5)
        self.assertIsNone(result[4])
        self.assertGreater(result[-1], 0)

    def test_flat_prices_zero_range(self):
        candles = candles_from_closes([1.0] * 20)
        result = atr(candles, 5)
        self.assertAlmostEqual(result[-1], 0.0)


if __name__ == "__main__":
    unittest.main()
