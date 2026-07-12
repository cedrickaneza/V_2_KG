#!/usr/bin/env python3
"""Generate SYNTHETIC hourly EUR/USD-like candles for demo backtests.

This is random-walk data with drifting trend regimes — it is NOT real
market data. It exists so the backtester works out of the box before you
download real history with scripts/download_data.py.

Usage:
    python scripts/generate_sample_data.py [--out data/sample_EURUSD_H1.csv] [--days 730]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forexbot.data.candles import Candle, save_candles_csv  # noqa: E402


def generate(days: int, seed: int = 42) -> list[Candle]:
    rng = random.Random(seed)
    price = 1.1000
    hourly_vol = 0.0009          # ~0.08% per hour, roughly EUR/USD-like
    drift = 0.0
    candles: list[Candle] = []
    t = datetime(2023, 1, 2, tzinfo=timezone.utc)
    end = t + timedelta(days=days)

    while t < end:
        # forex market is closed on weekends
        if t.weekday() >= 5:
            t += timedelta(hours=1)
            continue
        # occasionally switch trend regime (up / down / sideways)
        if rng.random() < 1 / 400:
            drift = rng.choice([-1.5e-5, 0.0, 1.5e-5])

        steps = [price]
        step_vol = hourly_vol / math.sqrt(8)
        for _ in range(8):
            steps.append(steps[-1] * (1 + rng.gauss(drift / 8, step_vol)))
        price = steps[-1]
        candles.append(
            Candle(
                time=t,
                open=steps[0],
                high=max(steps),
                low=min(steps),
                close=steps[-1],
                volume=float(rng.randint(500, 5000)),
            )
        )
        t += timedelta(hours=1)
    return candles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/sample_EURUSD_H1.csv")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    candles = generate(args.days, args.seed)
    save_candles_csv(candles, args.out)
    print(f"wrote {len(candles)} synthetic candles to {args.out}")
    print("REMINDER: this is fake data for testing the machinery, not for judging a strategy.")


if __name__ == "__main__":
    main()
