"""Tests for the walk-forward backtesting engine."""

from decimal import Decimal

import pandas as pd
import pytest

from src.backtest.engine import (
    Backtester,
    BacktestResult,
    BacktestTrade,
    buy_and_hold_return_pct,
)
from src.bot.strategies.base import Signal, Strategy
from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy
from src.exchange.executor import OrderSide


class ScriptedStrategy(Strategy):
    """Test double: emits a pre-programmed signal keyed by the last visible bar's index."""

    def __init__(self, signals: dict[int, Signal]) -> None:
        super().__init__(name="scripted")
        self._signals = signals

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        return self._signals.get(len(candles) - 1)


class RecordingStrategy(Strategy):
    """Test double: records the higher_tf_candles dict it was given on every call."""

    def __init__(self) -> None:
        super().__init__(name="recording")
        self.calls: list[tuple[pd.Timestamp, dict[str, pd.DataFrame] | None]] = []

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        self.calls.append((candles.index[-1], higher_tf_candles))
        return None


def buy(reason: str = "go long") -> Signal:
    return Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="scripted", reason=reason)


def sell(reason: str = "go flat") -> Signal:
    return Signal(symbol="BTC/USD", side=OrderSide.SELL, strategy="scripted", reason=reason)


def make_candles(opens: list[float], closes: list[float] | None = None) -> pd.DataFrame:
    """Build an OHLCV DataFrame; only open/close matter for the engine under test."""
    closes = closes if closes is not None else opens
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "volume": [100.0] * len(opens),
        },
        index=pd.date_range("2026-01-01", periods=len(opens), freq="1h", tz="UTC"),
    )


class TestBacktesterValidation:
    def test_rejects_zero_position_size(self) -> None:
        with pytest.raises(ValueError, match="position_size_pct"):
            Backtester(ScriptedStrategy({}), "BTC/USD", position_size_pct=Decimal("0"))

    def test_rejects_position_size_over_100(self) -> None:
        with pytest.raises(ValueError, match="position_size_pct"):
            Backtester(ScriptedStrategy({}), "BTC/USD", position_size_pct=Decimal("101"))

    def test_rejects_negative_fee_pct(self) -> None:
        with pytest.raises(ValueError, match="fee_pct"):
            Backtester(ScriptedStrategy({}), "BTC/USD", fee_pct=Decimal("-1"))

    def test_rejects_negative_slippage_pct(self) -> None:
        with pytest.raises(ValueError, match="slippage_pct"):
            Backtester(ScriptedStrategy({}), "BTC/USD", slippage_pct=Decimal("-1"))


class TestBacktesterFeesAndSlippage:
    def test_buy_fee_reduces_amount_received(self) -> None:
        strategy = ScriptedStrategy({0: buy()})
        candles = make_candles([100, 90, 999])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), fee_pct=Decimal("10")
        )

        result = backtester.run(candles)

        trade = result.trades[0]
        assert trade.price == Decimal("90")  # no slippage configured
        assert trade.fee == Decimal("100")  # 10% of the 1000 spent
        assert trade.amount == Decimal("10")  # (1000 - 100) / 90

    def test_buy_slippage_worsens_fill_price(self) -> None:
        strategy = ScriptedStrategy({0: buy()})
        candles = make_candles([100, 100, 999])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), slippage_pct=Decimal("2")
        )

        result = backtester.run(candles)

        assert result.trades[0].price == Decimal("102")  # 100 * 1.02
        assert result.trades[0].fee == Decimal("0")

    def test_sell_slippage_worsens_fill_price(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 1: sell()})
        candles = make_candles([100, 100, 100])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), slippage_pct=Decimal("2")
        )

        result = backtester.run(candles)

        assert result.trades[1].price == Decimal("98")  # 100 * 0.98

    def test_fee_on_round_trip_reduces_realized_pnl(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 2: sell()})
        candles = make_candles(opens=[100, 90, 999, 120])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), fee_pct=Decimal("10")
        )

        result = backtester.run(candles)

        buy_trade, sell_trade = result.trades
        assert buy_trade.fee == Decimal("100")
        assert buy_trade.amount == Decimal("10")

        assert sell_trade.fee == Decimal("120")  # 10% of 10 * 120 gross proceeds
        assert sell_trade.pnl == Decimal("80")  # net proceeds 1080 - cost basis 1000
        assert result.ending_balance == Decimal("1080")
        assert result.total_return_pct == Decimal("8")

    def test_total_fees_paid_sums_across_trades(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 2: sell()})
        candles = make_candles(opens=[100, 90, 999, 120])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), fee_pct=Decimal("10")
        )

        result = backtester.run(candles)

        assert result.total_fees_paid == Decimal("100") + Decimal("120")

    def test_zero_fee_and_slippage_matches_frictionless_defaults(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 2: sell()})
        candles = make_candles(opens=[100, 50, 999, 80])
        backtester = Backtester(
            strategy,
            "BTC/USD",
            starting_balance=Decimal("1000"),
            fee_pct=Decimal("0"),
            slippage_pct=Decimal("0"),
        )

        result = backtester.run(candles)

        assert result.trades[1].pnl == Decimal("600")
        assert result.total_fees_paid == Decimal("0")


