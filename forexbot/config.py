"""Configuration loading.

Settings live in a YAML file (see config/config.example.yaml). The OANDA
API token is read from the OANDA_API_TOKEN environment variable — secrets
never belong in files that could be committed to git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .risk.manager import RiskConfig


@dataclass
class OandaSettings:
    account_id: str = ""
    token: str = ""


@dataclass
class AlpacaSettings:
    api_key_id: str = ""
    api_secret_key: str = ""
    entry: str = "limit"              # "limit" = cheaper maker fees with market fallback


@dataclass
class AppConfig:
    broker: str = "oanda"              # "oanda" (forex) or "alpaca" (crypto, long-only)
    mode: str = "practice"            # "practice" (demo money) or "live"
    dry_run: bool = True              # log orders instead of sending them
    instruments: List[str] = field(default_factory=lambda: ["EUR_USD"])
    granularity: str = "H1"
    lookback: int = 300               # candles of history given to the strategy
    strategy_name: str = "sma_crossover"
    strategy_params: Dict[str, Any] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    oanda: OandaSettings = field(default_factory=OandaSettings)
    alpaca: AlpacaSettings = field(default_factory=AlpacaSettings)


def load_config(path: str | Path) -> AppConfig:
    import yaml  # imported here so backtesting works without PyYAML installed

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    broker = str(raw.get("broker", "oanda")).lower()
    if broker not in ("oanda", "alpaca"):
        raise ValueError(f"broker must be 'oanda' or 'alpaca', got '{broker}'")

    mode = str(raw.get("mode", "practice")).lower()
    if mode not in ("practice", "live"):
        raise ValueError(f"mode must be 'practice' or 'live', got '{mode}'")

    strategy = raw.get("strategy") or {}
    risk_raw = raw.get("risk") or {}
    oanda_raw = raw.get("oanda") or {}
    alpaca_raw = raw.get("alpaca") or {}

    # `instruments: [BTC/USD, ETH/USD]` (list) or legacy `instrument: EUR_USD`
    if raw.get("instruments"):
        instruments = [str(x) for x in raw["instruments"]]
    else:
        instruments = [str(raw.get("instrument", "EUR_USD"))]

    entry = str(alpaca_raw.get("entry", "limit")).lower()
    if entry not in ("market", "limit"):
        raise ValueError(f"alpaca.entry must be 'market' or 'limit', got '{entry}'")

    return AppConfig(
        broker=broker,
        mode=mode,
        dry_run=bool(raw.get("dry_run", True)),
        instruments=instruments,
        granularity=str(raw.get("granularity", "H1")),
        lookback=int(raw.get("lookback", 300)),
        strategy_name=str(strategy.get("name", "sma_crossover")),
        strategy_params=dict(strategy.get("params") or {}),
        risk=RiskConfig(**risk_raw),
        oanda=OandaSettings(
            account_id=str(oanda_raw.get("account_id", "")),
            token=os.environ.get("OANDA_API_TOKEN", ""),
        ),
        alpaca=AlpacaSettings(
            api_key_id=os.environ.get("ALPACA_API_KEY_ID", ""),
            api_secret_key=os.environ.get("ALPACA_API_SECRET_KEY", ""),
            entry=entry,
        ),
    )
