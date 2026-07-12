"""Broker abstraction.

Every broker — the in-memory simulator used for backtesting and the real
OANDA client — implements this same small interface, so the rest of the
code never cares which one it is talking to.

Sign convention: positive units = long, negative units = short.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    instrument: str
    units: int                      # +long / -short
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    opened_at: datetime


@dataclass
class ClosedTrade:
    instrument: str
    units: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl: float
    reason: str                     # "signal" | "stop_loss" | "take_profit" | "end_of_data"


class Broker(ABC):
    @abstractmethod
    def get_equity(self) -> float:
        """Account value including unrealised profit/loss."""

    @abstractmethod
    def get_position(self, instrument: str) -> Optional[Position]:
        """The currently open position for an instrument, or None."""

    @abstractmethod
    def market_order(
        self,
        instrument: str,
        units: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None:
        """Buy (units > 0) or sell (units < 0) at the current market price."""

    @abstractmethod
    def close_position(self, instrument: str, reason: str = "signal") -> None:
        """Fully close the open position for an instrument, if any."""
