# Research log

The discipline: every idea gets tested with walk-forward validation on real
data and honest costs, and every result gets recorded here — **especially
the discards**. A discard costs nothing; the same lesson learned live costs
real money. Append new entries at the top.

---

## 2026-07-22 (evening) — ETH/USD cross-check: trend-following confirms, RSI discarded

**Setup.** Identical to the BTC daily test below: 2,028 daily ETH/USD bars
(2021-01-01 → 2026-07-21), walk-forward 600/150, long-only,
`--spread-pct 0.005`. Purpose: if the daily result repeats on a second
asset the strategies never saw, it is much less likely to be luck.

**Out-of-sample results (ETH, with BTC alongside for comparison):**

| Strategy | ETH OOS | BTC OOS | Verdict |
|---|---|---|---|
| Donchian breakout | **+7.3%** (PF 1.54, Sharpe 0.71, maxDD 2.9%) | +2.2% | keep — best result in the project |
| SMA crossover | +2.6% (PF 1.14) | +4.8% | keep |
| RSI mean-reversion | **−4.2%** (PF 0.30) | +1.1% | **discard** — inconsistent across assets |

**Reading.**
- The trend-following family (SMA, Donchian) is now positive out-of-sample
  on BOTH assets over ~4 years each after honest fees. RSI mean-reversion
  flipped sign between assets — exactly what a non-edge looks like; dropped.
- Honesty caveat: BTC and ETH are strongly correlated, so this is one
  confirmation from a *sibling* asset, not an independent universe. Still,
  the sign of a real (if modest) effect: daily-timeframe crypto trend
  capture survives 0.5% round-trip fees.
- Returns remain modest at the bot's cautious 0.5% risk sizing
  (≈1–2%/year); drawdowns are tiny (≤4.7%), so there is headroom to size
  up within the 2% cap once the edge is trusted.

**Next:** (1) maker/limit execution — cut fees from 0.25% to ≤0.15%/side;
(2) consider trading BTC+ETH together (diversifies entries); (3) fee-aware
entry filter.

---

## 2026-07-22 (later) — Daily bars, 5.5 years: first faint pulse — KEEP RESEARCHING

**Setup.** 2,028 daily BTC/USD bars (2021-01-01 → 2026-07-21). Walk-forward
train 600 / test 150 (≈9 folds, ~3.9 years out-of-sample), long-only,
`--spread-pct 0.005` (fees as a true percentage — new engine feature added
for this test, since price ranged $8k→$126k and any fixed-dollar fee would
be wrong at one end).

**Out-of-sample results:**

| Strategy | OOS total | Trades | Profit factor | Max DD | Sharpe |
|---|---|---|---|---|---|
| SMA crossover | **+4.8%** | 71 | 1.29 | 4.3% | 0.44 |
| Donchian breakout | +2.2% | 57 | 1.15 | 6.0% | 0.23 |
| RSI mean-reversion | +1.1% | 22 | 1.26 | 2.9% | 0.24 |

**Reading, honestly.**
- First test in the entire project where every configuration is positive
  out-of-sample, and train ≈ test (no curve-fit signature). Daily bars
  cut fee drag enough for the multi-year trendiness of BTC to show through.
- It is a *faint* pulse, not an edge worth money yet: ≈ +1.2%/year at the
  bot's very cautious sizing (0.5% risk/trade — max drawdown was only
  4.3%, so the bot was barely betting). Sharpe < 0.5 and ~71 trades is
  thin evidence; this could still be luck.
- Conclusion: the daily-timeframe, trend-following, fee-aware region is
  where further research should focus. Hourly is dead on arrival at these
  fees (see entry below).

**Next tests, in order:** (1) same daily walk-forward on ETH/USD — if the
result repeats on a second asset it's much less likely to be luck;
(2) maker/limit execution to cut fees toward 0.15%/side; (3) fee-aware
entry filter.

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
