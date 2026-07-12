"""Strategy interface.

A strategy answers one question after every completed candle:
"what position do I *want* to hold right now?"

    +1  -> long  (bet the price goes up)
    -1  -> short (bet the price goes down)
     0  -> flat  (no position)

The engine (backtester or live bot) compares that answer with the position
actually held and places whatever orders are needed to match. Keeping
strategies this small makes them easy to test and swap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..data.candles import Candle

LONG = 1
SHORT = -1
FLAT = 0


class Strategy(ABC):
    """Base class for all strategies."""

    #: minimum number of candles required before signals are meaningful
    warmup: int = 1

    @property
    def name(self) -> str:
        return type(self).__name__

    def reset(self) -> None:
        """Clear internal state. Called once before a backtest run."""

    @abstractmethod
    def target_position(self, candles: Sequence[Candle]) -> int:
        """Return the desired stance (+1 / -1 / 0) given candle history.

        ``candles`` is ordered oldest -> newest and contains only *completed*
        candles; the decision executes at the open of the next candle, so a
        strategy can never peek at future prices.

        NOTE: strategies may keep internal state, so callers must feed
        candles in chronological order, one decision per candle.
        """

    def describe(self) -> str:
        return self.name