class TestBacktesterRun:
    def test_no_signals_leaves_balance_unchanged(self) -> None:
        strategy = ScriptedStrategy({})
        candles = make_candles([100, 101, 102, 103])
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("10000"))

        result = backtester.run(candles)

        assert result.trades == []
        assert result.ending_balance == Decimal("10000")
        assert result.total_return_pct == Decimal("0")
        assert len(result.equity_curve) == 4
        assert all(eq == Decimal("10000") for eq in result.equity_curve)

    def test_empty_candles_produce_empty_result(self) -> None:
        strategy = ScriptedStrategy({})
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("10000"))

        result = backtester.run(make_candles([]))

        assert result.trades == []
        assert result.equity_curve == []
        assert result.ending_balance == Decimal("10000")

    def test_buy_signal_fills_at_next_bar_open_not_same_bar(self) -> None:
        strategy = ScriptedStrategy({0: buy()})
        candles = make_candles(opens=[100, 110, 120], closes=[105, 115, 125])
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        result = backtester.run(candles)

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.side == OrderSide.BUY
        assert trade.price == Decimal("110")
        assert trade.amount == Decimal("1000") / Decimal("110")
        assert trade.timestamp == candles.index[1]

    def test_signal_on_final_bar_is_never_filled(self) -> None:
        strategy = ScriptedStrategy({3: buy()})
        candles = make_candles([100, 101, 102, 103])
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        result = backtester.run(candles)

        assert result.trades == []

    def test_buy_then_sell_round_trip_computes_pnl(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 2: sell("take profit")})
        candles = make_candles(opens=[100, 50, 999, 80])
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        result = backtester.run(candles)

        assert len(result.trades) == 2
        buy_trade, sell_trade = result.trades
        assert buy_trade.side == OrderSide.BUY
        assert buy_trade.price == Decimal("50")
        assert buy_trade.amount == Decimal("20")
        assert buy_trade.pnl is None

        assert sell_trade.side == OrderSide.SELL
        assert sell_trade.price == Decimal("80")
        assert sell_trade.amount == Decimal("20")
        assert sell_trade.pnl == Decimal("600")
        assert sell_trade.reason == "take profit"

        assert result.ending_balance == Decimal("1600")
        assert result.total_return_pct == Decimal("60")

    def test_sell_signal_ignored_without_open_position(self) -> None:
        strategy = ScriptedStrategy({0: sell()})
        candles = make_candles([100, 101, 102])
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        result = backtester.run(candles)

        assert result.trades == []
        assert result.ending_balance == Decimal("1000")

    def test_buy_signal_ignored_without_quote_balance(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 2: buy("second attempt")})
        candles = make_candles([100, 100, 100, 100])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), position_size_pct=Decimal("100")
        )

        result = backtester.run(candles)

        assert len(result.trades) == 1

    def test_repeated_buy_while_holding_does_not_pyramid(self) -> None:
        """A BUY while already holding is skipped, matching TradingEngine.

        Strategies emit an entry signal on every bar the entry conditions hold,
        not only on the bar they first become true, so this fires constantly
        during a trend. Adding to the position each time would model something
        the live engine would never do (it skips a BUY for a symbol it already
        holds), and with partial position sizing it would quietly scale into a
        far larger position than intended.
        """
        strategy = ScriptedStrategy({0: buy(), 1: buy("still bullish"), 2: buy("still bullish")})
        candles = make_candles([100, 100, 100, 100])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), position_size_pct=Decimal("50")
        )

        result = backtester.run(candles)

        assert len(result.trades) == 1
        assert result.trades[0].amount == Decimal("5")  # 50% of 1000 at 100
        # flat prices throughout: no realized or unrealized gain
        assert result.ending_balance == Decimal("1000")

    def test_buy_allowed_again_after_position_is_closed(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 1: sell(), 2: buy("re-entry")})
        candles = make_candles([100, 100, 100, 100])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), position_size_pct=Decimal("50")
        )

        result = backtester.run(candles)

        assert [t.side for t in result.trades] == [OrderSide.BUY, OrderSide.SELL, OrderSide.BUY]

    def test_higher_tf_candles_are_sliced_without_lookahead(self) -> None:
        strategy = RecordingStrategy()
        candles = make_candles([100.0, 101.0, 102.0, 103.0, 104.0])
        higher_tf = make_candles([50.0 + i for i in range(20)])  # denser series, same start
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        backtester.run(candles, higher_tf_candles={"1h": higher_tf})

        assert len(strategy.calls) == 5
        for primary_ts, higher_tf_candles_seen in strategy.calls:
            assert higher_tf_candles_seen is not None
            sliced = higher_tf_candles_seen["1h"]
            assert (sliced.index <= primary_ts).all()

    def test_no_higher_tf_candles_passes_none_through(self) -> None:
        strategy = RecordingStrategy()
        candles = make_candles([100.0, 101.0, 102.0])
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        backtester.run(candles)

        assert len(strategy.calls) == 3
        assert all(higher_tf_candles is None for _, higher_tf_candles in strategy.calls)

    def test_mtf_confirmation_suppresses_an_otherwise_valid_buy(self) -> None:
        closes = [
            100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 90.0,
            100.0, 110.0, 115.0,
        ]
        candles = make_candles(closes)
        downtrend = make_candles(
            [130.0 - i * 2.0 for i in range(20)], closes=[130.0 - i * 2.0 for i in range(20)]
        )
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        result = backtester.run(candles, higher_tf_candles={"1h": downtrend})

        assert result.trades == []

    def test_mtf_confirmation_allows_a_buy_when_higher_tf_aligned(self) -> None:
        closes = [
            100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 90.0,
            100.0, 110.0, 115.0,
        ]
        candles = make_candles(closes)
        uptrend = make_candles(
            [50.0 + i * 2.0 for i in range(20)], closes=[50.0 + i * 2.0 for i in range(20)]
        )
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        backtester = Backtester(strategy, "BTC/USD", starting_balance=Decimal("1000"))

        result = backtester.run(candles, higher_tf_candles={"1h": uptrend})

        assert len(result.trades) == 1
        assert result.trades[0].side == OrderSide.BUY


