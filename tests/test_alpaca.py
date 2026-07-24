import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from forexbot.data.alpaca_feed import AlpacaCryptoFeed, drop_incomplete
from forexbot.data.candles import Candle
from forexbot.execution.alpaca_broker import AlpacaBroker, AlpacaError, format_qty

NOW = datetime(2026, 7, 20, 12, 30, tzinfo=timezone.utc)


class TestFormatQty(unittest.TestCase):
    def test_whole_number_has_no_decimal(self):
        self.assertEqual(format_qty(1.0), "1")
        self.assertEqual(format_qty(12.0), "12")

    def test_fractional_crypto_size(self):
        self.assertEqual(format_qty(0.01), "0.01")
        self.assertEqual(format_qty(0.1), "0.1")

    def test_no_scientific_notation_for_small_values(self):
        result = format_qty(0.000001)
        self.assertNotIn("e", result.lower())
        self.assertEqual(result, "0.000001")

    def test_zero_formats_as_zero(self):
        self.assertEqual(format_qty(0), "0")

    def test_tiny_value_below_precision_floors_to_zero(self):
        # below 1e-8 precision, must format cleanly to "0" rather than
        # producing an empty string or malformed order payload
        self.assertEqual(format_qty(0.000000001), "0")


class TestDropIncomplete(unittest.TestCase):
    def make_candle(self, start):
        return Candle(time=start, open=1, high=1, low=1, close=1)

    def test_forming_bar_is_dropped(self):
        # hourly bars; NOW is 12:30, so the 12:00 bar is still forming
        candles = [
            self.make_candle(NOW.replace(minute=0) - timedelta(hours=2)),  # 10:00 done
            self.make_candle(NOW.replace(minute=0) - timedelta(hours=1)),  # 11:00 done
            self.make_candle(NOW.replace(minute=0)),                        # 12:00 forming
        ]
        kept = drop_incomplete(candles, 3600, NOW)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[-1].time, NOW.replace(minute=0) - timedelta(hours=1))

    def test_bar_ending_exactly_now_is_complete(self):
        candles = [self.make_candle(NOW - timedelta(hours=1))]
        self.assertEqual(len(drop_incomplete(candles, 3600, NOW)), 1)

    def test_all_historical_bars_kept(self):
        candles = [
            self.make_candle(NOW - timedelta(days=10) + timedelta(hours=i))
            for i in range(5)
        ]
        self.assertEqual(len(drop_incomplete(candles, 3600, NOW)), 5)


def canned_response(status=200, payload=None, text="ok"):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = text
    return resp


class TestAlpacaCryptoFeed(unittest.TestCase):
    def make_feed(self):
        feed = AlpacaCryptoFeed("key", "secret")
        feed._session = MagicMock()
        return feed

    def bars_payload(self, symbol, times, price=100.0):
        return {
            "bars": {
                symbol: [
                    {"t": t.isoformat(), "o": price, "h": price + 1,
                     "l": price - 1, "c": price, "v": 10}
                    for t in times
                ]
            }
        }

    def test_bot_can_call_with_count_keyword(self):
        """Regression: TradingBot calls get_candles(..., count=lookback);
        this raised TypeError when the parameter was named `limit`."""
        feed = self.make_feed()
        feed._session.get.return_value = canned_response(payload={"bars": {}})
        feed.get_candles("BTC/USD", "1Hour", count=300)  # must not raise

    def test_requests_explicit_start_spanning_count_bars(self):
        """Regression: without an explicit start, Alpaca defaults to the
        beginning of the current DAY and truncates from the OLDEST side —
        the feed must always send a start far enough back to cover `count`
        recent bars."""
        feed = self.make_feed()
        feed._session.get.return_value = canned_response(payload={"bars": {}})
        before = datetime.now(timezone.utc)
        feed.get_candles("BTC/USD", "1Hour", count=300)
        params = feed._session.get.call_args.kwargs["params"]
        self.assertIn("start", params)
        start = datetime.fromisoformat(params["start"])
        hours_back = (before - start).total_seconds() / 3600
        self.assertGreaterEqual(hours_back, 300)

    def test_drops_still_forming_bar(self):
        feed = self.make_feed()
        now = datetime.now(timezone.utc)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        times = [current_hour - timedelta(hours=2), current_hour - timedelta(hours=1),
                 current_hour]  # last one is still forming
        feed._session.get.return_value = canned_response(
            payload=self.bars_payload("BTC/USD", times)
        )
        candles = feed.get_candles("BTC/USD", "1Hour", count=10)
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[-1].time, current_hour - timedelta(hours=1))

    def test_returns_at_most_count_newest(self):
        feed = self.make_feed()
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        times = [now - timedelta(hours=i) for i in range(10, 0, -1)]
        feed._session.get.return_value = canned_response(
            payload=self.bars_payload("BTC/USD", times)
        )
        candles = feed.get_candles("BTC/USD", "1Hour", count=3)
        self.assertEqual(len(candles), 3)
        self.assertEqual(candles[-1].time, now - timedelta(hours=1))

    def test_rejects_unknown_granularity(self):
        feed = self.make_feed()
        with self.assertRaises(ValueError):
            feed.get_candles("BTC/USD", "2Hour")


