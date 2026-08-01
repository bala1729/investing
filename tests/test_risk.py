"""Tests for the risk manager: position sizing, stop-loss/take-profit, and trading limits."""

from decimal import Decimal

import pytest

from src.bot.strategies.base import Signal
from src.config import Settings
from src.exchange.executor import OrderSide
from src.risk.manager import RiskManager


def make_settings(
    max_position_size_pct: float = 5.0,
    max_drawdown_pct: float = 10.0,
    default_stop_loss_pct: float = 2.0,
    max_open_positions: int = 5,
) -> Settings:
    return Settings(
        _env_file=None,
        max_position_size_pct=max_position_size_pct,
        max_drawdown_pct=max_drawdown_pct,
        default_stop_loss_pct=default_stop_loss_pct,
        max_open_positions=max_open_positions,
    )


class TestRiskManagerValidation:
    def test_rejects_zero_max_position_size_pct(self) -> None:
        with pytest.raises(ValueError, match="max_position_size_pct"):
            RiskManager(make_settings(max_position_size_pct=0))

    def test_rejects_max_position_size_pct_over_100(self) -> None:
        with pytest.raises(ValueError, match="max_position_size_pct"):
            RiskManager(make_settings(max_position_size_pct=101))

    def test_rejects_zero_max_drawdown_pct(self) -> None:
        with pytest.raises(ValueError, match="max_drawdown_pct"):
            RiskManager(make_settings(max_drawdown_pct=0))

    def test_rejects_max_drawdown_pct_over_100(self) -> None:
        with pytest.raises(ValueError, match="max_drawdown_pct"):
            RiskManager(make_settings(max_drawdown_pct=101))

    def test_rejects_zero_default_stop_loss_pct(self) -> None:
        with pytest.raises(ValueError, match="default_stop_loss_pct"):
            RiskManager(make_settings(default_stop_loss_pct=0))

    def test_rejects_default_stop_loss_pct_at_100(self) -> None:
        with pytest.raises(ValueError, match="default_stop_loss_pct"):
            RiskManager(make_settings(default_stop_loss_pct=100))

    def test_rejects_zero_max_open_positions(self) -> None:
        with pytest.raises(ValueError, match="max_open_positions"):
            RiskManager(make_settings(max_open_positions=0))

    def test_rejects_non_positive_risk_reward_ratio(self) -> None:
        with pytest.raises(ValueError, match="risk_reward_ratio"):
            RiskManager(make_settings(), risk_reward_ratio=Decimal("0"))


class TestCalculatePositionSize:
    def test_sizes_to_max_position_pct_of_balance(self) -> None:
        manager = RiskManager(make_settings(max_position_size_pct=5.0))
        size = manager.calculate_position_size(Decimal("10000"), Decimal("50000"))
        assert size == Decimal("0.01")

    def test_rejects_non_positive_price(self) -> None:
        manager = RiskManager(make_settings())
        with pytest.raises(ValueError, match="price"):
            manager.calculate_position_size(Decimal("10000"), Decimal("0"))


class TestCalculateStopLossPrice:
    def test_stop_below_entry_by_configured_pct(self) -> None:
        manager = RiskManager(make_settings(default_stop_loss_pct=2.0))
        stop = manager.calculate_stop_loss_price(Decimal("50000"))
        assert stop == Decimal("49000")

    def test_rejects_non_positive_entry_price(self) -> None:
        manager = RiskManager(make_settings())
        with pytest.raises(ValueError, match="entry_price"):
            manager.calculate_stop_loss_price(Decimal("0"))


class TestCalculateTakeProfitPrice:
    def test_uses_default_risk_reward_ratio(self) -> None:
        manager = RiskManager(
            make_settings(default_stop_loss_pct=2.0), risk_reward_ratio=Decimal("2")
        )
        take_profit = manager.calculate_take_profit_price(Decimal("50000"))
        assert take_profit == Decimal("52000")

    def test_accepts_explicit_ratio_override(self) -> None:
        manager = RiskManager(
            make_settings(default_stop_loss_pct=2.0), risk_reward_ratio=Decimal("2")
        )
        take_profit = manager.calculate_take_profit_price(
            Decimal("50000"), risk_reward_ratio=Decimal("3")
        )
        assert take_profit == Decimal("53000")

    def test_rejects_non_positive_entry_price(self) -> None:
        manager = RiskManager(make_settings())
        with pytest.raises(ValueError, match="entry_price"):
            manager.calculate_take_profit_price(Decimal("0"))

    def test_rejects_non_positive_explicit_ratio(self) -> None:
        manager = RiskManager(make_settings())
        with pytest.raises(ValueError, match="risk_reward_ratio"):
            manager.calculate_take_profit_price(Decimal("50000"), risk_reward_ratio=Decimal("0"))


