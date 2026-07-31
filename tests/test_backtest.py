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
from src.exchange.executor import OrderSide


class ScriptedStrategy(Strategy):
    """Test double: emits a pre-programmed signal keyed by the last visible bar's index."""

    def __init__(self, signals: dict[int, Signal]) -> None:
        super().__init__(name="scripted")
        self._signals = signals

    def generate_signal(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        return self._signals.get(len(candles) - 1)


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

    def test_partial_position_size_compounds_avg_entry_price(self) -> None:
        strategy = ScriptedStrategy({0: buy(), 1: buy("add to position")})
        candles = make_candles([100, 100, 100, 100])
        backtester = Backtester(
            strategy, "BTC/USD", starting_balance=Decimal("1000"), position_size_pct=Decimal("50")
        )

        result = backtester.run(candles)

        assert len(result.trades) == 2
        assert result.trades[0].amount == Decimal("5")
        assert result.trades[1].amount == Decimal("2.5")
        # flat prices throughout: no realized or unrealized gain
        assert result.ending_balance == Decimal("1000")


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