class TestAlpacaBrokerOrderFlow(unittest.TestCase):
    """The safety-critical sequencing, with HTTP mocked out."""

    def make_broker(self):
        broker = AlpacaBroker("key", "secret", paper=True)
        self.calls = []

        def fake_request(method, url, timeout=None, **kwargs):
            self.calls.append((method, url, kwargs.get("json"), kwargs.get("params")))
            if method == "POST" and "/orders" in url:
                return canned_response(payload={"id": "stop-123"})
            if method == "GET" and url.endswith("/v2/orders"):
                return canned_response(payload=self.open_orders)
            if method == "DELETE":
                return canned_response(status=204, text="")
            return canned_response()

        self.open_orders = []
        broker._session.request = fake_request
        return broker

    def test_entry_places_market_buy_then_resting_stop(self):
        broker = self.make_broker()
        broker.market_order("BTC/USD", 0.1, stop_loss=29000.0, take_profit=32000.0)
        (m1, _, body1, _), (m2, _, body2, _) = self.calls
        self.assertEqual((m1, body1["side"], body1["type"]), ("POST", "buy", "market"))
        self.assertEqual((m2, body2["side"], body2["type"]), ("POST", "sell", "stop"))
        self.assertEqual(body2["qty"], body1["qty"])
        self.assertEqual(broker._stop_order_ids["BTC/USD"], "stop-123")
        self.assertEqual(broker.get_take_profit("BTC/USD"), 32000.0)

    def test_short_rejected_before_any_http_call(self):
        broker = self.make_broker()
        with self.assertRaises(AlpacaError):
            broker.market_order("BTC/USD", -0.1)
        self.assertEqual(self.calls, [])

    def test_close_cancels_tracked_stop_before_liquidating(self):
        broker = self.make_broker()
        broker.market_order("BTC/USD", 0.1, stop_loss=29000.0)
        self.calls.clear()
        broker.close_position("BTC/USD")
        self.assertEqual(self.calls[0][0], "DELETE")
        self.assertIn("/v2/orders/stop-123", self.calls[0][1])
        self.assertEqual(self.calls[1][0], "DELETE")
        self.assertIn("/v2/positions/", self.calls[1][1])
        self.assertNotIn("BTC/USD", broker._stop_order_ids)
        self.assertNotIn("BTC/USD", broker._take_profits)

    def test_close_after_restart_finds_and_cancels_orphaned_stop(self):
        """If the bot restarted, the stop-order id is no longer tracked in
        memory; close_position must look up open orders for the symbol and
        cancel them, or a stale stop would fire against a future position."""
        broker = self.make_broker()
        self.open_orders = [{"id": "orphan-7", "symbol": "BTC/USD"}]
        broker.close_position("BTC/USD")  # nothing tracked -> fallback path
        methods_urls = [(m, u) for m, u, _, _ in self.calls]
        self.assertEqual(methods_urls[0][0], "GET")
        self.assertTrue(methods_urls[0][1].endswith("/v2/orders"))
        self.assertEqual(methods_urls[1][0], "DELETE")
        self.assertIn("/v2/orders/orphan-7", methods_urls[1][1])
        self.assertEqual(methods_urls[2][0], "DELETE")
        self.assertIn("/v2/positions/", methods_urls[2][1])


