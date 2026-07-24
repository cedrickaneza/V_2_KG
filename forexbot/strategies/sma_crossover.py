"""Trend-following: fast/slow simple-moving-average crossover.

Logic: when the average of recent prices (fast SMA) sits above the average
of a longer window (slow SMA), price is trending up -> be long. When it sits
below -> be short. This is the classic first strategy in every textbook:
it makes money in long trends and bleeds slowly in sideways markets.
"""

from __future__ import annotations

from typing import Sequence

from ..data.candles import Candle
from .base import FLAT, LONG, SHORT, Strategy


class SmaCrossover(Strategy):
    def __init__(self, fast: int = 20, slow: int = 50):
        if fast >= slow:
            raise ValueError("fast period must be smaller than slow period")
        self.fast = fast
        self.slow = slow
        self.warmup = slow

    def target_position(self, candles: Sequence[Candle]) -> int:
        if len(candles) < self.slow:
            return FLAT
        closes = [c.close for c in candles]
        fast_avg = sum(closes[-self.fast :]) / self.fast
        slow_avg = sum(closes[-self.slow :]) / self.slow
        if fast_avg > slow_avg:
            return LONG
        if fast_avg < slow_avg:
            return SHORT
        return FLAT

    def describe(self) -> str:
        return f"SmaCrossover(fast={self.fast}, slow={self.slow})"
