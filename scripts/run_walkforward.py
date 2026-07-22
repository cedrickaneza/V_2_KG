#!/usr/bin/env python3
"""Walk-forward validation: optimise on the past, verify on the unseen future.

This answers the question a plain backtest can't: "would these parameters
have worked on data they were NOT tuned on?" — the closest offline proxy
for real trading.

Examples:
    python scripts/run_walkforward.py --data data/EUR_USD_H1.csv \\
        --strategy sma_crossover --grid fast=10,20,30 --grid slow=50,100,200

    python scripts/run_walkforward.py --data data/EUR_USD_H1.csv \\
        --strategy donchian_breakout --grid entry_period=20,55,100 \\
        --grid exit_period=10,20 --select sharpe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forexbot.backtest.metrics import format_report  # noqa: E402
from forexbot.backtest.walkforward import run_walk_forward  # noqa: E402
from forexbot.data.candles import load_candles_csv  # noqa: E402
from forexbot.risk.manager import RiskConfig  # noqa: E402
from forexbot.strategies import STRATEGIES  # noqa: E402


def parse_grid(pairs: list[str]) -> dict:
    grid: dict = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        if not raw:
            raise SystemExit(f"--grid expects key=v1,v2,..., got '{pair}'")
        values = []
        for token in raw.split(","):
            try:
                values.append(int(token))
            except ValueError:
                values.append(float(token))
        grid[key] = values
    return grid


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", required=True)
    parser.add_argument("--strategy", default="sma_crossover", choices=sorted(STRATEGIES))
    parser.add_argument("--grid", action="append", default=[], metavar="KEY=V1,V2,...",
                        help="parameter values to search, repeatable")
    parser.add_argument("--train", type=int, default=2000, help="train window (candles)")
    parser.add_argument("--test", type=int, default=500, help="test window (candles)")
    parser.add_argument("--select", default="net_profit",
                        choices=["net_profit", "sharpe", "profit_factor"],
                        help="metric used to pick parameters on each train window")
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--spread", type=float, default=0.00008)
    parser.add_argument("--risk-per-trade", type=float, default=0.005)
    parser.add_argument("--granularity", default="H1")
    parser.add_argument("--long-only", action="store_true",
                        help="reject short signals, matching a venue that can't short (e.g. Alpaca crypto)")
    args = parser.parse_args()

    if not args.grid:
        raise SystemExit("provide at least one --grid, e.g. --grid fast=10,20,30")

    candles = load_candles_csv(args.data)
    print(f"data     : {args.data} ({len(candles)} candles)")
    print(f"strategy : {args.strategy}, selecting by {args.select}"
          + (", long-only" if args.long_only else ""))
    print(f"windows  : train {args.train} / test {args.test} candles\n")

    result = run_walk_forward(
        args.strategy,
        parse_grid(args.grid),
        candles,
        train_size=args.train,
        test_size=args.test,
        starting_balance=args.balance,
        spread=args.spread,
        risk_config=RiskConfig(risk_per_trade=args.risk_per_trade),
        selection_metric=args.select,
        granularity=args.granularity,
        long_only=args.long_only,
    )

    print(f"{'fold':<5} {'test period':<26} {'chosen params':<34} {'train%':>8} {'test%':>8} {'trades':>7}")
    print("-" * 92)
    for f in result.folds:
        period = f"{f.test_range[0]:%Y-%m-%d} .. {f.test_range[1]:%Y-%m-%d}"
        params = ", ".join(f"{k}={v}" for k, v in sorted(f.best_params.items()))
        print(f"{f.index:<5} {period:<26} {params:<34} {f.train_return_pct:>+7.1f}% "
              f"{f.test_return_pct:>+7.1f}% {f.test_trades:>7}")

    print()
    print(format_report(result.oos_metrics, title="Out-of-sample (honest) result"))
    print(f"\nAvg train return per fold : {result.avg_train_return_pct:+.1f}%")
    print(f"Avg test  return per fold : "
          f"{result.oos_metrics['total_return_pct'] / max(len(result.folds), 1):+.1f}%")
    print(
        "\nHow to read this: if the test column is consistently far below the train\n"
        "column, the parameters were memorising the past (curve-fit) — discard the\n"
        "idea. Only strategies whose OUT-OF-SAMPLE result is acceptable deserve\n"
        "paper trading."
    )


if __name__ == "__main__":
    main()
