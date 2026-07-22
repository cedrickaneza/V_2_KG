#!/usr/bin/env python3
"""Start the trading bot (paper by default).

OANDA (forex):
    cp config/config.example.yaml config/config.yaml   # then edit it
    export OANDA_API_TOKEN="your-token-here"
    python scripts/run_bot.py --config config/config.yaml

Alpaca (crypto):
    cp config/config.example.crypto.yaml config/config.yaml   # then edit it
    export ALPACA_API_KEY_ID="your-key-id"
    export ALPACA_API_SECRET_KEY="your-secret-key"
    python scripts/run_bot.py --config config/config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forexbot.bot import TradingBot, setup_logging  # noqa: E402
from forexbot.config import load_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--once", action="store_true",
                        help="run a single decision cycle and exit — for daily-candle "
                             "setups where the bot is woken once a day instead of "
                             "running continuously")
    args = parser.parse_args()

    if not Path(args.config).exists():
        raise SystemExit(
            f"config file '{args.config}' not found.\n"
            "Copy config/config.example.yaml to config/config.yaml and edit it."
        )

    setup_logging()
    config = load_config(args.config)
    if config.broker == "alpaca":
        if not config.alpaca.api_key_id or not config.alpaca.api_secret_key:
            raise SystemExit(
                "Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY environment variables first."
            )
    else:
        if not config.oanda.token:
            raise SystemExit("Set the OANDA_API_TOKEN environment variable first.")
        if not config.oanda.account_id:
            raise SystemExit("Set oanda.account_id in your config file.")

    bot = TradingBot(config)
    if args.once:
        bot.run_once()
    else:
        bot.run_forever()


if __name__ == "__main__":
    main()
