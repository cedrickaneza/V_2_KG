from typing import Any, Dict, Type

from .base import FLAT, LONG, SHORT, Strategy
from .donchian_breakout import DonchianBreakout
from .rsi_mean_reversion import RsiMeanReversion
from .sma_crossover import SmaCrossover

STRATEGIES: Dict[str, Type[Strategy]] = {
    "sma_crossover": SmaCrossover,
    "rsi_mean_reversion": RsiMeanReversion,
    "donchian_breakout": DonchianBreakout,
}


def build_strategy(name: str, params: Dict[str, Any] | None = None) -> Strategy:
    """Create a strategy by its config name, e.g. build_strategy('sma_crossover', {'fast': 10})."""
    try:
        cls = STRATEGIES[name]
    except KeyError:
        known = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"unknown strategy '{name}' (available: {known})") from None
    return cls(**(params or {}))


__all__ = [
    "Strategy",
    "SmaCrossover",
    "RsiMeanReversion",
    "DonchianBreakout",
    "build_strategy",
    "STRATEGIES",
    "LONG",
    "SHORT",
    "FLAT",
]
