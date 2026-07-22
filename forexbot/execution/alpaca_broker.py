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

Only a small slice of the v2 API is used:
    GET    /v2/account                    -> equity
    GET    /v2/positions/{symbol}         -> current position (404 = none)
    POST   /v2/orders                     -> market or stop order
    DELETE /v2/orders/{id}                -> cancel a resting order
    DELETE /v2/positions/{symbol}         -> liquidate a position
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

from .broker import Broker, Position

PAPER_HOST = "https://paper-api.alpaca.markets"
LIVE_HOST = "https://api.alpaca.markets"


class AlpacaError(RuntimeError):
    pass


def format_qty(units: float) -> str:
    """Alpaca crypto qty as a clean decimal string (no '1e-05', no trailing zeros)."""
    text = f"{units:.8f}".rstrip("0").rstrip(".")
    return text or "0"


class AlpacaBroker(Broker):
    long_only = True  # crypto cannot be shorted on Alpaca — not configurable

    def __init__(
        self, api_key_id: str, api_secret_key: str, paper: bool = True, timeout: float = 15.0
    ):
        if not api_key_id or not api_secret_key:
            raise AlpacaError(
                "Alpaca API key id and secret are required "
                "(env vars ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY)"
            )
        self.paper = paper
        self.timeout = timeout
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
    ) -> Optional[Dict[str, Any]]:
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

        if stop_loss is not None:
            stop_data = self._request(
                "POST",
                "/v2/orders",
                json={
                    "symbol": instrument,
                    "qty": qty_str,
                    "side": "sell",
                    "type": "stop",
                    "stop_price": f"{stop_loss:.8f}",
                    "time_in_force": "gtc",
                },
            )
            self._stop_order_ids[instrument] = stop_data["id"]

        if take_profit is not None:
            self._take_profits[instrument] = take_profit

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
        if order_id is None:
            return
        # allow_404: the stop may already have filled or been cancelled
        self._request("DELETE", f"/v2/orders/{order_id}", allow_404=True)
