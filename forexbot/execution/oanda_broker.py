"""OANDA v20 REST broker.

Works against the *practice* environment (fake money, real prices) or the
live one. Get a free practice account and API token at
https://www.oanda.com/ -> "Try a demo" -> Manage API Access.

Only a tiny slice of the v20 API is used:
    GET  /v3/accounts/{id}/summary          -> equity
    GET  /v3/accounts/{id}/openPositions    -> current positions
    POST /v3/accounts/{id}/orders           -> market order (+ stop/target)
    PUT  /v3/accounts/{id}/positions/{i}/close
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from ..data.candles import parse_time
from .broker import Broker, Position

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
LIVE_HOST = "https://api-fxtrade.oanda.com"


class OandaError(RuntimeError):
    pass


def price_precision(instrument: str) -> int:
    """OANDA rejects over-precise prices: JPY pairs use 3 decimals, most others 5."""
    return 3 if instrument.endswith("JPY") else 5


class OandaBroker(Broker):
    def __init__(self, account_id: str, token: str, practice: bool = True, timeout: float = 15.0):
        if not account_id or not token:
            raise OandaError(
                "OANDA account_id and API token are required "
                "(set OANDA_API_TOKEN in your environment)"
            )
        self.account_id = account_id
        self.practice = practice
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        self.host = PRACTICE_HOST if practice else LIVE_HOST

    # -- HTTP plumbing ----------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        url = f"{self.host}{path}"
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
                if resp.status_code >= 500:
                    raise OandaError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
                if resp.status_code >= 400:
                    # client errors won't improve with retries
                    raise OandaError(
                        f"{method} {path} -> {resp.status_code}: {resp.text[:300]}"
                    ) from None
                return resp.json()
            except (requests.ConnectionError, requests.Timeout, OandaError) as exc:
                if isinstance(exc, OandaError) and "-> 4" in str(exc):
                    raise
                last_error = exc
                time.sleep(2**attempt)
        raise OandaError(f"{method} {path} failed after retries: {last_error}")

    # -- Broker interface -----------------------------------------------------

    def get_equity(self) -> float:
        data = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        return float(data["account"]["NAV"])

    def get_position(self, instrument: str) -> Optional[Position]:
        data = self._request("GET", f"/v3/accounts/{self.account_id}/openPositions")
        for pos in data.get("positions", []):
            if pos["instrument"] != instrument:
                continue
            long_units = int(float(pos["long"]["units"]))
            short_units = int(float(pos["short"]["units"]))
            units = long_units + short_units
            if units == 0:
                continue
            side = pos["long"] if units > 0 else pos["short"]
            return Position(
                instrument=instrument,
                units=units,
                entry_price=float(side["averagePrice"]),
                stop_loss=None,   # attached to the underlying trades, not exposed here
                take_profit=None,
                opened_at=datetime.now(timezone.utc),
            )
        return None

    def market_order(
        self,
        instrument: str,
        units: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None:
        if units == 0:
            return
        digits = price_precision(instrument)
        order: Dict[str, Any] = {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
        }
        if stop_loss is not None:
            order["stopLossOnFill"] = {"price": f"{stop_loss:.{digits}f}"}
        if take_profit is not None:
            order["takeProfitOnFill"] = {"price": f"{take_profit:.{digits}f}"}
        data = self._request(
            "POST", f"/v3/accounts/{self.account_id}/orders", json={"order": order}
        )
        if "orderCancelTransaction" in data:
            reason = data["orderCancelTransaction"].get("reason", "unknown")
            raise OandaError(f"order was cancelled by OANDA: {reason}")

    def close_position(self, instrument: str, reason: str = "signal") -> None:
        pos = self.get_position(instrument)
        if pos is None:
            return
        body = {"longUnits": "ALL"} if pos.units > 0 else {"shortUnits": "ALL"}
        self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/positions/{instrument}/close",
            json=body,
        )

    # -- extras ------------------------------------------------------------

    def get_price(self, instrument: str) -> float:
        """Latest mid price."""
        data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/pricing",
            params={"instruments": instrument},
        )
        prices = data.get("prices", [])
        if not prices:
            raise OandaError(f"no pricing returned for {instrument}")
        bid = float(prices[0]["bids"][0]["price"])
        ask = float(prices[0]["asks"][0]["price"])
        return (bid + ask) / 2

    def server_time(self) -> datetime:
        data = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        return parse_time(data["account"]["createdTime"])  # placeholder for connectivity checks
