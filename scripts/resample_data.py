#!/usr/bin/env python3
"""Resample a candle CSV to a coarser timeframe (e.g. 1-hour -> 4-hour bars).

Why you'd want this: trading costs are charged per trade, so on fee-heavy
venues (crypto) a strategy often only has a chance on coarser bars where it
trades less. Resampling locally beats re-downloading.

    python scripts/resample_data.py --in data/BTCUSD_1Hour.csv --hours 4
    python scripts/resample_data.py --in data/BTCUSD_1Hour.csv --hours 24
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forexbot.data.candles import Candle, load_candles_csv, save_candles_csv  # noqa: E402


def resample(candles: list[Candle], hours: int) -> list[Candle]:
    """Aggregate candles into `hours`-wide bars aligned to midnight UTC.

    Only complete groups are kept: a bucket must contain every source bar
    it spans, so a half-filled bucket at either edge of the data (or around
    a data gap) is dropped rather than emitted as a misleading bar.
    """
    buckets: dict = {}
    for c in candles:
        t = c.time.astimezone(timezone.utc)
        anchor = t.replace(hour=(t.hour // hours) * hours if hours < 24 else 0,
                           minute=0, second=0, microsecond=0)
        buckets.setdefault(anchor, []).append(c)

    per_bucket = hours  # source is hourly
    out = []
    for anchor in sorted(buckets):
        group = sorted(buckets[anchor], key=lambda c: c.time)
        if len(group) != per_bucket:
            continue
        out.append(
            Candle(
                time=anchor,
                open=group[0].open,
                high=max(c.high for c in group),
                low=min(c.low for c in group),
                close=group[-1].close,
                volume=sum(c.volume for c in group),
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", required=True, help="source CSV of HOURLY candles")
    parser.add_argument("--hours", type=int, required=True, choices=[2, 3, 4, 6, 8, 12, 24],
                        help="bar width of the output")
    parser.add_argument("--out", help="output CSV (default: derived from input name)")
    args = parser.parse_args()

    candles = load_candles_csv(args.src)
    step = candles[1].time - candles[0].time if len(candles) > 1 else None
    if step != timedelta(hours=1):
        raise SystemExit(f"expected hourly source data, but bar spacing is {step}")

    label = "1Day" if args.hours == 24 else f"{args.hours}Hour"
    out_path = args.out or str(Path(args.src).with_name(
        Path(args.src).stem.rsplit("_", 1)[0] + f"_{label}.csv"
    ))
    resampled = resample(candles, args.hours)
    save_candles_csv(resampled, out_path)
    print(f"{len(candles)} hourly bars -> {len(resampled)} {label} bars -> {out_path}")


if __name__ == "__main__":
    main()
