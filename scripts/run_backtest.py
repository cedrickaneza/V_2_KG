#!/usr/bin/env python3
"""Run a strategy over historical candles and print a performance report.

Examples:
    python scripts/run_backtest.py --data data/sample_EURUSD_H1.csv
    python scripts/run_backtest.py --data data/EUR_USD_H1.csv --strategy rsi_mean_reversion
    python scripts/run_backtest.py --data data/EUR_USD_H1.csv --strategy sma_crossover \\
        --param fast=10 --param slow=40 --balance 5000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forexbot.backtest.engine import BacktestEngine  # noqa: E402
from forexbot.backtest.metrics import format_report  # noqa: E402
from forexbot.data.candles import load_candles_csv  # noqa: E402
from forexbot.risk.manager import RiskConfig, RiskManager  # noqa: E402
from forexbot.strategies import STRATEGIES, build_strategy  # noqa: E402


def parse_params(pairs: list[str]) -> dict:
    params: dict = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if not value:
            raise SystemExit(f"--param expects key=value, got '{pair}'")
        try:
            params[key] = int(value)
        except ValueError:
            try:
                params[key] = float(value)
            except ValueError:
                params[key] = value
    return params


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", required=True, help="CSV of candles (time,open,high,low,close,volume)")
    parser.add_argument("--strategy", default="sma_crossover", choices=sorted(STRATEGIES))
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                        help="strategy parameter, repeatable (e.g. --param fast=10)")
    parser.add_argument("--balance", type=float, default=10_000.0, help="starting balance")
    parser.add_argument("--spread", type=float, default=0.00008, help="bid/ask spread in price units")
    parser.add_argument("--spread-pct", type=float, default=0.0,
                        help="round-trip cost as a FRACTION of price (crypto fees; "
                             "e.g. 0.005 = 0.5%% round trip). Overrides --spread when set")
    parser.add_argument("--risk-per-trade", type=float, default=0.005)
    parser.add_argument("--granularity", default="H1", help="candle size of the data (for Sharpe annualisation)")
    parser.add_argument("--equity-out", help="optional CSV path to save the equity curve")
    parser.add_argument("--long-only", action="store_true",
                        help="reject short signals, matching a venue that can't short (e.g. Alpaca crypto)")
    args = parser.parse_args()

    candles = load_candles_csv(args.data)
    strategy = build_strategy(args.strategy, parse_params(args.param))
    risk = RiskManager(RiskConfig(risk_per_trade=args.risk_per_trade))
    engine = BacktestEngine(
        strategy, risk,
        starting_balance=args.balance,
        spread=args.spread,
        granularity=args.granularity,
        long_only=args.long_only,
        spread_pct=args.spread_pct,
    )

    cost = (f"{args.spread_pct:.3%} of price per round trip"
            if args.spread_pct else f"spread {args.spread}")
    print(f"data      : {args.data} ({len(candles)} candles, "
          f"{candles[0].time:%Y-%m-%d} .. {candles[-1].time:%Y-%m-%d})")
    print(f"strategy  : {strategy.describe()}")
    print(f"risk      : {args.risk_per_trade:.2%} per trade, {cost}"
          + (", long-only" if args.long_only else ""))
    print()

    result = engine.run(candles)
    print(format_report(result.metrics))
    if result.skipped_signals:
        print(f"\n(risk manager blocked {result.skipped_signals} entries)")

    if args.equity_out:
        import csv
        with open(args.equity_out, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "equity"])
            for t, e in result.equity_curve:
                writer.writerow([t.isoformat(), f"{e:.2f}"])
        print(f"equity curve saved to {args.equity_out}")

    print(
        "\nNOTE: backtests flatter every strategy — real trading adds slippage,\n"
        "missed fills and changing market conditions. Paper trade before going live."
    )


if __name__ == "__main__":
    main()
