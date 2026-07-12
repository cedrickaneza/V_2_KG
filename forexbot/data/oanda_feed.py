"""Candle data from the OANDA v20 REST API (works with a free practice token)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from .candles import Candle, parse_time

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
LIVE_HOST = "https://api-fxtrade.oanda.com"

GRANULARITY_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D": 86400,
}

MAX_COUNT_PER_REQUEST = 5000


class OandaFeed:
    def __init__(self, token: str, practice: bool = True, timeout: float = 15.0):
        if not token:
            raise ValueError("an OANDA API token is required (env var OANDA_API_TOKEN)")
        self.host = PRACTICE_HOST if practice else LIVE_HOST
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def get_candles(
        self,
        instrument: str,
        granularity: str = "H1",
        count: int = 500,
        start: Optional[datetime] = None,
    ) -> List[Candle]:
        """Fetch up to `count` most recent COMPLETED mid-price candles."""
        if granularity not in GRANULARITY_SECONDS:
            raise ValueError(
                f"unsupported granularity '{granularity}' "
                f"(supported: {', '.join(GRANULARITY_SECONDS)})"
            )
        params = {
            "granularity": granularity,
            "price": "M",
            "count": str(min(count, MAX_COUNT_PER_REQUEST)),
        }
        if start is not None:
            params["from"] = start.astimezone(timezone.utc).isoformat()
            params.pop("count")
            params["count"] = str(min(count, MAX_COUNT_PER_REQUEST))
        resp = self._session.get(
            f"{self.host}/v3/instruments/{instrument}/candles",
            params=params,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"OANDA candles request failed ({resp.status_code}): {resp.text[:300]}"
            )
        candles: List[Candle] = []
        for raw in resp.json().get("candles", []):
            if not raw.get("complete", False):
                continue  # never trade on a half-formed candle
            mid = raw["mid"]
            candles.append(
                Candle(
                    time=parse_time(raw["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=float(raw.get("volume", 0)),
                )
            )
        return candles

    def download_history(
        self, instrument: str, granularity: str = "H1", days: int = 365
    ) -> List[Candle]:
        """Page backwards-compatible bulk download for backtesting datasets."""
        step = GRANULARITY_SECONDS[granularity]
        start = datetime.now(timezone.utc) - timedelta(days=days)
        out: List[Candle] = []
        seen = set()
        while True:
            batch = self.get_candles(
                instrument, granularity, count=MAX_COUNT_PER_REQUEST, start=start
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
