"""Live/paper trading loop.

Once per candle (e.g. every hour on H1) the bot:
    1. fetches the latest completed candles from OANDA
    2. updates the risk manager with current account equity
    3. asks the strategy for its desired stance (+1 / -1 / 0)
    4. reconciles: closes/opens positions so reality matches the stance,
       with an ATR stop-loss, take-profit and risk-based size attached

Safety defaults:
    * dry_run: true  -> orders are logged, never sent
    * mode: practice -> demo account (fake money) even when dry_run is off
    * mode: live requires BOTH editing the config AND setting the env var
      FOREXBOT_I_UNDERSTAND_LIVE_RISK=yes
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .data.oanda_feed import GRANULARITY_SECONDS, OandaFeed
from .execution.oanda_broker import OandaBroker
from .risk.manager import RiskManager
from .strategies import build_strategy

log = logging.getLogger("forexbot")


def setup_logging(log_dir: str = "logs") -> None:
    Path(log_dir).mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(Path(log_dir) / "bot.log"),
        ],
    )


class TradingBot:
    def __init__(self, config: AppConfig):
        self.config = config
        practice = config.mode == "practice"

        import os

        if not practice and os.environ.get("FOREXBOT_I_UNDERSTAND_LIVE_RISK") != "yes":
            raise SystemExit(
                "Refusing to start in LIVE mode. Live trading risks real money.\n"
                "If you have months of profitable practice results and accept the "
                "risk, set FOREXBOT_I_UNDERSTAND_LIVE_RISK=yes and restart."
            )

        self.strategy = build_strategy(config.strategy_name, config.strategy_params)
        self.risk = RiskManager(config.risk)
        self.feed = OandaFeed(config.oanda.token, practice=practice)
        self.broker = OandaBroker(
            config.oanda.account_id, config.oanda.token, practice=practice
        )
        self.granularity_seconds = GRANULARITY_SECONDS[config.granularity]

    # -- scheduling ------------------------------------------------------

    def seconds_until_next_candle(self) -> float:
        now = datetime.now(timezone.utc).timestamp()
        step = self.granularity_seconds
        return step - (now % step) + 10  # +10s so OANDA has finalised the candle

    # -- one trading cycle ----------------------------------------------------

    def run_cycle(self) -> None:
        cfg = self.config
        candles = self.feed.get_candles(
            cfg.instrument, cfg.granularity, count=cfg.lookback
        )
        if len(candles) < self.strategy.warmup:
            log.warning(
                "only %d candles available, need %d — skipping cycle",
                len(candles),
                self.strategy.warmup,
            )
            return

        equity = self.broker.get_equity()
        now = datetime.now(timezone.utc)
        self.risk.update(now, equity)

        stance = self.strategy.target_position(candles)
        pos = self.broker.get_position(cfg.instrument)
        held = 0 if pos is None else (1 if pos.units > 0 else -1)
        last_close = candles[-1].close

        log.info(
            "cycle: equity=%.2f price=%.5f stance=%+d held=%+d %s",
            equity,
            last_close,
            stance,
            held,
            "(DRY RUN)" if cfg.dry_run else "",
        )

        if self.risk.halted:
            log.error("KILL SWITCH ACTIVE: %s — no trading", self.risk.halt_reason)
            return
        if stance == held:
            return

        if pos is not None:
            if cfg.dry_run:
                log.info("[dry-run] would close %+d units of %s", pos.units, cfg.instrument)
            else:
                self.broker.close_position(cfg.instrument)
                log.info("closed %+d units of %s", pos.units, cfg.instrument)

        if stance == 0:
            return

        allowed, reason = self.risk.can_open_trade(equity)
        if not allowed:
            log.warning("entry blocked by risk manager: %s", reason)
            return

        stop_dist = self.risk.stop_distance(candles)
        if not stop_dist:
            log.warning("no ATR available yet — skipping entry")
            return
        units = self.risk.position_size(equity, stop_dist) * stance
        if units == 0:
            log.warning("position size rounded to 0 — equity too small for this stop")
            return

        tp_dist = self.risk.take_profit_distance(stop_dist)
        if stance > 0:
            sl, tp = last_close - stop_dist, last_close + tp_dist
        else:
            sl, tp = last_close + stop_dist, last_close - tp_dist

        if cfg.dry_run:
            log.info(
                "[dry-run] would open %+d units of %s (SL=%.5f TP=%.5f)",
                units, cfg.instrument, sl, tp,
            )
        else:
            self.broker.market_order(cfg.instrument, units, stop_loss=sl, take_profit=tp)
            log.info("opened %+d units of %s (SL=%.5f TP=%.5f)", units, cfg.instrument, sl, tp)

    # -- main loop -----------------------------------------------------------

    def run_forever(self) -> None:
        cfg = self.config
        log.info("=" * 60)
        log.info(
            "forexbot starting: %s %s %s mode=%s dry_run=%s",
            cfg.instrument, cfg.granularity, self.strategy.describe(),
            cfg.mode.upper(), cfg.dry_run,
        )
        log.info(
            "risk: %.2f%%/trade, %.0f%% daily loss cap, %.0f%% drawdown kill switch",
            cfg.risk.risk_per_trade * 100,
            cfg.risk.max_daily_loss_pct * 100,
            cfg.risk.max_drawdown_pct * 100,
        )
        log.info("=" * 60)

        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                log.info("stopped by user — open positions (if any) are left untouched")
                raise
            except Exception:
                log.exception("cycle failed; will retry next candle")
            wait = self.seconds_until_next_candle()
            log.info("sleeping %.0fs until next %s candle", wait, cfg.granularity)
            time.sleep(wait)
