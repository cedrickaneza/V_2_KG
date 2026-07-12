"""forexbot — an educational forex trading bot.

Layers:
    data       -> candles (price bars) from CSV files or the OANDA API
    strategies -> turn candles into a desired position (+1 long / -1 short / 0 flat)
    risk       -> decide HOW MUCH to trade and when to stop trading entirely
    execution  -> brokers that place orders (simulated, or OANDA practice/live)
    backtest   -> replay history through a strategy to measure how it would have done

Nothing in this package is financial advice. Always start with the
backtester, then the OANDA *practice* account. See README.md.
"""

__version__ = "0.1.0"
