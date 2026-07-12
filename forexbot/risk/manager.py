"""Risk management — the part that keeps the account alive.

Strategies decide *direction*; the RiskManager decides *size* and whether
trading is allowed at all:

* position sizing: risk a fixed small fraction of equity per trade
* stop distance:   a multiple of ATR, so stops adapt to volatility
* daily loss cap:  stop opening new trades after a bad day
* kill switch:     halt the bot entirely if drawdown exceeds a hard limit

The sizing formula ``units = risk_amount / stop_distance`` is exact when the
account currency equals the pair's quote currency (e.g. a USD account trading
EUR_USD). For cross pairs it is an approximation — acceptable while learning,
and the ``max_units`` cap bounds the error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence, Tuple

from ..data.candles import Candle
from ..indicators import atr


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.005      # fraction of equity risked per trade (0.5%)
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0   # stop-loss distance = 2 x ATR
    atr_tp_multiplier: float = 3.0     # take-profit distance = 3 x ATR (1.5:1 reward:risk)
    max_daily_loss_pct: float = 0.02   # stop opening trades after losing 2% in a day
    max_drawdown_pct: float = 0.10     # kill switch: halt for good at -10% from peak
    max_units: int = 100_000           # hard cap on position size (1 standard lot)

    def __post_init__(self) -> None:
        if not 0 < self.risk_per_trade <= 0.02:
            raise ValueError(
                "risk_per_trade must be in (0, 0.02]; risking more than 2% "
                "per trade is how accounts die"
            )
        if self.atr_stop_multiplier <= 0 or self.atr_tp_multiplier <= 0:
            raise ValueError("ATR multipliers must be positive")


class RiskManager:
    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()
        self.peak_equity: Optional[float] = None
        self.day_start_equity: Optional[float] = None
        self._current_day: Optional[str] = None
        self.halted = False
        self.halt_reason = ""

    # -- state tracking ------------------------------------------------

    def update(self, now: datetime, equity: float) -> None:
        """Feed the latest account equity. Call once per candle/cycle."""
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        day = now.strftime("%Y-%m-%d")
        if day != self._current_day:
            self._current_day = day
            self.day_start_equity = equity
        if (
            not self.halted
            and self.peak_equity
            and equity <= self.peak_equity * (1 - self.config.max_drawdown_pct)
        ):
            self.halted = True
            self.halt_reason = (
                f"drawdown kill switch: equity {equity:.2f} is more than "
                f"{self.config.max_drawdown_pct:.0%} below peak {self.peak_equity:.2f}"
            )

    # -- gates ----------------------------------------------------------

    def can_open_trade(self, equity: float) -> Tuple[bool, str]:
        """May a NEW trade be opened right now? Returns (allowed, reason)."""
        if self.halted:
            return False, self.halt_reason
        if self.day_start_equity:
            daily_limit = self.day_start_equity * (1 - self.config.max_daily_loss_pct)
            if equity <= daily_limit:
                return False, (
                    f"daily loss limit reached (equity {equity:.2f} <= "
                    f"{daily_limit:.2f}); no new trades until tomorrow"
                )
        return True, "ok"

    # -- sizing -----------------------------------------------------------

    def stop_distance(self, candles: Sequence[Candle]) -> Optional[float]:
        """Stop-loss distance in price units, derived from current volatility."""
        values = atr(candles, self.config.atr_period)
        latest = values[-1] if values else None
        if latest is None or latest <= 0:
            return None
        return latest * self.config.atr_stop_multiplier

    def take_profit_distance(self, stop_dist: float) -> float:
        return stop_dist * self.config.atr_tp_multiplier / self.config.atr_stop_multiplier

    def position_size(self, equity: float, stop_dist: float) -> int:
        """Units such that hitting the stop loses ~risk_per_trade of equity."""
        if stop_dist <= 0 or equity <= 0:
            return 0
        units = int(equity * self.config.risk_per_trade / stop_dist)
        return min(units, self.config.max_units)
