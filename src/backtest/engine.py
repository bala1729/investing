"""Walk-forward backtesting engine for Strategy implementations."""

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from src.bot.strategies.base import Signal, Strategy
from src.exchange.executor import OrderSide


def buy_and_hold_return_pct(candles: pd.DataFrame) -> Decimal:
    """Return the % return from buying at the first bar's open and holding to the last close.

    A standard baseline for judging a strategy's backtest results — a strategy
    that can't beat simply holding the asset over the same period isn't adding
    value versus doing nothing.
    """
    if len(candles) == 0:
        return Decimal("0")
    entry = Decimal(str(candles.iloc[0]["open"]))
    if entry == 0:
        return Decimal("0")
    exit_price = Decimal(str(candles.iloc[-1]["close"]))
    return (exit_price - entry) / entry * 100


@dataclass(frozen=True)
class BacktestTrade:
    """A single simulated fill during a backtest."""

    timestamp: pd.Timestamp
    side: OrderSide
    price: Decimal
    amount: Decimal
    reason: str
    pnl: Decimal | None = None
    fee: Decimal = Decimal("0")


@dataclass(frozen=True)
class BacktestResult:
    """Outcome of running a Backtester over a range of historical candles."""

    symbol: str
    strategy: str
    starting_balance: Decimal
    ending_balance: Decimal
    trades: list[BacktestTrade]
    equity_curve: list[Decimal]

    @property
    def total_return_pct(self) -> Decimal:
        """Overall return over the backtest period, as a percentage."""
        if self.starting_balance == 0:
            return Decimal("0")
        return (self.ending_balance - self.starting_balance) / self.starting_balance * 100

    @property
    def closed_trades(self) -> list[BacktestTrade]:
        """Trades that closed a position (i.e. have a realized P&L)."""
        return [t for t in self.trades if t.pnl is not None]

    @property
    def total_fees_paid(self) -> Decimal:
        """Sum of all fees paid across every fill, in quote currency."""
        return sum((t.fee for t in self.trades), Decimal("0"))

    @property
    def win_rate_pct(self) -> Decimal | None:
        """Percentage of closed trades that were profitable, or None if none closed."""
        closed = self.closed_trades
        if not closed:
            return None
        wins = sum(1 for t in closed if t.pnl is not None and t.pnl > 0)
        return Decimal(wins) / Decimal(len(closed)) * 100

    @property
    def max_drawdown_pct(self) -> Decimal:
        """Largest peak-to-trough decline in equity over the backtest, as a percentage."""
        if not self.equity_curve:
            return Decimal("0")

        peak = self.equity_curve[0]
        max_dd = Decimal("0")
        for equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        return max_dd


class Backtester:
    """Replays a Strategy bar-by-bar over historical candles with no lookahead bias.

    A signal generated from the data available through bar N is filled at bar
    N+1's open — the earliest price a live strategy could actually have traded
    at, since bar N's close (and any indicator derived from it) isn't known
    until bar N has finished forming. A signal generated on the final bar has
    no following bar to fill on and is dropped.

    Modeled as simple long-only spot trading, mirroring PaperTradingSimulator:
    a BUY signal spends `position_size_pct` of the available quote balance, a
    SELL signal liquidates the entire base position. A BUY with no quote
    balance left, or a SELL with no position open, is ignored.

    `fee_pct` and `slippage_pct` model real-world trading costs, both applied
    per fill (i.e. on both the entry and the exit of a position):
      - fee_pct is taken out of the traded value — on a BUY it reduces how much
        base currency you actually receive for your quote spend; on a SELL it
        reduces the quote currency proceeds.
      - slippage_pct worsens the fill price versus the bar's raw open — higher
        for a BUY, lower for a SELL — approximating the cost of actually
        getting filled versus the idealized quoted price.
    Both default to 0 so the engine's own default behavior is fee-free/frictionless;
    scripts/backtest.py defaults to realistic non-zero values since that's the
    tool actually used to judge a strategy.
    """

    def __init__(
        self,
        strategy: Strategy,
        symbol: str,
        starting_balance: Decimal = Decimal("10000"),
        position_size_pct: Decimal = Decimal("100"),
        fee_pct: Decimal = Decimal("0"),
        slippage_pct: Decimal = Decimal("0"),
    ) -> None:
        if not (Decimal("0") < position_size_pct <= Decimal("100")):
            raise ValueError("position_size_pct must be between 0 (exclusive) and 100")
        if fee_pct < 0:
            raise ValueError("fee_pct cannot be negative")
        if slippage_pct < 0:
            raise ValueError("slippage_pct cannot be negative")
        self._strategy = strategy
        self._symbol = symbol
        self._starting_balance = starting_balance
        self._position_size_pct = position_size_pct
        self._fee_pct = fee_pct
        self._slippage_pct = slippage_pct

    def run(self, candles: pd.DataFrame) -> BacktestResult:
        """Run the strategy over historical candles, oldest first.

        Args:
            candles: OHLCV data as produced by ohlcv_to_dataframe(), oldest first.

        Returns:
            The simulated trade log and resulting performance metrics.
        """
        quote_balance = self._starting_balance
        base_balance = Decimal("0")
        avg_entry_price = Decimal("0")
        trades: list[BacktestTrade] = []
        equity_curve: list[Decimal] = []
        pending_signal: Signal | None = None

        for i in range(len(candles)):
            if pending_signal is not None:
                raw_price = Decimal(str(candles.iloc[i]["open"]))
                timestamp = candles.index[i]

                if pending_signal.side == OrderSide.BUY and quote_balance > 0:
                    buy_price = raw_price * (1 + self._slippage_pct / 100)
                    spend = quote_balance * (self._position_size_pct / Decimal("100"))
                    fee_amount = spend * (self._fee_pct / 100)
                    amount = (spend - fee_amount) / buy_price
                    total_cost = avg_entry_price * base_balance + spend
                    base_balance += amount
                    avg_entry_price = total_cost / base_balance
                    quote_balance -= spend
                    trades.append(
                        BacktestTrade(
                            timestamp=timestamp,
                            side=OrderSide.BUY,
                            price=buy_price,
                            amount=amount,
                            reason=pending_signal.reason,
                            fee=fee_amount,
                        )
                    )
                elif pending_signal.side == OrderSide.SELL and base_balance > 0:
                    sell_price = raw_price * (1 - self._slippage_pct / 100)
                    gross_proceeds = base_balance * sell_price
                    fee_amount = gross_proceeds * (self._fee_pct / 100)
                    net_proceeds = gross_proceeds - fee_amount
                    pnl = net_proceeds - avg_entry_price * base_balance
                    trades.append(
                        BacktestTrade(
                            timestamp=timestamp,
                            side=OrderSide.SELL,
                            price=sell_price,
                            amount=base_balance,
                            reason=pending_signal.reason,
                            pnl=pnl,
                            fee=fee_amount,
                        )
                    )
                    quote_balance += net_proceeds
                    base_balance = Decimal("0")
                    avg_entry_price = Decimal("0")

            pending_signal = self._strategy.generate_signal(self._symbol, candles.iloc[: i + 1])

            mark_price = Decimal(str(candles.iloc[i]["close"]))
            equity_curve.append(quote_balance + base_balance * mark_price)

        ending_balance = equity_curve[-1] if equity_curve else self._starting_balance

        return BacktestResult(
            symbol=self._symbol,
            strategy=self._strategy.name,
            starting_balance=self._starting_balance,
            ending_balance=ending_balance,
            trades=trades,
            equity_curve=equity_curve,
        )
