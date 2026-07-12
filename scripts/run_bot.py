#!/usr/bin/env python3
"""Start the trading bot (paper by default).

    cp config/config.example.yaml config/config.yaml   # then edit it
    export OANDA_API_TOKEN="your-token-here"
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
    args = parser.parse_args()

    if not Path(args.config).exists():
        raise SystemExit(
            f"config file '{args.config}' not found.\n"
            "Copy config/config.example.yaml to config/config.yaml and edit it."
        )

    setup_logging()
    config = load_config(args.config)
    if not config.oanda.token:
        raise SystemExit("Set the OANDA_API_TOKEN environment variable first.")
    if not config.oanda.account_id:
        raise SystemExit("Set oanda.account_id in your config file.")

    TradingBot(config).run_forever()


if __name__ == "__main__":
    main()