class TestAlpacaLimitEntry(unittest.TestCase):
    """The 'patient buyer': limit at the bid, poll, fall back to market."""

    def make_broker(self, order_states, bid=30_000.0):
        """order_states: successive JSON payloads returned by GET /v2/orders/{id}."""
        broker = AlpacaBroker(
            "key", "secret", paper=True,
            entry="limit", limit_patience_seconds=10, limit_poll_seconds=3,
        )
        # fake clock: no real waiting; each "sleep" advances simulated time,
        # so with patience 10 and poll 3 the loop polls exactly 3 times
        clock = {"t": 0.0}
        broker._monotonic = lambda: clock["t"]
        broker._sleep = lambda seconds: clock.__setitem__("t", clock["t"] + seconds)
        self.calls = []
        self.states = list(order_states)

        def fake_request(method, url, timeout=None, **kwargs):
            self.calls.append((method, url, kwargs.get("json")))
            if method == "POST" and "/orders" in url:
                body = kwargs["json"]
                return canned_response(payload={"id": f"{body['type']}-1"})
            if method == "GET" and "/v2/orders/" in url:
                payload = self.states.pop(0) if self.states else {"status": "canceled", "filled_qty": "0"}
                return canned_response(payload=payload)
            if method == "DELETE":
                return canned_response(status=204, text="")
            return canned_response()

        broker._session.request = fake_request
        quote = canned_response(payload={"quotes": {"BTC/USD": {"bp": bid, "ap": bid + 5}}})
        broker._session.get = MagicMock(return_value=quote)
        return broker

    def order_types_posted(self):
        return [j["type"] for m, u, j in self.calls if m == "POST" and j]

    def test_limit_fill_pays_maker_and_places_stop(self):
        broker = self.make_broker([{"status": "filled", "filled_qty": "0.1"}])
        broker.market_order("BTC/USD", 0.1, stop_loss=29_000.0)
        self.assertEqual(self.order_types_posted(), ["limit", "stop"])  # no market order
        limit_body = next(j for m, _, j in self.calls if m == "POST" and j["type"] == "limit")
        self.assertEqual(limit_body["limit_price"], "30000.00")
        self.assertEqual(limit_body["side"], "buy")
        stop_body = next(j for m, _, j in self.calls if m == "POST" and j["type"] == "stop")
        self.assertEqual(stop_body["qty"], "0.1")

    def test_unfilled_limit_falls_back_to_market(self):
        # every poll says still working; after patience -> cancel -> market
        pending = [{"status": "new", "filled_qty": "0"}] * 10
        broker = self.make_broker(pending)
        broker.market_order("BTC/USD", 0.1, stop_loss=29_000.0)
        self.assertEqual(self.order_types_posted(), ["limit", "market", "stop"])
        cancels = [u for m, u, _ in self.calls if m == "DELETE"]
        self.assertTrue(any("/v2/orders/limit-1" in u for u in cancels))

    def test_partial_fill_keeps_partial_and_sizes_stop_to_it(self):
        # unfilled during polling, but the post-cancel check reveals a partial
        pending = [{"status": "new", "filled_qty": "0"}] * 3
        final = [{"status": "canceled", "filled_qty": "0.04"}]
        broker = self.make_broker(pending + final)
        broker.market_order("BTC/USD", 0.1, stop_loss=29_000.0)
        types = self.order_types_posted()
        self.assertNotIn("market", types)  # partial accepted, remainder NOT chased
        stop_body = next(j for m, _, j in self.calls if m == "POST" and j["type"] == "stop")
        self.assertEqual(stop_body["qty"], "0.04")

    def test_no_quote_available_goes_straight_to_market(self):
        broker = self.make_broker([])
        broker._session.get = MagicMock(return_value=canned_response(payload={"quotes": {}}))
        broker.market_order("BTC/USD", 0.1, stop_loss=29_000.0)
        self.assertEqual(self.order_types_posted(), ["market", "stop"])


if __name__ == "__main__":
    unittest.main()
