"""Alpaca crypto broker (paper or live).

Sign up free at https://alpaca.markets/ (email + password, no identity
verification for paper trading) and generate API keys from the dashboard.

Two hard platform constraints shape this class, both different from OANDA:

1. **Crypto cannot be shorted on Alpaca.** ``long_only = True`` below is not
   a preference, it's a fact of the venue — ``market_order`` refuses
   negative units rather than silently failing at the exchange.

2. **Crypto orders cannot be brackets** (one order carrying an attached
   stop-loss + take-profit, the way OANDA's ``stopLossOnFill`` works).
   Alpaca only allows *standalone* orders for crypto, so protection has to
   be built from two separate pieces here:
       * stop-loss  -> a resting STOP order submitted right after entry.
         This is the safety-critical piece: it lives on Alpaca's servers,
         so it still protects the position even if this bot's process
         crashes or loses its network connection.
       * take-profit -> tracked in memory and checked once per cycle by
         the caller (TradingBot); if crossed, the bot cancels the resting
         stop and closes the position with a market order. This is a
         disclosed, deliberate simplification: missing a take-profit exit
         while the bot is offline costs upside, not capital, which is an
         acceptable trade against the complexity of running two competing
         resting orders (stop + limit) that would need manual OCO
         reconciliation. Call ``get_take_profit`` each cycle to check it.

Entry styles (``entry=`` constructor arg):
    * ``"market"`` — buy instantly at whatever the market asks. Simple, but
      always pays Alpaca's highest ("taker") fee, ~0.25% of the trade.
    * ``"limit"`` — the patient buyer: rest a buy order at the current best
      bid, poll for up to ``limit_patience_seconds``; a resting order that
      gets filled pays the cheaper "maker" fee (≤0.15%). If it doesn't fill
      in time, cancel and fall back to a market order, so a trade signal is
      never silently dropped. The protective stop is placed only AFTER the
      entry actually fills (a stop-sell can't exist without a position on a
      venue with no shorting), sized to the quantity that really filled —
      which also handles partial fills.

Only a small slice of the v2 API is used:
    GET    /v2/account                    -> equity
    GET    /v2/positions/{symbol}         -> current position (404 = none)
    GET    /v2/orders?status=open         -> find orphaned resting orders
    GET    /v2/orders/{id}                -> poll a limit entry's fill status
    POST   /v2/orders                     -> market, limit or stop order
    DELETE /v2/orders/{id}                -> cancel a resting order
    DELETE /v2/positions/{symbol}         -> liquidate a position
plus the latest-quote endpoint on the market-data host for the bid price.

Known, accepted gaps (paper-trading grade, not production grade):
* if the entry fills but the follow-up stop order submission fails, the
  position is briefly unprotected until the next cycle's log shows the
  exception and a human intervenes;
* a POST retried after a network timeout could double-submit (no
  idempotency key) — same tradeoff the OANDA client makes.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

from .broker import Broker, Position

PAPER_HOST = "https://paper-api.alpaca.markets"
LIVE_HOST = "https://api.alpaca.markets"
DATA_HOST = "https://data.alpaca.markets"

log = logging.getLogger("forexbot")


class AlpacaError(RuntimeError):
    pass


def format_qty(units: float) -> str:
    """Alpaca crypto qty as a clean decimal string (no '1e-05', no trailing zeros)."""
    text = f"{units:.8f}".rstrip("0").rstrip(".")
    return text or "0"


def format_limit_price(price: float) -> str:
    """Sensible decimal places across coin price scales (BTC 60000 vs DOGE 0.12)."""
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.6f}"


class AlpacaBroker(Broker):
    long_only = True  # crypto cannot be shorted on Alpaca — not configurable

    def __init__(
        self,
        api_key_id: str,
        api_secret_key: str,
        paper: bool = True,
        timeout: float = 15.0,
        entry: str = "market",
        limit_patience_seconds: float = 120.0,
        limit_poll_seconds: float = 3.0,
    ):
        if not api_key_id or not api_secret_key:
            raise AlpacaError(
                "Alpaca API key id and secret are required "
                "(env vars ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY)"
            )
        if entry not in ("market", "limit"):
            raise AlpacaError(f"entry must be 'market' or 'limit', got '{entry}'")
        self.paper = paper
        self.timeout = timeout
        self.entry = entry
        self.limit_patience_seconds = limit_patience_seconds
        self.limit_poll_seconds = limit_poll_seconds
        self._sleep = time.sleep          # replaceable in tests
        self._monotonic = time.monotonic  # replaceable in tests
        self._session = requests.Session()
        self._session.headers.update(
            {"APCA-API-KEY-ID": api_key_id, "APCA-API-SECRET-KEY": api_secret_key}
        )
        self.host = PAPER_HOST if paper else LIVE_HOST
        self._stop_order_ids: Dict[str, str] = {}
        self._take_profits: Dict[str, float] = {}

    # -- HTTP plumbing ----------------------------------------------------

    def _request(
        self, method: str, path: str, allow_404: bool = False, **kwargs: Any
    ) -> Any:
        """Returns parsed JSON (dict for most endpoints, list for /v2/orders),
        or None when allow_404 swallowed a 404."""
        url = f"{self.host}{path}"
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
                if allow_404 and resp.status_code == 404:
                    return None
                if resp.status_code >= 500:
                    raise AlpacaError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
                if resp.status_code >= 400:
                    raise AlpacaError(
                        f"{method} {path} -> {resp.status_code}: {resp.text[:300]}"
                    ) from None
                return resp.json() if resp.text else {}
            except (requests.ConnectionError, requests.Timeout, AlpacaError) as exc:
                if isinstance(exc, AlpacaError) and "-> 4" in str(exc):
                    raise
                last_error = exc
                time.sleep(2**attempt)
        raise AlpacaError(f"{method} {path} failed after retries: {last_error}")

    @staticmethod
    def _encode(symbol: str) -> str:
        return quote(symbol, safe="")

    # -- Broker interface -----------------------------------------------------

    def get_equity(self) -> float:
        data = self._request("GET", "/v2/account")
        return float(data["equity"])

    def get_position(self, instrument: str) -> Optional[Position]:
        data = self._request("GET", f"/v2/positions/{self._encode(instrument)}", allow_404=True)
        if data is None:
            return None
        qty = float(data["qty"])
        units = qty if data["side"] == "long" else -qty
        return Position(
            instrument=instrument,
            units=units,
            entry_price=float(data["avg_entry_price"]),
            stop_loss=None,       # tracked separately, see _stop_order_ids
            take_profit=self._take_profits.get(instrument),
            opened_at=datetime.now(timezone.utc),
        )

    def market_order(
        self,
        instrument: str,
        units: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None:
        if units == 0:
            return
        if units < 0:
            raise AlpacaError(
                "Alpaca cannot short crypto; the caller should have clamped this "
                "signal to flat instead of calling market_order with units < 0"
            )
        qty_str = format_qty(units)
        if qty_str == "0":
            return

        if self.entry == "limit":
            filled_qty = self._limit_entry_with_fallback(instrument, qty_str, units)
        else:
            self._submit_market_buy(instrument, qty_str)
            filled_qty = units

        if filled_qty <= 0:
            log.warning("%s: entry did not fill at all — no position, no stop", instrument)
            return

        # protective stop sized to what actually filled (handles partials)
        if stop_loss is not None:
            stop_data = self._request(
                "POST",
                "/v2/orders",
                json={
                    "symbol": instrument,
                    "qty": format_qty(filled_qty),
                    "side": "sell",
                    "type": "stop",
                    "stop_price": f"{stop_loss:.8f}",
                    "time_in_force": "gtc",
                },
            )
            self._stop_order_ids[instrument] = stop_data["id"]

        if take_profit is not None:
            self._take_profits[instrument] = take_profit

    def _submit_market_buy(self, instrument: str, qty_str: str) -> None:
        self._request(
            "POST",
            "/v2/orders",
            json={
                "symbol": instrument,
                "qty": qty_str,
                "side": "buy",
                "type": "market",
                "time_in_force": "gtc",
            },
        )

    def _limit_entry_with_fallback(
        self, instrument: str, qty_str: str, units: float
    ) -> float:
        """Try to enter as a maker (limit at the best bid); fall back to a
        market order if unfilled within the patience window. Returns the
        quantity actually acquired."""
        bid = self._latest_bid(instrument)
        if bid is None or bid <= 0:
            log.warning("%s: no bid quote available — using market entry", instrument)
            self._submit_market_buy(instrument, qty_str)
            return units

        order = self._request(
            "POST",
            "/v2/orders",
            json={
                "symbol": instrument,
                "qty": qty_str,
                "side": "buy",
                "type": "limit",
                "limit_price": format_limit_price(bid),
                "time_in_force": "gtc",
            },
        )
        order_id = order["id"]

        deadline = self._monotonic() + self.limit_patience_seconds
        while True:
            self._sleep(self.limit_poll_seconds)
            if self._monotonic() >= deadline:
                break  # patience over; the post-cancel check below catches late fills
            state = self._request("GET", f"/v2/orders/{order_id}", allow_404=True)
            if state and state.get("status") == "filled":
                log.info("%s: limit entry filled as maker at %s", instrument, format_limit_price(bid))
                return float(state.get("filled_qty") or units)

        # patience exhausted: cancel, then look at the FINAL state — the
        # order may have filled (fully or partly) in the race with the cancel
        self._request("DELETE", f"/v2/orders/{order_id}", allow_404=True)
        state = self._request("GET", f"/v2/orders/{order_id}", allow_404=True)
        already = float((state or {}).get("filled_qty") or 0)
        if already > 0:
            log.info(
                "%s: limit entry filled %s of %s before cancel — keeping the partial",
                instrument, format_qty(already), qty_str,
            )
            return already

        log.info("%s: limit entry unfilled after %.0fs — falling back to market",
                 instrument, self.limit_patience_seconds)
        self._submit_market_buy(instrument, qty_str)
        return units

    def _latest_bid(self, instrument: str) -> Optional[float]:
        """Best bid from the market-data host (different host than trading)."""
        try:
            resp = self._session.get(
                f"{DATA_HOST}/v1beta3/crypto/us/latest/quotes",
                params={"symbols": instrument},
                timeout=self.timeout,
            )
            if resp.status_code >= 400:
                return None
            quote_data = resp.json().get("quotes", {}).get(instrument, {})
            return float(quote_data.get("bp") or 0) or None
        except (requests.ConnectionError, requests.Timeout, ValueError):
            return None

    def close_position(self, instrument: str, reason: str = "signal") -> None:
        self._cancel_resting_stop(instrument)
        self._take_profits.pop(instrument, None)
        self._request("DELETE", f"/v2/positions/{self._encode(instrument)}", allow_404=True)

    # -- take-profit is bot-managed for crypto; see module docstring ------

    def get_take_profit(self, instrument: str) -> Optional[float]:
        return self._take_profits.get(instrument)

    # -- internals ----------------------------------------------------------

    def _cancel_resting_stop(self, instrument: str) -> None:
        order_id = self._stop_order_ids.pop(instrument, None)
        if order_id is not None:
            # allow_404: the stop may already have filled or been cancelled
            self._request("DELETE", f"/v2/orders/{order_id}", allow_404=True)
            return
        # No tracked id — e.g. the bot restarted since the stop was placed.
        # A resting stop left behind after liquidation would fire later with
        # no position behind it, so find and cancel any open orders for this
        # symbol before the caller closes the position.
        data = self._request(
            "GET", "/v2/orders", params={"status": "open", "symbols": instrument}
        )
        for order in data or []:
            self._request("DELETE", f"/v2/orders/{order['id']}", allow_404=True)
