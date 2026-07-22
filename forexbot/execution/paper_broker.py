"""Simulated broker used by the backtester.

Fills orders instantly at the current candle's open price, charging half
the bid/ask spread on entry and half on exit (so a round trip costs one
full spread — the main real-world cost of trading forex).

Simplifications, deliberately conservative where possible:
* stop-loss and take-profit are evaluated against each candle's high/low;
  if both could have been hit inside one candle, the STOP is assumed to
  have been hit first (pessimistic).
* no slippage model beyond the spread; real fills are slightly worse.

Set ``long_only=True`` to backtest as if trading a venue that cannot short
(e.g. Alpaca crypto) — a short signal must be rejected here rather than
silently filled, or the backtest would claim an edge the venue can't
actually deliver.
"""

from __future__ import annotations

from typing import List, Optional

from ..data.candles import Candle
from .broker import Broker, ClosedTrade, Position


class PaperBroker(Broker):
    def __init__(
        self,
        starting_balance: float = 10_000.0,
        spread: float = 0.00008,
        long_only: bool = False,
    ):
        self.starting_balance = starting_balance
        self.balance = starting_balance          # realised cash
        self.spread = spread
        self.long_only = long_only
        self.position: Optional[Position] = None
        self.trades: List[ClosedTrade] = []
        self._candle: Optional[Candle] = None    # the candle currently being simulated

    # -- simulation clock -------------------------------------------------

    def process_candle(self, candle: Candle) -> None:
        """Advance the simulation to a new candle.

        First resolves any stop-loss / take-profit the candle's range would
        have triggered, then leaves the candle as "current" so subsequent
        market orders fill at its open.
        """
        self._candle = candle
        pos = self.position
        if pos is None:
            return

        if pos.units > 0:  # long: stop below, target above
            if pos.stop_loss is not None and candle.low <= pos.stop_loss:
                self._exit(pos.stop_loss, "stop_loss")
            elif pos.take_profit is not None and candle.high >= pos.take_profit:
                self._exit(pos.take_profit, "take_profit")
        else:  # short: stop above, target below
            if pos.stop_loss is not None and candle.high >= pos.stop_loss:
                self._exit(pos.stop_loss, "stop_loss")
            elif pos.take_profit is not None and candle.low <= pos.take_profit:
                self._exit(pos.take_profit, "take_profit")

    # -- Broker interface -------------------------------------------------

    def get_equity(self) -> float:
        price = self._candle.close if self._candle else None
        return self.equity(price)

    def equity(self, mark_price: Optional[float]) -> float:
        if self.position is None or mark_price is None:
            return self.balance
        pos = self.position
        return self.balance + pos.units * (mark_price - pos.entry_price)

    def get_position(self, instrument: str) -> Optional[Position]:
        if self.position and self.position.instrument == instrument:
            return self.position
        return None

    def market_order(
        self,
        instrument: str,
        units: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None:
        if self._candle is None:
            raise RuntimeError("process_candle() must be called before placing orders")
        if units == 0:
            return
        if self.long_only and units < 0:
            raise ValueError(
                "long_only broker cannot open a short position; the strategy/engine "
                "should have clamped this signal to flat instead of calling market_order"
            )
        if self.position is not None:
            raise RuntimeError("PaperBroker holds one position at a time; close it first")
        half = self.spread / 2
        fill = self._candle.open + half if units > 0 else self._candle.open - half
        self.position = Position(
            instrument=instrument,
            units=units,
            entry_price=fill,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=self._candle.time,
        )

    def close_position(self, instrument: str, reason: str = "signal") -> None:
        if self.position is None or self.position.instrument != instrument:
            return
        if self._candle is None:
            raise RuntimeError("no current candle to price the close against")
        half = self.spread / 2
        # closing a long means selling (receive open - half); closing a short means buying
        price = (
            self._candle.open - half
            if self.position.units > 0
            else self._candle.open + half
        )
        self._exit(price, reason)

    # -- internals ----------------------------------------------------------

    def _exit(self, price: float, reason: str) -> None:
        pos = self.position
        assert pos is not None and self._candle is not None
        pnl = pos.units * (price - pos.entry_price)
        self.balance += pnl
        self.trades.append(
            ClosedTrade(
                instrument=pos.instrument,
                units=pos.units,
                entry_time=pos.opened_at,
                entry_price=pos.entry_price,
                exit_time=self._candle.time,
                exit_price=price,
                pnl=pnl,
                reason=reason,
            )
        )
        self.position = None
