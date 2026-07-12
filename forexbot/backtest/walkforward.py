"""Walk-forward validation — the antidote to curve-fitting.

The #1 way beginners fool themselves: tune parameters until the backtest
looks great, then discover the "edge" was memorised noise. Walk-forward
simulates how you would really have traded:

    [ train 2000 candles ][ test 500 ]
                [ train 2000 candles ][ test 500 ]
                            [ train 2000 candles ][ test 500 ]  ...

For each fold, every parameter combination is backtested on the TRAIN
window only; the best one is then run on the unseen TEST window. Stitching
the test windows together yields an out-of-sample (OOS) equity curve — the
closest a backtest can get to honest.

Read the result like this:
* OOS metrics >= 0 and not far below the average train metrics -> the edge
  might be real; graduate it to paper trading.
* great train numbers, poor OOS numbers -> curve-fit. Discard the idea and
  be glad you found out for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..data.candles import Candle
from ..execution.broker import ClosedTrade
from ..risk.manager import RiskConfig, RiskManager
from ..strategies import build_strategy
from .engine import BacktestEngine
from .metrics import compute_metrics


def expand_grid(grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """{'fast': [10, 20], 'slow': [50]} -> [{'fast':10,'slow':50}, {'fast':20,'slow':50}]"""
    keys = sorted(grid)
    return [dict(zip(keys, values)) for values in product(*(grid[k] for k in keys))]


@dataclass
class Fold:
    index: int
    train_range: Tuple[datetime, datetime]
    test_range: Tuple[datetime, datetime]
    best_params: Dict[str, Any]
    train_return_pct: float     # of the selected params, on the train window
    test_return_pct: float      # same params, unseen data
    test_trades: int


@dataclass
class WalkForwardResult:
    folds: List[Fold] = field(default_factory=list)
    oos_equity: List[Tuple[datetime, float]] = field(default_factory=list)
    oos_trades: List[ClosedTrade] = field(default_factory=list)
    oos_metrics: Dict[str, float] = field(default_factory=dict)
    selection_metric: str = "net_profit"

    @property
    def avg_train_return_pct(self) -> float:
        if not self.folds:
            return 0.0
        return sum(f.train_return_pct for f in self.folds) / len(self.folds)


def _score(metrics: Dict[str, float], key: str) -> float:
    value = metrics[key]
    if value == float("inf"):  # profit_factor with zero losses
        return 1e9
    return value


def run_walk_forward(
    strategy_name: str,
    grid: Dict[str, List[Any]],
    candles: Sequence[Candle],
    *,
    train_size: int = 2000,
    test_size: int = 500,
    starting_balance: float = 10_000.0,
    spread: float = 0.00008,
    risk_config: Optional[RiskConfig] = None,
    selection_metric: str = "net_profit",   # or "sharpe" / "profit_factor"
    granularity: str = "H1",
) -> WalkForwardResult:
    risk_config = risk_config or RiskConfig()

    combos = []
    for params in expand_grid(grid):
        try:
            build_strategy(strategy_name, params)  # validates the combination
            combos.append(params)
        except (ValueError, TypeError):
            continue  # e.g. fast >= slow — skip invalid corners of the grid
    if not combos:
        raise ValueError("no valid parameter combination in the grid")
    if len(candles) < train_size + test_size:
        raise ValueError(
            f"need at least train_size+test_size={train_size + test_size} candles, "
            f"got {len(candles)}"
        )

    result = WalkForwardResult(selection_metric=selection_metric)
    equity = starting_balance
    fold_index = 0
    cursor = train_size

    while cursor + test_size <= len(candles):
        train = candles[cursor - train_size : cursor]

        # -- pick the best params on the train window only ----------------
        best_params, best_score, best_train_return = None, float("-inf"), 0.0
        for params in combos:
            engine = BacktestEngine(
                build_strategy(strategy_name, params),
                RiskManager(risk_config),      # fresh manager per run
                starting_balance=starting_balance,
                spread=spread,
                granularity=granularity,
            )
            try:
                m = engine.run(train).metrics
            except ValueError:
                continue  # not enough candles for this combo's warmup
            score = _score(m, selection_metric)
            if score > best_score:
                best_params, best_score = params, score
                best_train_return = m["total_return_pct"]
        if best_params is None:
            raise ValueError("train window too small for every combo's warmup")

        # -- run the winner on the unseen test window ---------------------
        strategy = build_strategy(strategy_name, best_params)
        oos_engine = BacktestEngine(
            strategy,
            RiskManager(risk_config),
            starting_balance=equity,           # compound across folds
            spread=spread,
            granularity=granularity,
        )
        # prefix the test window with exactly the warmup the engine needs,
        # so indicators are ready and trading starts at the first test candle
        warm = max(strategy.warmup, risk_config.atr_period + 2)
        run_slice = list(candles[cursor - warm : cursor + test_size])
        oos = oos_engine.run(run_slice)

        test = candles[cursor : cursor + test_size]
        result.folds.append(
            Fold(
                index=fold_index,
                train_range=(train[0].time, train[-1].time),
                test_range=(test[0].time, test[-1].time),
                best_params=best_params,
                train_return_pct=best_train_return,
                test_return_pct=(oos.metrics["final_equity"] / equity - 1.0) * 100,
                test_trades=oos.metrics["num_trades"],
            )
        )
        result.oos_equity.extend(oos.equity_curve)
        result.oos_trades.extend(oos.trades)
        equity = oos.metrics["final_equity"]

        fold_index += 1
        cursor += test_size

    result.oos_metrics = compute_metrics(
        result.oos_equity, result.oos_trades, starting_balance, granularity
    )
    return result
