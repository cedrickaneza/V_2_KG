import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from forexbot.execution.alpaca_broker import AlpacaBroker
from forexbot.execution.oanda_broker import OandaBroker
from forexbot.risk.manager import RiskConfig, RiskManager
from forexbot.state import load_state, save_state

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


class TestStatePersistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "state.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_risk_history_round_trip(self):
        """Kill-switch memory must survive a restart, or one-shot daily runs
        would reset the account's safety limits every day."""
        risk = RiskManager(RiskConfig())
        risk.update(NOW, 10_000)
        risk.update(NOW, 8_900)  # -11% -> kill switch latches
        self.assertTrue(risk.halted)

        broker = AlpacaBroker("k", "s")
        save_state(self.path, risk, broker)

        fresh_risk = RiskManager(RiskConfig())
        fresh_broker = AlpacaBroker("k", "s")
        self.assertTrue(load_state(self.path, fresh_risk, fresh_broker))
        self.assertTrue(fresh_risk.halted)
        self.assertEqual(fresh_risk.peak_equity, 10_000)
        self.assertIn("kill switch", fresh_risk.halt_reason)

    def test_broker_take_profits_round_trip(self):
        risk = RiskManager()
        broker = AlpacaBroker("k", "s")
        broker._take_profits = {"BTC/USD": 32_000.0}
        broker._stop_order_ids = {"BTC/USD": "stop-9"}
        save_state(self.path, risk, broker)

        fresh_broker = AlpacaBroker("k", "s")
        load_state(self.path, RiskManager(), fresh_broker)
        self.assertEqual(fresh_broker.get_take_profit("BTC/USD"), 32_000.0)
        self.assertEqual(fresh_broker._stop_order_ids["BTC/USD"], "stop-9")

    def test_missing_file_returns_false(self):
        self.assertFalse(load_state(self.path, RiskManager(), AlpacaBroker("k", "s")))

    def test_broker_without_tracked_state_is_fine(self):
        """OANDA brackets orders on the exchange, so it has no in-memory
        take-profits — save/load must handle that without complaint."""
        risk = RiskManager()
        risk.update(NOW, 10_000)
        oanda = OandaBroker("acct", "token")
        save_state(self.path, risk, oanda)
        fresh_risk = RiskManager()
        self.assertTrue(load_state(self.path, fresh_risk, OandaBroker("acct", "token")))
        self.assertEqual(fresh_risk.peak_equity, 10_000)


if __name__ == "__main__":
    unittest.main()
