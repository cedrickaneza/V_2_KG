"""Shared helpers for building candle series in tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Sequence

from forexbot.data.candles import Candle

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def candles_from_closes(closes: Sequence[float], spread: float = 0.0) -> List[Candle]:
    """Build hourly candles where open == previous close and high/low hug the range."""
    out: List[Candle] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        high = max(prev, close) + spread
        low = min(prev, close) - spread
        out.append(
            Candle(
                time=START + timedelta(hours=i),
                open=prev,
                high=high,
                low=low,
                close=close,
                volume=1000,
            )
        )
        prev = close
    return out


def trend(start: float, step: float, count: int) -> List[float]:
    return [start + step * i for i in range(count)]
