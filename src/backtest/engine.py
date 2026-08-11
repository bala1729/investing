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

    One position per symbol, matching TradingEngine: a BUY while already holding
    is skipped rather than pyramided into. Strategies emit an entry signal on
    every bar the entry conditions hold (not only on the bar they first become
    true), so without this the same position would be added to on every bar of a
    trend - and the backtest would model something the live engine would never
    do.

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

    `stop_loss_exit_pct` and `take_profit_exit_pct` control how much of the
    position each protective level closes when it fires (default 100 - a full
    exit, unchanged from before these existed). Both fire single-shot even when
    partial: whichever level triggers is cleared afterward regardless of
    fraction, so a price that lingers past a level cannot re-trigger it on every
    following bar and ladder the remainder down to dust. A strategy can request
    its own partial exit independently via `Signal.exit_fraction` on a SELL -
    the two mechanisms never collide within a bar, since a fired protective
    level always clears `pending_signal` before the strategy-signal branch runs.

    Fractional exits change what a trade count and win rate mean: each partial
    fill records its own pnl and counts as a closed trade, so a strategy that
    scales out of one logical position reports more, smaller closed trades than
    the same strategy exiting all at once. Not a bug, but not directly
    comparable to a 100%-exit run's trade count.
    """

    def __init__(
        self,
        strategy: Strategy,
        symbol: str,
        starting_balance: Decimal = Decimal("10000"),
        position_size_pct: Decimal = Decimal("100"),
        fee_pct: Decimal = Decimal("0"),
        slippage_pct: Decimal = Decimal("0"),
        stop_loss_pct: Decimal = Decimal("0"),
        take_profit_pct: Decimal = Decimal("0"),
        trailing_trigger_pct: Decimal = Decimal("0"),
        trailing_lock_pct: Decimal = Decimal("0"),
        stop_loss_exit_pct: Decimal = Decimal("100"),
        take_profit_exit_pct: Decimal = Decimal("100"),
    ) -> None:
        if not (Decimal("0") < position_size_pct <= Decimal("100")):
            raise ValueError("position_size_pct must be between 0 (exclusive) and 100")
        if fee_pct < 0:
            raise ValueError("fee_pct cannot be negative")
        if slippage_pct < 0:
            raise ValueError("slippage_pct cannot be negative")
        if stop_loss_pct < 0 or stop_loss_pct >= 100:
            raise ValueError("stop_loss_pct must be between 0 and 100 (exclusive)")
        if take_profit_pct < 0:
            raise ValueError("take_profit_pct cannot be negative")
        if trailing_trigger_pct < 0 or trailing_lock_pct < 0:
            raise ValueError("trailing stop percentages cannot be negative")
        if trailing_trigger_pct > 0 and trailing_lock_pct >= trailing_trigger_pct:
            raise ValueError("trailing_lock_pct must be below trailing_trigger_pct")
        if trailing_trigger_pct > 0 and stop_loss_pct == 0:
            raise ValueError("a trailing stop needs stop_loss_pct set to have a stop to raise")
        if not (Decimal("0") < stop_loss_exit_pct <= Decimal("100")):
            raise ValueError("stop_loss_exit_pct must be between 0 (exclusive) and 100")
        if not (Decimal("0") < take_profit_exit_pct <= Decimal("100")):
            raise ValueError("take_profit_exit_pct must be between 0 (exclusive) and 100")
        self._strategy = strategy
        self._symbol = symbol
        self._starting_balance = starting_balance
        self._position_size_pct = position_size_pct
        self._fee_pct = fee_pct
        self._slippage_pct = slippage_pct
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._trailing_trigger_pct = trailing_trigger_pct
        self._trailing_lock_pct = trailing_lock_pct
        self._stop_loss_exit_pct = stop_loss_exit_pct
        self._take_profit_exit_pct = take_profit_exit_pct

    def run(
        self,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> BacktestResult:
        """Run the strategy over historical candles, oldest first.

        Args:
            candles: OHLCV data as produced by ohlcv_to_dataframe(), oldest first.
            higher_tf_candles: Optional higher-timeframe OHLCV data, keyed by
                timeframe string, for strategies with multi-timeframe entry
                confirmation. At each primary (entry) bar, each higher-timeframe
                DataFrame is sliced to candles that opened at or before that
                bar's own timestamp - a deliberately conservative cutoff that
                may exclude the most-recent higher-timeframe candle but never
                leaks data the primary bar couldn't have seen yet.

        Returns:
            The simulated trade log and resulting performance metrics.
        """
        quote_balance = self._starting_balance
        base_balance = Decimal("0")
        avg_entry_price = Decimal("0")
        trades: list[BacktestTrade] = []
        equity_curve: list[Decimal] = []
        pending_signal: Signal | None = None
        stop_price: Decimal | None = None
        target_price: Decimal | None = None

        for i in range(len(candles)):
            # Protective exits are resolved before the strategy's own pending
            # signal, mirroring TradingEngine.enforce_stops() running ahead of
            # signal generation: a position already stopped out on this bar must
            # not also be sold by a strategy signal from the previous one.
            if base_balance > 0 and (stop_price is not None or target_price is not None):
                bar_low = Decimal(str(candles.iloc[i]["low"]))
                bar_high = Decimal(str(candles.iloc[i]["high"]))
                exit_at: Decimal | None = None
                exit_reason = ""
                exit_pct = Decimal("100")
                fired_stop = False
                fired_target = False
                # Stop takes precedence when a single bar spans both levels: OHLC
                # cannot say which came first, and assuming the loss is the
                # honest choice - the alternative flatters every result on a
                # volatile bar.
                if stop_price is not None and bar_low <= stop_price:
                    exit_at, exit_reason = stop_price, f"Stop-loss hit at {stop_price}"
                    exit_pct, fired_stop = self._stop_loss_exit_pct, True
                elif target_price is not None and bar_high >= target_price:
                    exit_at, exit_reason = target_price, f"Take-profit hit at {target_price}"
                    exit_pct, fired_target = self._take_profit_exit_pct, True

                if exit_at is not None:
                    sell_price = exit_at * (1 - self._slippage_pct / 100)
                    sold_amount = base_balance * (exit_pct / 100)
                    gross_proceeds = sold_amount * sell_price
                    fee_amount = gross_proceeds * (self._fee_pct / 100)
                    net_proceeds = gross_proceeds - fee_amount
                    trades.append(
                        BacktestTrade(
                            timestamp=candles.index[i],
                            side=OrderSide.SELL,
                            price=sell_price,
                            amount=sold_amount,
                            reason=exit_reason,
                            pnl=net_proceeds - avg_entry_price * sold_amount,
                            fee=fee_amount,
                        )
                    )
                    quote_balance += net_proceeds
                    base_balance -= sold_amount
                    if base_balance <= 0:
                        base_balance = Decimal("0")
                        avg_entry_price = Decimal("0")
                        stop_price = target_price = None
                    else:
                        # Single-shot: whichever level fired clears even on a
                        # partial exit, so a price that lingers past it can't
                        # re-trigger it every following bar and ladder the
                        # remainder down to dust. The other level (if any)
                        # stays armed for what's left.
                        if fired_stop:
                            stop_price = None
                        if fired_target:
                            target_price = None
                    pending_signal = None

            if pending_signal is not None:
                raw_price = Decimal(str(candles.iloc[i]["open"]))
                timestamp = candles.index[i]

                if (
                    pending_signal.side == OrderSide.BUY
                    and quote_balance > 0
                    and base_balance == 0
                ):
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
                    if self._stop_loss_pct > 0:
                        stop_price = avg_entry_price * (1 - self._stop_loss_pct / 100)
                    if self._take_profit_pct > 0:
                        target_price = avg_entry_price * (1 + self._take_profit_pct / 100)
                elif pending_signal.side == OrderSide.SELL and base_balance > 0:
                    sell_price = raw_price * (1 - self._slippage_pct / 100)
                    # Signal.exit_fraction is 0-1 (matches Signal.confidence's
                    # convention), unlike the constructor's 0-100 *_exit_pct
                    # params above - no /100 here.
                    sold_amount = base_balance * Decimal(str(pending_signal.exit_fraction))
                    gross_proceeds = sold_amount * sell_price
                    fee_amount = gross_proceeds * (self._fee_pct / 100)
                    net_proceeds = gross_proceeds - fee_amount
                    pnl = net_proceeds - avg_entry_price * sold_amount
                    trades.append(
                        BacktestTrade(
                            timestamp=timestamp,
                            side=OrderSide.SELL,
                            price=sell_price,
                            amount=sold_amount,
                            reason=pending_signal.reason,
                            pnl=pnl,
                            fee=fee_amount,
                        )
                    )
                    quote_balance += net_proceeds
                    base_balance -= sold_amount
                    if base_balance <= 0:
                        base_balance = Decimal("0")
                        avg_entry_price = Decimal("0")
                        stop_price = target_price = None
                    # else: avg_entry_price/stop_price/target_price stay as-is -
                    # the remainder is still the same position.

            # Ratchet after this bar's exits are settled, never before: raising
            # the stop on the same bar's high and then testing it against the
            # same bar's low would exit at the locked level on a bar that only
            # touched the trigger at its very end, an ordering OHLC cannot
            # justify. Deferring to the next bar assumes only that the trigger
            # was genuinely reached.
            if base_balance > 0 and stop_price is not None and self._trailing_trigger_pct > 0:
                trigger_at = avg_entry_price * (1 + self._trailing_trigger_pct / 100)
                if Decimal(str(candles.iloc[i]["high"])) >= trigger_at:
                    locked = avg_entry_price * (1 + self._trailing_lock_pct / 100)
                    if locked > stop_price:
                        stop_price = locked

            sliced_higher_tf_candles = None
            if higher_tf_candles is not None:
                current_ts = candles.index[i]
                sliced_higher_tf_candles = {
                    tf: df[df.index <= current_ts] for tf, df in higher_tf_candles.items()
                }

            pending_signal = self._strategy.generate_signal(
                self._symbol, candles.iloc[: i + 1], sliced_higher_tf_candles
            )

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
