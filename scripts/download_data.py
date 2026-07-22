#!/usr/bin/env python3
"""Download real historical candles into a CSV for backtesting.

OANDA (forex), requires a free practice account API token:
    export OANDA_API_TOKEN="your-token-here"
    python scripts/download_data.py --broker oanda --instrument EUR_USD --granularity H1 --days 730

Alpaca (crypto), requires a free account (email + password, no ID
verification) at https://alpaca.markets/ -> API Keys:
    export ALPACA_API_KEY_ID="your-key-id"
    export ALPACA_API_SECRET_KEY="your-secret-key"
    python scripts/download_data.py --broker alpaca --instrument BTC/USD --granularity 1Hour --days 730
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forexbot.data.alpaca_feed import AlpacaCryptoFeed  # noqa: E402
from forexbot.data.alpaca_feed import GRANULARITY_SECONDS as ALPACA_GRANULARITY_SECONDS  # noqa: E402
from forexbot.data.candles import save_candles_csv  # noqa: E402
from forexbot.data.oanda_feed import GRANULARITY_SECONDS as OANDA_GRANULARITY_SECONDS  # noqa: E402
from forexbot.data.oanda_feed import OandaFeed  # noqa: E402

DEFAULTS = {
    "oanda": {"instrument": "EUR_USD", "granularity": "H1"},
    "alpaca": {"instrument": "BTC/USD", "granularity": "1Hour"},
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--broker", default="oanda", choices=["oanda", "alpaca"])
    parser.add_argument("--instrument", help="e.g. EUR_USD (oanda) or BTC/USD (alpaca)")
    parser.add_argument("--granularity", help="e.g. H1 (oanda) or 1Hour (alpaca)")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--out", help="output CSV (default: data/<instrument>_<granularity>.csv)")
    args = parser.parse_args()

    instrument = args.instrument or DEFAULTS[args.broker]["instrument"]
    granularity = args.granularity or DEFAULTS[args.broker]["granularity"]
    safe_instrument = instrument.replace("/", "")
    out = args.out or f"data/{safe_instrument}_{granularity}.csv"

    if args.broker == "oanda":
        if granularity not in OANDA_GRANULARITY_SECONDS:
            raise SystemExit(
                f"'{granularity}' isn't a valid OANDA granularity "
                f"(choose from: {', '.join(OANDA_GRANULARITY_SECONDS)})"
            )
        token = os.environ.get("OANDA_API_TOKEN", "")
        if not token:
            raise SystemExit(
                "Set the OANDA_API_TOKEN environment variable first.\n"
                "Get a free token: oanda.com -> demo account -> Manage API Access."
            )
        feed = OandaFeed(token, practice=True)
    else:
        if granularity not in ALPACA_GRANULARITY_SECONDS:
            raise SystemExit(
                f"'{granularity}' isn't a valid Alpaca timeframe "
                f"(choose from: {', '.join(ALPACA_GRANULARITY_SECONDS)})"
            )
        key_id = os.environ.get("ALPACA_API_KEY_ID", "")
        secret = os.environ.get("ALPACA_API_SECRET_KEY", "")
        if not key_id or not secret:
            raise SystemExit(
                "Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY first.\n"
                "Get free keys: alpaca.markets -> sign up -> API Keys."
            )
        feed = AlpacaCryptoFeed(key_id, secret)

    print(f"downloading {args.days} days of {instrument} {granularity} candles from {args.broker}...")
    candles = feed.download_history(instrument, granularity, args.days)
    if not candles:
        raise SystemExit("no candles returned — check the instrument name and your credentials")
    save_candles_csv(candles, out)
    print(f"wrote {len(candles)} candles to {out}")


if __name__ == "__main__":
    main()
