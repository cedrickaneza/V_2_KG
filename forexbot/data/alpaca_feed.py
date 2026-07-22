"""Historical + live crypto candles from Alpaca's Market Data API.

Works with a free Alpaca account (paper or live — market data access is the
same either way). Sign up at https://alpaca.markets/ (email + password,
no identity verification for paper trading) and generate API keys from the
dashboard.

Only the crypto bars endpoint is used:
    GET https://data.alpaca.markets/v1beta3/crypto/us/bars

Symbols use Alpaca's native "BTC/USD" format (not OANDA's "EUR_USD" style) —
pass them through unchanged.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from .candles import Candle, parse_time

DATA_HOST = "https://data.alpaca.markets"

# Alpaca's own {n}{Unit} timeframe grammar, restricted to the values this
# bot's config/CLI actually offer (mirrors GRANULARITY_SECONDS in oanda_feed).
GRANULARITY_SECONDS = {
    "1Min": 60,
    "5Min": 300,
    "15Min": 900,
    "30Min": 1800,
    "1Hour": 3600,
    "4Hour": 14400,
    "1Day": 86400,
}

MAX_LIMIT_PER_REQUEST = 10_000


class AlpacaFeedError(RuntimeError):
    pass


def drop_incomplete(
    candles: List[Candle], step_seconds: int, now: datetime
) -> List[Candle]:
    """Remove bars whose interval hasn't finished yet.

    A bar's timestamp is the START of its interval, so it is complete only
    once `time + step <= now`. Alpaca (unlike OANDA) doesn't flag this, and
    the newest bar in a response is usually still forming.
    """
    step = timedelta(seconds=step_seconds)
    return [c for c in candles if c.time + step <= now]


class AlpacaCryptoFeed:
    def __init__(self, api_key_id: str, api_secret_key: str, timeout: float = 15.0):
        if not api_key_id or not api_secret_key:
            raise ValueError(
                "an Alpaca API key id and secret are required "
                "(env vars ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY)"
            )
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {"APCA-API-KEY-ID": api_key_id, "APCA-API-SECRET-KEY": api_secret_key}
        )

    def get_candles(
        self,
        symbol: str,
        granularity: str = "1Hour",
        count: int = 500,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[Candle]:
        """Fetch up to `count` most recent COMPLETED crypto bars.

        The parameter names mirror OandaFeed.get_candles so TradingBot can
        call either feed identically (Alpaca itself says "timeframe"/"limit").

        Two Alpaca quirks are handled here so callers never see them:
        * bars carry no "complete" flag (unlike OANDA), and the latest bar is
          usually still forming — any bar whose interval hasn't finished yet
          is dropped, keeping the project-wide "never trade a half-formed
          candle" rule intact;
        * when `start` is omitted the API defaults to the beginning of the
          current DAY and `limit` truncates from the OLDEST side — so with no
          explicit start we ask from `count` intervals back, which spans the
          newest bars (crypto trades 24/7, so the bar stream has no gaps).
        """
        if granularity not in GRANULARITY_SECONDS:
            raise ValueError(
                f"unsupported granularity '{granularity}' "
                f"(supported: {', '.join(GRANULARITY_SECONDS)})"
            )
        step = GRANULARITY_SECONDS[granularity]
        now = datetime.now(timezone.utc)
        if start is None:
            start = now - timedelta(seconds=step * (count + 2))

        params: Dict[str, Any] = {
            "symbols": symbol,
            "timeframe": granularity,
            "limit": str(min(count + 5, MAX_LIMIT_PER_REQUEST)),
            "start": start.astimezone(timezone.utc).isoformat(),
        }
        if end is not None:
            params["end"] = end.astimezone(timezone.utc).isoformat()

        resp = self._session.get(
            f"{DATA_HOST}/v1beta3/crypto/us/bars", params=params, timeout=self.timeout
        )
        if resp.status_code >= 400:
            raise AlpacaFeedError(
                f"Alpaca bars request failed ({resp.status_code}): {resp.text[:300]}"
            )
        bars = resp.json().get("bars", {}).get(symbol, [])
        candles = [
            Candle(
                time=parse_time(bar["t"]),
                open=float(bar["o"]),
                high=float(bar["h"]),
                low=float(bar["l"]),
                close=float(bar["c"]),
                volume=float(bar.get("v", 0)),
            )
            for bar in bars
        ]
        candles = drop_incomplete(candles, step, now)
        return candles[-count:]

    def download_history(
        self, symbol: str, granularity: str = "1Hour", days: int = 730
    ) -> List[Candle]:
        """Page forward from `days` ago to now, for building backtest datasets."""
        step = GRANULARITY_SECONDS[granularity]
        start = datetime.now(timezone.utc) - timedelta(days=days)
        out: List[Candle] = []
        seen = set()
        while True:
            batch = self.get_candles(
                symbol, granularity, count=MAX_LIMIT_PER_REQUEST, start=start
            )
            new = [c for c in batch if c.time not in seen]
            if not new:
                break
            out.extend(new)
            seen.update(c.time for c in new)
            start = new[-1].time + timedelta(seconds=step)
            if start >= datetime.now(timezone.utc):
                break
            time.sleep(0.25)  # stay polite to the API
        out.sort(key=lambda c: c.time)
        return out
