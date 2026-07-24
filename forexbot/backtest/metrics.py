"""Performance metrics for a backtest run.

The numbers every trader checks first:
* total return / max drawdown — how much it made vs. how painful the ride was
* win rate + profit factor    — how it made the money
* Sharpe ratio                — return per unit of volatility (>1 is decent)
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

from ..execution.broker import ClosedTrade

# Forex (OANDA-style keys): ~24 hourly candles x ~260 trading days.
# Crypto (Alpaca-style keys): trades every day, so a 365-day year.
PERIODS_PER_YEAR = {
    "M1": 60 * 24 * 260,
    "M5": 12 * 24 * 260,
    "M15": 4 * 24 * 260,
    "M30": 2 * 24 * 260,
    "H1": 24 * 260,
    "H4": 6 * 260,
    "D": 260,
    "1Min": 60 * 24 * 365,
    "5Min": 12 * 24 * 365,
    "15Min": 4 * 24 * 365,
    "30Min": 2 * 24 * 365,
    "1Hour": 24 * 365,
    "4Hour": 6 * 365,
    "1Day": 365,
}


def max_drawdown(equity: Sequence[float]) -> float:
    """Worst peak-to-trough drop, as a fraction (0.15 = -15%)."""
    peak = float("-inf")
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def sharpe_ratio(equity: Sequence[float], periods_per_year: int) -> float:
    if len(equity) < 3:
        return 0.0
    returns = [
        (equity[i] / equity[i - 1]) - 1.0
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def compute_metrics(
    equity_curve: Sequence[Tuple[datetime, float]],
    trades: Sequence[ClosedTrade],
    starting_balance: float,
    granularity: str = "H1",
) -> Dict[str, float]:
    equity: List[float] = [starting_balance] + [e for _, e in equity_curve]
    final = equity[-1]

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)

    return {
        "starting_balance": starting_balance,
        "final_equity": final,
        "net_profit": final - starting_balance,
        "total_return_pct": (final / starting_balance - 1.0) * 100 if starting_balance else 0.0,
        "num_trades": len(trades),
        "win_rate_pct": (len(wins) / len(trades) * 100) if trades else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "max_drawdown_pct": max_drawdown(equity) * 100,
        "sharpe": sharpe_ratio(equity, PERIODS_PER_YEAR.get(granularity, 24 * 260)),
    }


def format_report(metrics: Dict[str, float], title: str = "Backtest report") -> str:
    pf = metrics["profit_factor"]
    pf_str = "inf" if math.isinf(pf) else f"{pf:.2f}"
    lines = [
        f"===== {title} =====",
        f"Starting balance : {metrics['starting_balance']:>12,.2f}",
        f"Final equity     : {metrics['final_equity']:>12,.2f}",
        f"Net profit       : {metrics['net_profit']:>12,.2f}  ({metrics['total_return_pct']:+.2f}%)",
        f"Trades           : {metrics['num_trades']:>12d}",
        f"Win rate         : {metrics['win_rate_pct']:>11.1f}%",
        f"Profit factor    : {pf_str:>12s}",
        f"Avg win / loss   : {metrics['avg_win']:>+12,.2f} / {metrics['avg_loss']:+,.2f}",
        f"Max drawdown     : {metrics['max_drawdown_pct']:>11.1f}%",
        f"Sharpe ratio     : {metrics['sharpe']:>12.2f}",
    ]
    return "\n".join(lines)
