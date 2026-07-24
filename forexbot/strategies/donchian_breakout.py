"""Breakout: trade when price escapes its recent range (Donchian channel).

Logic (the classic "Turtle" style): if price closes above the highest high
of the last ``entry_period`` candles, something changed — go long and stay
until price closes below the lowest low of the last ``exit_period`` candles.
Mirror for shorts. A third *family* of behaviour next to trend-following
(SMA) and mean-reversion (RSI): breakouts win rarely but big, and chop
loses often but small.
"""

from __future__ import annotations

from typing import Sequence

from ..data.candles import Candle
from .base import FLAT, LONG, SHORT, Strategy


class DonchianBreakout(Strategy):
    def __init__(self, entry_period: int = 55, exit_period: int = 20):
        if exit_period >= entry_period:
            raise ValueError("exit_period must be smaller than entry_period")
        if exit_period < 2:
            raise ValueError("exit_period must be at least 2")
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.warmup = entry_period + 1
        self._stance = FLAT

    def reset(self) -> None:
        self._stance = FLAT

    def target_position(self, candles: Sequence[Candle]) -> int:
        if len(candles) < self.entry_period + 1:
            return self._stance

        # channels are built from candles BEFORE the latest one, so the
        # latest close is compared against a range it didn't help form
        prior = candles[:-1]
        close = candles[-1].close
        entry_high = max(c.high for c in prior[-self.entry_period :])
        entry_low = min(c.low for c in prior[-self.entry_period :])
        exit_high = max(c.high for c in prior[-self.exit_period :])
        exit_low = min(c.low for c in prior[-self.exit_period :])

        if self._stance == FLAT:
            if close > entry_high:
                self._stance = LONG
            elif close < entry_low:
                self._stance = SHORT
        elif self._stance == LONG and close < exit_low:
            self._stance = FLAT
        elif self._stance == SHORT and close > exit_high:
            self._stance = FLAT
        return self._stance

    def describe(self) -> str:
        return f"DonchianBreakout(entry={self.entry_period}, exit={self.exit_period})"
