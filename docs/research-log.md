# Research log

The discipline: every idea gets tested with walk-forward validation on real
data and honest costs, and every result gets recorded here — **especially
the discards**. A discard costs nothing; the same lesson learned live costs
real money. Append new entries at the top.

---

## 2026-07-22 — All three starter strategies on BTC/USD (Alpaca): DISCARD

**Setup.** 2 years of real BTC/USD from Alpaca (2024-07-22 → 2026-07-22,
17,517 hourly bars, gapless). Walk-forward validation, long-only (Alpaca
can't short crypto), risk defaults (0.5%/trade, 2×ATR stop, 3×ATR target).
Costs modelled as 0.5% round trip (`--spread 442` at median price $88k),
matching Alpaca's ~0.25%/side taker fee. Benchmark: buy-and-hold BTC over
the same period was **−2.5%** (sideways market — timing had to earn
everything).

**Out-of-sample results (the honest column):**

| Strategy | 1Hour | 4Hour | 1Day |
|---|---|---|---|
| SMA crossover | −47.1% (592 trades) | −6.9% (131) | −1.4% (8) |
| Donchian breakout | −37.7% (321 trades) | −4.2% (64) | −4.0% (9) |
| RSI mean-reversion | −26.5% (198 trades) | −3.4% (36) | −4.5% (18) |

**Reading.**
- **Fees dominate at high frequency.** The hourly losses are mostly fee
  drag: hundreds of trades × ~0.5% round trip on a market that went
  nowhere. Moving 1Hour → 4Hour recovered 30–40 percentage points without
  changing any strategy logic.
- **No edge remains after fees at any tested frequency.** Even at daily
  bars, no configuration was positive out-of-sample. Trade counts at 1Day
  are small (8–18), so those numbers are weak evidence rather than proof —
  but nothing here earns a paper-trading slot.
- This matches the earlier synthetic-market Monte Carlo finding: textbook
  indicator strategies carry no exploitable edge; the machinery's job is
  to say so *before* money (or months of paper time) is spent. It did.

**What might change the verdict (untested, in rough order of promise):**
1. **Maker execution** — entering with limit orders instead of market
   orders cuts Alpaca fees from 0.25% to ≤0.15%/side; at 4Hour frequency
   that's several percent a year back.
2. **Fee-aware signal filter** — only take entries whose expected move
   (e.g. ATR multiple) is a large multiple of the round-trip cost.
3. **More daily history** — Alpaca serves years more data; `--days 2000+`
   of 1Day bars would give the daily timeframe real statistical power.
4. **Other assets** (ETH/USD etc.) and **regime filters** (only trade when
   volatility/trend measures say the strategy's regime is active).
