"""Backtesting: replay a strategy against historical candles before it trades real money."""

from src.backtest.engine import Backtester, BacktestResult, BacktestTrade, buy_and_hold_return_pct

__all__ = ["Backtester", "BacktestResult", "BacktestTrade", "buy_and_hold_return_pct"]
