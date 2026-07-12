#!/usr/bin/env python3
"""Download real historical candles from OANDA into a CSV for backtesting.

Requires a (free) OANDA practice account API token:
    export OANDA_API_TOKEN="your-token-here"
    python scripts/download_data.py --instrument EUR_USD --granularity H1 --days 730
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forexbot.data.candles import save_candles_csv  # noqa: E402
from forexbot.data.oanda_feed import GRANULARITY_SECONDS, OandaFeed  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", default="EUR_USD", help="e.g. EUR_USD, GBP_USD, USD_JPY")
    parser.add_argument("--granularity", default="H1", choices=sorted(GRANULARITY_SECONDS))
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--out", help="output CSV (default: data/<instrument>_<granularity>.csv)")
    args = parser.parse_args()

    token = os.environ.get("OANDA_API_TOKEN", "")
    if not token:
        raise SystemExit(
            "Set the OANDA_API_TOKEN environment variable first.\n"
            "Get a free token: oanda.com -> demo account -> Manage API Access."
        )

    out = args.out or f"data/{args.instrument}_{args.granularity}.csv"
    feed = OandaFeed(token, practice=True)
    print(f"downloading {args.days} days of {args.instrument} {args.granularity} candles...")
    candles = feed.download_history(args.instrument, args.granularity, args.days)
    if not candles:
        raise SystemExit("no candles returned — check the instrument name and your token")
    save_candles_csv(candles, out)
    print(f"wrote {len(candles)} candles to {out}")


if __name__ == "__main__":
    main()
