import unittest
from datetime import timedelta

from forexbot.backtest.engine import BacktestEngine
from forexbot.backtest.metrics import max_drawdown
from forexbot.data.candles import Candle
from forexbot.execution.paper_broker import PaperBroker
from forexbot.risk.manager import RiskConfig, RiskManager
from forexbot.strategies.sma_crossover import SmaCrossover
from tests.helpers import START, candles_from_closes, trend


class TestPaperBroker(unittest.TestCase):
    def make_candle(self, o, h, l, c, hours=0):
        return Candle(time=START + timedelta(hours=hours), open=o, high=h, low=l, close=c)

    def test_entry_pays_half_spread(self):
        broker = PaperBroker(10_000, spread=0.0002)
        broker.process_candle(self.make_candle(1.1000, 1.1010, 1.0990, 1.1005))
        broker.market_order("EUR_USD", 10_000)
        self.assertAlmostEqual(broker.position.entry_price, 1.1001)

    def test_round_trip_costs_full_spread(self):
        broker = PaperBroker(10_000, spread=0.0002)
        broker.process_candle(self.make_candle(1.1000, 1.1010, 1.0990, 1.1000))
        broker.market_order("EUR_USD", 10_000)
        broker.process_candle(self.make_candle(1.1000, 1.1010, 1.0990, 1.1000, hours=1))
        broker.close_position("EUR_USD")
        # price unchanged, so loss == spread * units
        self.assertAlmostEqual(broker.balance, 10_000 - 0.0002 * 10_000)

    def test_stop_loss_triggers_on_low(self):
        broker = PaperBroker(10_000, spread=0.0)
        broker.process_candle(self.make_candle(1.1000, 1.1010, 1.0990, 1.1005))
        broker.market_order("EUR_USD", 10_000, stop_loss=1.0950)
        broker.process_candle(self.make_candle(1.1000, 1.1005, 1.0940, 1.0960, hours=1))
        self.assertIsNone(broker.position)
        self.assertEqual(broker.trades[-1].reason, "stop_loss")
        self.assertAlmostEqual(broker.trades[-1].exit_price, 1.0950)

    def test_stop_beats_take_profit_in_same_candle(self):
        broker = PaperBroker(10_000, spread=0.0)
        broker.process_candle(self.make_candle(1.1000, 1.1010, 1.0990, 1.1005))
        broker.market_order("EUR_USD", 10_000, stop_loss=1.0950, take_profit=1.1050)
        # wild candle that spans both levels -> pessimistic: stop first
        broker.process_candle(self.make_candle(1.1000, 1.1100, 1.0900, 1.1000, hours=1))
        self.assertEqual(broker.trades[-1].reason, "stop_loss")

    def test_short_take_profit(self):
        broker = PaperBroker(10_000, spread=0.0)
        broker.process_candle(self.make_candle(1.1000, 1.1010, 1.0990, 1.1000))
        broker.market_order("EUR_USD", -10_000, take_profit=1.0950)
        broker.process_candle(self.make_candle(1.0990, 1.0995, 1.0940, 1.0960, hours=1))
        self.assertEqual(broker.trades[-1].reason, "take_profit")
        self.assertGreater(broker.trades[-1].pnl, 0)

    def test_fractional_units_supported(self):
        """Crypto-scale sizing (e.g. 0.1 BTC) must not be truncated to zero."""
        broker = PaperBroker(10_000, spread=0.0)
        broker.process_candle(self.make_candle(30_000, 30_100, 29_900, 30_050))
        broker.market_order("BTC/USD", 0.1)
        self.assertAlmostEqual(broker.position.units, 0.1)

    def test_percentage_cost_round_trip(self):
        """With spread_pct, a round trip costs that fraction of the trade's
        value — the crypto fee model, correct at any price level."""
        broker = PaperBroker(10_000, spread_pct=0.005)  # 0.5% round trip
        broker.process_candle(self.make_candle(50_000, 50_100, 49_900, 50_000))
        broker.market_order("BTC/USD", 0.1)
        broker.process_candle(self.make_candle(50_000, 50_100, 49_900, 50_000, hours=1))
        broker.close_position("BTC/USD")
        # price unchanged -> loss == 0.5% of (0.1 units x 50_000)
        self.assertAlmostEqual(broker.balance, 10_000 - 0.005 * 0.1 * 50_000)

    def test_percentage_cost_scales_with_price(self):
        """The whole point of spread_pct: the same trade costs proportionally
        the same at a 10k price as at a 100k price."""
        for price in (10_000, 100_000):
            broker = PaperBroker(10_000, spread_pct=0.005)
            broker.process_candle(self.make_candle(price, price, price, price))
            broker.market_order("BTC/USD", 1.0)
            broker.process_candle(self.make_candle(price, price, price, price, hours=1))
            broker.close_position("BTC/USD")
            self.assertAlmostEqual(broker.balance, 10_000 - 0.005 * price)

    def test_long_only_rejects_short(self):
        broker = PaperBroker(10_000, spread=0.0, long_only=True)
        broker.process_candle(self.make_candle(1.1000, 1.1010, 1.0990, 1.1005))
        with self.assertRaises(ValueError):
            broker.market_order("EUR_USD", -10_000)


