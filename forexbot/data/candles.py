"""Candle (OHLC price bar) type and CSV persistence.

A "candle" summarises price movement over a fixed interval (e.g. one hour):
open (first price), high, low, close (last price) and traded volume.
All timestamps are timezone-aware UTC.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

CSV_HEADER = ["time", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class Candle:
    time: datetime  # start of the interval, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.time.tzinfo is None:
            object.__setattr__(self, "time", self.time.replace(tzinfo=timezone.utc))


def parse_time(value: str) -> datetime:
    """Parse ISO-8601 timestamps, tolerating 'Z' suffixes and nanoseconds
    (OANDA sends e.g. '2024-01-01T00:00:00.000000000Z')."""
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    # datetime.fromisoformat only accepts up to microseconds (6 digits)
    if "." in value:
        head, _, tail = value.partition(".")
        frac = ""
        offset = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                frac += ch
            else:
                offset = tail[i:]
                break
        value = f"{head}.{frac[:6].ljust(6, '0')}{offset}"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_candles_csv(path: str | Path) -> List[Candle]:
    candles: List[Candle] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append(
                Candle(
                    time=parse_time(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0.0),
                )
            )
    candles.sort(key=lambda c: c.time)
    return candles


def save_candles_csv(candles: Iterable[Candle], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for c in candles:
            writer.writerow(
                [c.time.isoformat(), f"{c.open:.6f}", f"{c.high:.6f}",
                 f"{c.low:.6f}", f"{c.close:.6f}", f"{c.volume:g}"]
            )
