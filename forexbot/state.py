"""Persist the bot's small in-memory state between runs.

Why this exists: the validated setup trades DAILY candles, so the bot only
needs to wake once a day — running it as a one-shot ("--once") from a
machine that is otherwise off. But two pieces of state live in memory and
would be lost between runs, silently changing behaviour vs the backtest:

* RiskManager history — peak equity (drawdown kill switch) and the day's
  starting equity (daily loss cap). Losing these would reset the account's
  safety limits every run.
* AlpacaBroker's tracked take-profit levels and resting-stop order ids —
  losing these would mean take-profits never trigger in one-shot mode.

Everything else is either on the broker's servers (positions, stop orders)
or recomputed from candles each cycle.

A known sharp edge: this state has no idea WHICH account it belongs to.
Switch to a different paper account (e.g. after resetting your Alpaca
paper balance) and the old peak_equity is still on disk — the risk
manager will compare the new, smaller balance against that stale peak and
immediately (and falsely) trip the drawdown kill switch. Use clear_state()
via `run_bot.py --reset-state` whenever the underlying account changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .risk.manager import RiskManager


def save_state(path: str | Path, risk: RiskManager, broker: Any) -> None:
    data: dict = {
        "risk": {
            "peak_equity": risk.peak_equity,
            "day_start_equity": risk.day_start_equity,
            "current_day": risk._current_day,
            "halted": risk.halted,
            "halt_reason": risk.halt_reason,
        }
    }
    if hasattr(broker, "_take_profits") and hasattr(broker, "_stop_order_ids"):
        data["broker"] = {
            "take_profits": broker._take_profits,
            "stop_order_ids": broker._stop_order_ids,
        }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_state(path: str | Path, risk: RiskManager, broker: Any) -> bool:
    """Apply saved state if the file exists. Returns True when loaded."""
    path = Path(path)
    if not path.exists():
        return False
    data = json.loads(path.read_text())

    risk_data = data.get("risk", {})
    risk.peak_equity = risk_data.get("peak_equity")
    risk.day_start_equity = risk_data.get("day_start_equity")
    risk._current_day = risk_data.get("current_day")
    risk.halted = bool(risk_data.get("halted", False))
    risk.halt_reason = str(risk_data.get("halt_reason", ""))

    broker_data = data.get("broker")
    if broker_data and hasattr(broker, "_take_profits"):
        broker._take_profits = {
            k: float(v) for k, v in broker_data.get("take_profits", {}).items()
        }
        broker._stop_order_ids = dict(broker_data.get("stop_order_ids", {}))
    return True


def clear_state(path: str | Path) -> bool:
    """Delete saved state — use when the underlying account has changed
    (a new/reset paper balance, a different broker) so old history isn't
    mistaken for the new account's history. Returns True if a file existed."""
    path = Path(path)
    if path.exists():
        path.unlink()
        return True
    return False
