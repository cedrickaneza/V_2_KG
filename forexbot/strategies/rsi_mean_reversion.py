"""Mean-reversion: buy oversold, sell overbought, exit at neutral RSI.

Logic: forex pairs often oscillate around a fair value. When RSI drops
below ``oversold`` the move may be overdone -> go long and hold until RSI
recovers to ``exit_level``. Mirror logic for shorts. This style wins often
but loses big when a real trend steamrolls the reversion bet — which is
exactly why the risk manager's stop-loss matters.
"""

from __future__ import annotations

from typing import Sequence

from ..data.candles import Candle
from ..indicators import rsi
from .base import FLAT, LONG, SHORT, Strategy


class RsiMeanReversion(Strategy):
    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        exit_level: float = 50.0,
    ):
        if not (0 < oversold < exit_level < overbought < 100):
            raise ValueError("expected 0 < oversold < exit_level < overbought < 100")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.exit_level = exit_level
        # Wilder smoothing needs extra history beyond `period` to stabilise
        self.warmup = period * 5
        self._stance = FLAT

    def reset(self) -> None:
        self._stance = FLAT

    def target_position(self, candles: Sequence[Candle]) -> int:
        closes = [c.close for c in candles]
        value = rsi(closes, self.period)[-1] if len(closes) > self.period else None
        if value is None:
            return self._stance

        if self._stance == FLAT:
            if value < self.oversold:
                self._stance = LONG
            elif value > self.overbought:
                self._stance = SHORT
        elif self._stance == LONG and value >= self.exit_level:
            self._stance = FLAT
        elif self._stance == SHORT and value <= self.exit_level:
            self._stance = FLAT
        return self._stance

    def describe(self) -> str:
        return (
            f"RsiMeanReversion(period={self.period}, oversold={self.oversold}, "
            f"overbought={self.overbought}, exit={self.exit_level})"
        )
