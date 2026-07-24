"""Technical indicators implemented on plain Python lists.

Each function returns a list the same length as its input, with ``None``
in positions where there is not yet enough history to compute a value.
Keeping the output aligned with the input makes off-by-one bugs obvious.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from .data.candles import Candle


def sma(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Simple moving average."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: List[Optional[float]] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Exponential moving average, seeded with the SMA of the first window."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(values: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index (Wilder's smoothing).

    RSI ranges 0..100. Readings under ~30 are conventionally "oversold",
    over ~70 "overbought".
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period

    def to_rsi(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period + 1, n):
        delta = values[i] - values[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = to_rsi(avg_gain, avg_loss)
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> List[Optional[float]]:
    """Average True Range (Wilder's smoothing) — a volatility measure.

    We use it to size stop-losses: a stop placed a multiple of ATR away
    adapts to how much the market normally moves.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(candles)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out

    true_ranges: List[float] = [0.0] * n
    for i in range(1, n):
        c = candles[i]
        prev_close = candles[i - 1].close
        true_ranges[i] = max(
            c.high - c.low,
            abs(c.high - prev_close),
            abs(c.low - prev_close),
        )

    current = sum(true_ranges[1 : period + 1]) / period
    out[period] = current
    for i in range(period + 1, n):
        current = (current * (period - 1) + true_ranges[i]) / period
        out[i] = current
    return out