class TestBacktestEngine(unittest.TestCase):
    def run_engine(self, closes, **risk_kwargs):
        candles = candles_from_closes(closes, spread=0.0002)
        strategy = SmaCrossover(fast=5, slow=15)
        risk = RiskManager(RiskConfig(**risk_kwargs))
        engine = BacktestEngine(strategy, risk, starting_balance=10_000, spread=0.0001)
        return engine.run(candles)

    def test_profits_in_strong_trend(self):
        closes = trend(1.0, 0.0005, 400)
        result = self.run_engine(closes)
        self.assertGreater(result.metrics["num_trades"], 0)
        self.assertGreater(result.metrics["final_equity"], 10_000)

    def test_equity_curve_covers_run(self):
        closes = trend(1.0, 0.0005, 200)
        result = self.run_engine(closes)
        self.assertGreater(len(result.equity_curve), 150)

    def test_open_position_closed_at_end_of_data(self):
        closes = trend(1.0, 0.0005, 200)
        result = self.run_engine(closes)
        self.assertEqual(result.trades[-1].reason, "end_of_data")

    def test_refuses_too_little_data(self):
        with self.assertRaises(ValueError):
            self.run_engine(trend(1.0, 0.0005, 10))

    def test_long_only_clamps_short_signals_to_flat(self):
        """In a downtrend SmaCrossover wants SHORT; a long_only venue (e.g.
        Alpaca crypto) can't take that trade, so it must end up flat instead
        of a broker rejecting an order the engine should never have sent."""
        closes = trend(1.2, -0.0005, 400)  # steady downtrend -> strategy wants SHORT
        candles = candles_from_closes(closes, spread=0.0002)
        strategy = SmaCrossover(fast=5, slow=15)
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy, risk, starting_balance=10_000, spread=0.0001, long_only=True
        )
        result = engine.run(candles)
        self.assertTrue(all(t.units >= 0 for t in result.trades))

    def test_all_decisions_use_past_data_only(self):
        """A strategy that records what it saw must never see the candle
        being traded, only strictly older ones."""
        seen = []

        class Spy(SmaCrossover):
            def target_position(self, candles):
                seen.append(candles[-1].time)
                return super().target_position(candles)

        candles = candles_from_closes(trend(1.0, 0.0005, 100))
        engine = BacktestEngine(Spy(fast=5, slow=15), RiskManager(), 10_000, 0.0001)
        result = engine.run(candles)
        # every equity point is for a candle strictly after the newest
        # candle the strategy saw when deciding it
        for (decision_time, (traded_time, _)) in zip(seen, result.equity_curve):
            self.assertLess(decision_time, traded_time)


class TestMetrics(unittest.TestCase):
    def test_max_drawdown(self):
        self.assertAlmostEqual(max_drawdown([100, 120, 90, 110]), 0.25)
        self.assertAlmostEqual(max_drawdown([100, 110, 120]), 0.0)


if __name__ == "__main__":
    unittest.main()
