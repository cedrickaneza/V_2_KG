"""Backtest engine: replay historical candles through a strategy.

Anti-lookahead rule: the decision for candle N uses only candles 0..N-1
and executes at candle N's OPEN. The strategy can never see a price that
had not happened yet at decision time.

Per-candle sequence (mirrors what the live bot does each cycle):
    1. resolve stop-loss / take-profit hits inside the new candle
    2. mark equity, update the risk manager (daily loss / kill switch)
    3. ask the strategy for its desired stance
    4. if it differs from the held position: close / open with ATR-based
       stop-loss, take-profit, and risk-based position size

Pass ``long_only=True`` when backtesting for a venue that cannot short
(e.g. Alpaca crypto): a SHORT signal is clamped to FLAT before it ever
reaches the broker, so the reported performance reflects trades that
venue could actually place — not a strategy variant it can't execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

from ..data.candles import Candle
from ..execution.broker import ClosedTrade
from ..execution.paper_broker import PaperBroker
from ..risk.manager import RiskManager
from ..strategies.base import FLAT, Strategy
from .metrics import compute_metrics


@dataclass
class BacktestResult:
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    trades: List[ClosedTrade] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    skipped_signals: int = 0  # entries blocked by the risk manager


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        risk: RiskManager,
        starting_balance: float = 10_000.0,
        spread: float = 0.00008,
        lookback: int = 300,
        granularity: str = "H1",
        long_only: bool = False,
        spread_pct: float = 0.0,
    ):
        self.strategy = strategy
        self.risk = risk
        self.starting_balance = starting_balance
        self.spread = spread
        self.spread_pct = spread_pct
        # window of history handed to the strategy each step (keeps runs fast)
        self.lookback = max(lookback, strategy.warmup, risk.config.atr_period + 2)
        self.granularity = granularity
        self.long_only = long_only

    def run(self, candles: Sequence[Candle], instrument: str = "EUR_USD") -> BacktestResult:
        warmup = max(self.strategy.warmup, self.risk.config.atr_period + 2)
        if len(candles) <= warmup + 1:
            raise ValueError(
                f"need more than {warmup + 1} candles, got {len(candles)}"
            )

        self.strategy.reset()
        broker = PaperBroker(
            self.starting_balance, self.spread,
            long_only=self.long_only, spread_pct=self.spread_pct,
        )
        result = BacktestResult()

        for i in range(warmup, len(candles)):
            candle = candles[i]                       # candle we are trading INTO
            window = candles[max(0, i - self.lookback) : i]  # info known beforehand

            broker.process_candle(candle)             # SL/TP that this candle triggers
            equity_open = broker.equity(candle.open)
            self.risk.update(candle.time, equity_open)

            stance = self.strategy.target_position(window)
            if self.long_only and stance < 0:
                stance = FLAT
            pos = broker.get_position(instrument)
            held = 0 if pos is None else (1 if pos.units > 0 else -1)

            if stance != held:
                if pos is not None:
                    broker.close_position(instrument, reason="signal")
                if stance != 0:
                    allowed, _reason = self.risk.can_open_trade(broker.equity(candle.open))
                    if not allowed:
                        result.skipped_signals += 1
                    else:
                        stop_dist = self.risk.stop_distance(window)
                        if stop_dist:
                            units = self.risk.position_size(
                                broker.equity(candle.open), stop_dist
                            )
                            if units > 0:
                                tp_dist = self.risk.take_profit_distance(stop_dist)
                                entry = candle.open
                                if stance > 0:
                                    sl, tp = entry - stop_dist, entry + tp_dist
                                else:
                                    sl, tp = entry + stop_dist, entry - tp_dist
                                broker.market_order(
                                    instrument, units * stance, stop_loss=sl, take_profit=tp
                                )

            result.equity_curve.append((candle.time, broker.equity(candle.close)))

        if broker.get_position(instrument) is not None:
            broker.close_position(instrument, reason="end_of_data")
            result.equity_curve[-1] = (candles[-1].time, broker.equity(candles[-1].close))

        result.trades = broker.trades
        result.metrics = compute_metrics(
            result.equity_curve, result.trades, self.starting_balance, self.granularity
        )
        return result