class TestIsDrawdownBreached:
    def test_below_limit_is_not_breached(self) -> None:
        manager = RiskManager(make_settings(max_drawdown_pct=10.0))
        assert manager.is_drawdown_breached(Decimal("10000"), Decimal("9100")) is False

    def test_at_limit_is_breached(self) -> None:
        manager = RiskManager(make_settings(max_drawdown_pct=10.0))
        assert manager.is_drawdown_breached(Decimal("10000"), Decimal("9000")) is True

    def test_beyond_limit_is_breached(self) -> None:
        manager = RiskManager(make_settings(max_drawdown_pct=10.0))
        assert manager.is_drawdown_breached(Decimal("10000"), Decimal("8000")) is True

    def test_non_positive_peak_is_not_breached(self) -> None:
        manager = RiskManager(make_settings())
        assert manager.is_drawdown_breached(Decimal("0"), Decimal("0")) is False


class TestIsExposureLimitReached:
    def test_below_limit(self) -> None:
        manager = RiskManager(make_settings(max_open_positions=2))
        assert manager.is_exposure_limit_reached(1) is False

    def test_at_limit(self) -> None:
        manager = RiskManager(make_settings(max_open_positions=2))
        assert manager.is_exposure_limit_reached(2) is True

    def test_beyond_limit(self) -> None:
        manager = RiskManager(make_settings(max_open_positions=2))
        assert manager.is_exposure_limit_reached(3) is True


def make_signal(side: OrderSide) -> Signal:
    return Signal(symbol="BTC/USD", side=side, strategy="test", reason="test")


class TestEvaluateSignal:
    def test_sell_is_always_approved_with_no_sizing(self) -> None:
        manager = RiskManager(make_settings())
        decision = manager.evaluate_signal(
            signal=make_signal(OrderSide.SELL),
            balance=Decimal("10000"),
            price=Decimal("50000"),
            peak_equity=Decimal("10000"),
            current_equity=Decimal("1000"),  # 90% drawdown - irrelevant for a SELL
            open_position_count=999,  # way over any limit - irrelevant for a SELL
        )
        assert decision.approved is True
        assert decision.position_size is None
        assert decision.stop_loss_price is None
        assert decision.take_profit_price is None

    def test_buy_approved_with_full_sizing(self) -> None:
        manager = RiskManager(
            make_settings(
                max_position_size_pct=5.0, default_stop_loss_pct=2.0, max_open_positions=5
            ),
            risk_reward_ratio=Decimal("2"),
        )
        decision = manager.evaluate_signal(
            signal=make_signal(OrderSide.BUY),
            balance=Decimal("10000"),
            price=Decimal("50000"),
            peak_equity=Decimal("10000"),
            current_equity=Decimal("10000"),
            open_position_count=0,
        )
        assert decision.approved is True
        assert decision.reason is None
        assert decision.position_size == Decimal("0.01")
        assert decision.stop_loss_price == Decimal("49000")
        assert decision.take_profit_price == Decimal("52000")

    def test_buy_rejected_when_drawdown_breached(self) -> None:
        manager = RiskManager(make_settings(max_drawdown_pct=10.0))
        decision = manager.evaluate_signal(
            signal=make_signal(OrderSide.BUY),
            balance=Decimal("10000"),
            price=Decimal("50000"),
            peak_equity=Decimal("10000"),
            current_equity=Decimal("8000"),
            open_position_count=0,
        )
        assert decision.approved is False
        assert decision.reason is not None
        assert "drawdown" in decision.reason.lower()
        assert decision.position_size is None

    def test_buy_rejected_when_exposure_limit_reached(self) -> None:
        manager = RiskManager(make_settings(max_open_positions=2))
        decision = manager.evaluate_signal(
            signal=make_signal(OrderSide.BUY),
            balance=Decimal("10000"),
            price=Decimal("50000"),
            peak_equity=Decimal("10000"),
            current_equity=Decimal("10000"),
            open_position_count=2,
        )
        assert decision.approved is False
        assert decision.reason is not None
        assert "positions" in decision.reason.lower()

    def test_drawdown_is_checked_before_exposure(self) -> None:
        manager = RiskManager(make_settings(max_drawdown_pct=10.0, max_open_positions=2))
        decision = manager.evaluate_signal(
            signal=make_signal(OrderSide.BUY),
            balance=Decimal("10000"),
            price=Decimal("50000"),
            peak_equity=Decimal("10000"),
            current_equity=Decimal("8000"),  # breached
            open_position_count=2,  # also at limit
        )
        assert decision.approved is False
        assert decision.reason is not None
        assert "drawdown" in decision.reason.lower()