class TestBacktestResultProperties:
    def test_total_return_pct_handles_zero_starting_balance(self) -> None:
        result = BacktestResult(
            symbol="BTC/USD",
            strategy="s",
            starting_balance=Decimal("0"),
            ending_balance=Decimal("0"),
            trades=[],
            equity_curve=[],
        )
        assert result.total_return_pct == Decimal("0")

    def test_win_rate_none_when_no_closed_trades(self) -> None:
        result = BacktestResult(
            symbol="BTC/USD",
            strategy="s",
            starting_balance=Decimal("100"),
            ending_balance=Decimal("100"),
            trades=[],
            equity_curve=[Decimal("100")],
        )
        assert result.win_rate_pct is None
        assert result.closed_trades == []

    def test_win_rate_with_mixed_outcomes(self) -> None:
        ts = pd.Timestamp("2026-01-01", tz="UTC")
        trades = [
            BacktestTrade(ts, OrderSide.BUY, Decimal("100"), Decimal("1"), "buy"),
            BacktestTrade(
                ts, OrderSide.SELL, Decimal("110"), Decimal("1"), "win", pnl=Decimal("10")
            ),
            BacktestTrade(ts, OrderSide.BUY, Decimal("100"), Decimal("1"), "buy"),
            BacktestTrade(
                ts, OrderSide.SELL, Decimal("90"), Decimal("1"), "loss", pnl=Decimal("-10")
            ),
        ]
        result = BacktestResult(
            symbol="BTC/USD",
            strategy="s",
            starting_balance=Decimal("100"),
            ending_balance=Decimal("100"),
            trades=trades,
            equity_curve=[Decimal("100")],
        )
        assert len(result.closed_trades) == 2
        assert result.win_rate_pct == Decimal("50")

    def test_max_drawdown_pct_empty_curve(self) -> None:
        result = BacktestResult(
            symbol="BTC/USD",
            strategy="s",
            starting_balance=Decimal("100"),
            ending_balance=Decimal("100"),
            trades=[],
            equity_curve=[],
        )
        assert result.max_drawdown_pct == Decimal("0")

    def test_max_drawdown_pct_tracks_peak_to_trough(self) -> None:
        result = BacktestResult(
            symbol="BTC/USD",
            strategy="s",
            starting_balance=Decimal("100"),
            ending_balance=Decimal("110"),
            trades=[],
            equity_curve=[Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110")],
        )
        assert result.max_drawdown_pct == Decimal("25")


class TestBuyAndHoldReturnPct:
    def test_empty_candles_returns_zero(self) -> None:
        assert buy_and_hold_return_pct(make_candles([])) == Decimal("0")

    def test_computes_return_from_first_open_to_last_close(self) -> None:
        candles = make_candles(opens=[100, 105, 110], closes=[102, 108, 120])
        assert buy_and_hold_return_pct(candles) == Decimal("20")

    def test_negative_return(self) -> None:
        candles = make_candles(opens=[100, 90], closes=[95, 80])
        assert buy_and_hold_return_pct(candles) == Decimal("-20")

    def test_zero_entry_price_returns_zero(self) -> None:
        candles = make_candles(opens=[0, 90], closes=[0, 80])
        assert buy_and_hold_return_pct(candles) == Decimal("0")


def ohlc_candles(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Build candles with explicit (open, high, low, close) so wicks can be controlled."""
    return pd.DataFrame(
        {
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[3] for b in bars],
            "volume": [100.0] * len(bars),
        },
        index=pd.date_range("2026-01-01", periods=len(bars), freq="1h", tz="UTC"),
    )


class TestBacktesterStops:
    """Stop-loss, take-profit, and the trailing ratchet.

    Without these the ratchet could not be measured against the strategies
    already logged in docs/backtest-results.md, which is the whole reason for
    modelling them here rather than only in the live engine.
    """

    def test_disabled_by_default(self) -> None:
        """Existing results must not shift because stops became available."""
        candles = ohlc_candles([(100, 100, 100, 100), (100, 100, 50, 100), (100, 100, 100, 100)])
        result = Backtester(
            ScriptedStrategy({0: buy()}), "BTC/USD", starting_balance=Decimal("1000")
        ).run(candles)
        assert [t.side for t in result.trades] == [OrderSide.BUY]

    def test_stop_loss_exits_on_the_bar_that_breaches_it(self) -> None:
        # entry fills at bar 1's open of 100, stop 2% below at 98
        candles = ohlc_candles(
            [(100, 100, 100, 100), (100, 101, 100, 101), (101, 101, 97, 97), (97, 97, 97, 97)]
        )
        result = Backtester(
            ScriptedStrategy({0: buy()}),
            "BTC/USD",
            starting_balance=Decimal("1000"),
            stop_loss_pct=Decimal("2"),
        ).run(candles)

        exits = [t for t in result.trades if t.side == OrderSide.SELL]
        assert len(exits) == 1
        assert exits[0].price == Decimal("98")
        assert "Stop-loss hit" in exits[0].reason

    def test_take_profit_exits_on_the_bar_that_reaches_it(self) -> None:
        candles = ohlc_candles(
            [(100, 100, 100, 100), (100, 100, 100, 100), (100, 105, 100, 104)]
        )
        result = Backtester(
            ScriptedStrategy({0: buy()}),
            "BTC/USD",
            starting_balance=Decimal("1000"),
            take_profit_pct=Decimal("4"),
        ).run(candles)

        exits = [t for t in result.trades if t.side == OrderSide.SELL]
        assert len(exits) == 1
        assert exits[0].price == Decimal("104")
        assert "Take-profit hit" in exits[0].reason

    def test_stop_wins_when_one_bar_spans_both_levels(self) -> None:
        """OHLC cannot order the touches; assuming the loss keeps results honest."""
        candles = ohlc_candles(
            [(100, 100, 100, 100), (100, 100, 100, 100), (100, 105, 97, 100)]
        )
        result = Backtester(
            ScriptedStrategy({0: buy()}),
            "BTC/USD",
            starting_balance=Decimal("1000"),
            stop_loss_pct=Decimal("2"),
            take_profit_pct=Decimal("4"),
        ).run(candles)

        exits = [t for t in result.trades if t.side == OrderSide.SELL]
        assert len(exits) == 1
        assert "Stop-loss hit" in exits[0].reason

    def test_trailing_ratchet_turns_a_loser_into_a_winner(self) -> None:
        """Reaching +2% then collapsing exits at +1% instead of -2%."""
        candles = ohlc_candles(
            [
                (100, 100, 100, 100),
                (100, 100, 100, 100),   # entry fills here at 100
                (100, 103, 100, 103),   # touches +3%, arming the ratchet
                (103, 103, 95, 95),     # collapse: raised stop at 101 catches it
            ]
        )
        result = Backtester(
            ScriptedStrategy({0: buy()}),
            "BTC/USD",
            starting_balance=Decimal("1000"),
            stop_loss_pct=Decimal("2"),
            trailing_trigger_pct=Decimal("2"),
            trailing_lock_pct=Decimal("1"),
        ).run(candles)

        exits = [t for t in result.trades if t.side == OrderSide.SELL]
        assert len(exits) == 1
        assert exits[0].price == Decimal("101")
        assert exits[0].pnl is not None and exits[0].pnl > 0

    def test_ratchet_does_not_arm_on_the_same_bar_it_triggers(self) -> None:
        """A bar that touches +2% and falls back must not exit at +1% within that bar.

        OHLC gives no ordering, so treating the high as preceding the low would
        manufacture an exit the data cannot support.
        """
        candles = ohlc_candles(
            [
                (100, 100, 100, 100),
                (100, 100, 100, 100),   # entry at 100
                (100, 103, 100.5, 100.5),  # touches +3% and dips below 101 in the same bar
                (100.5, 100.6, 100.5, 100.6),
            ]
        )
        result = Backtester(
            ScriptedStrategy({0: buy()}),
            "BTC/USD",
            starting_balance=Decimal("1000"),
            stop_loss_pct=Decimal("2"),
            trailing_trigger_pct=Decimal("2"),
            trailing_lock_pct=Decimal("1"),
        ).run(candles)

        # Bar 2 arms the ratchet; bar 3 (low 100.5) is what the raised stop catches.
        exits = [t for t in result.trades if t.side == OrderSide.SELL]
        assert len(exits) == 1
        assert exits[0].timestamp == candles.index[3]

    def test_stop_exit_supersedes_a_pending_strategy_signal(self) -> None:
        """Matches the live engine, where enforce_stops() runs before the strategy."""
        candles = ohlc_candles(
            [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 97, 97), (97, 97, 97, 97)]
        )
        result = Backtester(
            ScriptedStrategy({0: buy(), 1: sell("strategy exit")}),
            "BTC/USD",
            starting_balance=Decimal("1000"),
            stop_loss_pct=Decimal("2"),
        ).run(candles)

        exits = [t for t in result.trades if t.side == OrderSide.SELL]
        assert len(exits) == 1
        assert "Stop-loss hit" in exits[0].reason

    def test_can_re_enter_after_being_stopped_out(self) -> None:
        candles = ohlc_candles(
            [
                (100, 100, 100, 100),
                (100, 100, 100, 100),   # entry
                (100, 100, 97, 97),     # stopped out at 98
                (98, 98, 98, 98),
                (98, 98, 98, 98),       # re-entry
                (98, 98, 98, 98),
            ]
        )
        result = Backtester(
            ScriptedStrategy({0: buy(), 3: buy("re-enter")}),
            "BTC/USD",
            starting_balance=Decimal("1000"),
            stop_loss_pct=Decimal("2"),
        ).run(candles)

        assert [t.side for t in result.trades] == [
            OrderSide.BUY, OrderSide.SELL, OrderSide.BUY
        ]

    def test_rejects_a_trailing_stop_without_a_stop_to_raise(self) -> None:
        with pytest.raises(ValueError, match="needs stop_loss_pct set"):
            Backtester(
                ScriptedStrategy({}), "BTC/USD",
                trailing_trigger_pct=Decimal("2"), trailing_lock_pct=Decimal("1"),
            )

    def test_rejects_lock_at_or_above_trigger(self) -> None:
        with pytest.raises(ValueError, match="must be below trailing_trigger_pct"):
            Backtester(
                ScriptedStrategy({}), "BTC/USD", stop_loss_pct=Decimal("2"),
                trailing_trigger_pct=Decimal("2"), trailing_lock_pct=Decimal("2"),
            )

    def test_rejects_out_of_range_stop_loss(self) -> None:
        with pytest.raises(ValueError, match="stop_loss_pct must be between"):
            Backtester(ScriptedStrategy({}), "BTC/USD", stop_loss_pct=Decimal("100"))

    def test_rejects_negative_take_profit(self) -> None:
        with pytest.raises(ValueError, match="take_profit_pct cannot be negative"):
            Backtester(ScriptedStrategy({}), "BTC/USD", take_profit_pct=Decimal("-1"))

    def test_rejects_negative_trailing_percentages(self) -> None:
        with pytest.raises(ValueError, match="trailing stop percentages cannot be negative"):
            Backtester(ScriptedStrategy({}), "BTC/USD", trailing_lock_pct=Decimal("-1"))
