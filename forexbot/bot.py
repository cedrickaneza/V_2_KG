"""Live/paper trading loop.

Once per candle (e.g. every hour on H1, once a day on 1Day) the bot:
    1. updates the risk manager with current account equity (once)
    2. then, for EACH configured instrument:
       a. fetches the latest completed candles
       b. asks that instrument's own strategy for its stance (+1 / -1 / 0)
       c. reconciles: closes/opens positions so reality matches the stance,
          with an ATR stop-loss, take-profit and risk-based size attached

Each instrument gets its OWN strategy instance because strategies may keep
internal state; sharing one instance across instruments would tangle their
signals. The risk manager is shared on purpose: daily-loss and drawdown
limits protect the ACCOUNT, not any single market.

Safety defaults:
    * dry_run: true  -> orders are logged, never sent
    * mode: practice -> demo account (fake money) even when dry_run is off
    * mode: live requires BOTH editing the config AND setting the env var
      FOREXBOT_I_UNDERSTAND_LIVE_RISK=yes

Broker differences this loop has to account for:
    * OANDA (forex) allows short positions and attaches stop-loss/take-profit
      to the entry order as a bracket.
    * Alpaca (crypto) is long-only — a SHORT signal is clamped to FLAT — and
      cannot bracket orders, so only the stop-loss rides as a resting order
      on Alpaca's side; take-profit is checked here, once per cycle, against
      the broker's ``get_take_profit`` (see alpaca_broker.py for why).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .data.alpaca_feed import GRANULARITY_SECONDS as ALPACA_GRANULARITY_SECONDS
from .data.alpaca_feed import AlpacaCryptoFeed
from .data.oanda_feed import GRANULARITY_SECONDS as OANDA_GRANULARITY_SECONDS
from .data.oanda_feed import OandaFeed
from .execution.alpaca_broker import AlpacaBroker
from .execution.oanda_broker import OandaBroker
from .risk.manager import RiskManager
from .strategies import FLAT, build_strategy

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

        # one strategy instance PER instrument — strategies carry state
        self.strategies = {
            instrument: build_strategy(config.strategy_name, config.strategy_params)
            for instrument in config.instruments
        }
        self.risk = RiskManager(config.risk)

        if config.broker == "alpaca":
            self.feed = AlpacaCryptoFeed(
                config.alpaca.api_key_id, config.alpaca.api_secret_key
            )
            self.broker = AlpacaBroker(
                config.alpaca.api_key_id,
                config.alpaca.api_secret_key,
                paper=practice,
                entry=config.alpaca.entry,
            )
            self.granularity_seconds = ALPACA_GRANULARITY_SECONDS[config.granularity]
        else:
            self.feed = OandaFeed(config.oanda.token, practice=practice)
            self.broker = OandaBroker(
                config.oanda.account_id, config.oanda.token, practice=practice
            )
            self.granularity_seconds = OANDA_GRANULARITY_SECONDS[config.granularity]

        self.long_only = getattr(self.broker, "long_only", False)

    # -- scheduling ------------------------------------------------------

    def seconds_until_next_candle(self) -> float:
        now = datetime.now(timezone.utc).timestamp()
        step = self.granularity_seconds
        return step - (now % step) + 10  # +10s so the broker has finalised the candle

    # -- one trading cycle ----------------------------------------------------

    def run_cycle(self) -> None:
        equity = self.broker.get_equity()
        self.risk.update(datetime.now(timezone.utc), equity)

        if self.risk.halted:
            log.error("KILL SWITCH ACTIVE: %s — no trading", self.risk.halt_reason)
            return

        for instrument in self.config.instruments:
            try:
                self._run_instrument(instrument, equity)
            except Exception:
                log.exception("cycle failed for %s; continuing with the rest", instrument)

    def _run_instrument(self, instrument: str, equity: float) -> None:
        cfg = self.config
        strategy = self.strategies[instrument]

        candles = self.feed.get_candles(instrument, cfg.granularity, count=cfg.lookback)
        if len(candles) < strategy.warmup:
            log.warning(
                "%s: only %d candles available, need %d — skipping",
                instrument, len(candles), strategy.warmup,
            )
            return

        stance = strategy.target_position(candles)
        if self.long_only and stance < 0:
            stance = FLAT
        pos = self.broker.get_position(instrument)
        held = 0 if pos is None else (1 if pos.units > 0 else -1)
        last_close = candles[-1].close

        log.info(
            "%s: equity=%.2f price=%.5f stance=%+d held=%+d %s",
            instrument, equity, last_close, stance, held,
            "(DRY RUN)" if cfg.dry_run else "",
        )

        # brokers that can't bracket an order (e.g. Alpaca crypto) track
        # take-profit here instead of on the exchange — see the module
        # docstring and alpaca_broker.py for why this is a deliberate,
        # disclosed simplification rather than a broker-enforced exit.
        get_take_profit = getattr(self.broker, "get_take_profit", None)
        if pos is not None and get_take_profit is not None:
            tp = get_take_profit(instrument)
            crossed = tp is not None and (
                (pos.units > 0 and last_close >= tp) or (pos.units < 0 and last_close <= tp)
            )
            if crossed:
                if cfg.dry_run:
                    log.info("[dry-run] would close %+g units of %s (take-profit reached)",
                             pos.units, instrument)
                else:
                    self.broker.close_position(instrument, reason="take_profit")
                    log.info("closed %+g units of %s (take-profit reached)",
                             pos.units, instrument)
                return

        if stance == held:
            return

        if pos is not None:
            if cfg.dry_run:
                log.info("[dry-run] would close %+g units of %s", pos.units, instrument)
            else:
                self.broker.close_position(instrument)
                log.info("closed %+g units of %s", pos.units, instrument)

        if stance == 0:
            return

        allowed, reason = self.risk.can_open_trade(equity)
        if not allowed:
            log.warning("%s: entry blocked by risk manager: %s", instrument, reason)
            return

        stop_dist = self.risk.stop_distance(candles)
        if not stop_dist:
            log.warning("%s: no ATR available yet — skipping entry", instrument)
            return
        units = self.risk.position_size(equity, stop_dist) * stance
        if units == 0:
            log.warning("%s: position size rounded to 0 — equity too small for this stop",
                        instrument)
            return

        tp_dist = self.risk.take_profit_distance(stop_dist)
        if stance > 0:
            sl, tp = last_close - stop_dist, last_close + tp_dist
        else:
            sl, tp = last_close + stop_dist, last_close - tp_dist

        if cfg.dry_run:
            log.info("[dry-run] would open %+g units of %s (SL=%.5f TP=%.5f)",
                     units, instrument, sl, tp)
        else:
            self.broker.market_order(instrument, units, stop_loss=sl, take_profit=tp)
            log.info("opened %+g units of %s (SL=%.5f TP=%.5f)", units, instrument, sl, tp)

    # -- main loop -----------------------------------------------------------

    def run_forever(self) -> None:
        cfg = self.config
        strategy_desc = next(iter(self.strategies.values())).describe()
        log.info("=" * 60)
        log.info(
            "forexbot starting: %s %s %s mode=%s dry_run=%s",
            ", ".join(cfg.instruments), cfg.granularity, strategy_desc,
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
