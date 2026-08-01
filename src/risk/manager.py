"""Risk manager: gates strategy signals before they reach the order executor."""

from dataclasses import dataclass
from decimal import Decimal

from src.bot.strategies.base import Signal
from src.config import Settings, get_settings
from src.exchange.executor import OrderSide


@dataclass(frozen=True)
class RiskDecision:
    """The outcome of evaluating a signal against risk limits.

    `position_size`, `stop_loss_price`, and `take_profit_price` are only set
    for an approved BUY (a new entry); a SELL (closing a position) is always
    approved with those left None, since risk management's job is to protect
    capital, never to trap you in a position by blocking an exit.
    """

    approved: bool
    reason: str | None = None
    position_size: Decimal | None = None
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None


class RiskManager:
    """Position sizing, stop-loss/take-profit pricing, and trading limits.

    Stateless by design, mirroring Strategy and Backtester: every check takes
    the account state it needs as explicit arguments rather than tracking it
    internally, so it's trivially testable without mocking. Assumes the
    long-only spot model used throughout this codebase (PaperTradingSimulator,
    Backtester) — there is no short-side entry to size or protect.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        risk_reward_ratio: Decimal = Decimal("2"),
    ) -> None:
        self._settings = settings or get_settings()
        if not (0 < self._settings.max_position_size_pct <= 100):
            raise ValueError("max_position_size_pct must be between 0 (exclusive) and 100")
        if not (0 < self._settings.max_drawdown_pct <= 100):
            raise ValueError("max_drawdown_pct must be between 0 (exclusive) and 100")
        if not (0 < self._settings.default_stop_loss_pct < 100):
            raise ValueError("default_stop_loss_pct must be between 0 and 100 (exclusive)")
        if self._settings.max_open_positions < 1:
            raise ValueError("max_open_positions must be at least 1")
        if risk_reward_ratio <= 0:
            raise ValueError("risk_reward_ratio must be positive")
        self._risk_reward_ratio = risk_reward_ratio

    def calculate_position_size(self, balance: Decimal, price: Decimal) -> Decimal:
        """Size a new position at `max_position_size_pct` of the given balance.

        Args:
            balance: Available quote-currency balance.
            price: Entry price.

        Returns:
            Position size in base-currency units.
        """
        if price <= 0:
            raise ValueError("price must be positive")
        max_pct = Decimal(str(self._settings.max_position_size_pct))
        return (balance * max_pct / 100) / price

    def calculate_stop_loss_price(self, entry_price: Decimal) -> Decimal:
        """Stop-loss price, `default_stop_loss_pct` below the entry price."""
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")
        stop_pct = Decimal(str(self._settings.default_stop_loss_pct))
        return entry_price * (1 - stop_pct / 100)

    def calculate_take_profit_price(
        self, entry_price: Decimal, risk_reward_ratio: Decimal | None = None
    ) -> Decimal:
        """Take-profit price, `risk_reward_ratio` times the stop-loss distance above entry."""
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")
        ratio = risk_reward_ratio if risk_reward_ratio is not None else self._risk_reward_ratio
        if ratio <= 0:
            raise ValueError("risk_reward_ratio must be positive")
        stop_pct = Decimal(str(self._settings.default_stop_loss_pct))
        return entry_price * (1 + (stop_pct / 100) * ratio)

    def is_drawdown_breached(self, peak_equity: Decimal, current_equity: Decimal) -> bool:
        """True if the decline from `peak_equity` exceeds `max_drawdown_pct`."""
        if peak_equity <= 0:
            return False
        drawdown_pct = (peak_equity - current_equity) / peak_equity * 100
        return drawdown_pct >= Decimal(str(self._settings.max_drawdown_pct))

    def is_exposure_limit_reached(self, open_position_count: int) -> bool:
        """True if already at or over `max_open_positions`."""
        return open_position_count >= self._settings.max_open_positions

    def evaluate_signal(
        self,
        signal: Signal,
        balance: Decimal,
        price: Decimal,
        peak_equity: Decimal,
        current_equity: Decimal,
        open_position_count: int,
    ) -> RiskDecision:
        """Gate a strategy signal, sizing and pricing stops for an approved entry.

        Args:
            signal: The strategy-generated signal to evaluate.
            balance: Available quote-currency balance to size a new entry from.
            price: Current market price for the signal's symbol.
            peak_equity: Historical high-water mark of total account equity.
            current_equity: Current total account equity.
            open_position_count: Number of currently open positions.

        Returns:
            An approved decision (with sizing/stops for a BUY) or a rejection
            with a human-readable reason.
        """
        if signal.side == OrderSide.SELL:
            return RiskDecision(approved=True)

        if self.is_drawdown_breached(peak_equity, current_equity):
            return RiskDecision(
                approved=False,
                reason=f"Max drawdown of {self._settings.max_drawdown_pct}% breached",
            )

        if self.is_exposure_limit_reached(open_position_count):
            return RiskDecision(
                approved=False,
                reason=f"Max open positions ({self._settings.max_open_positions}) reached",
            )

        return RiskDecision(
            approved=True,
            position_size=self.calculate_position_size(balance, price),
            stop_loss_price=self.calculate_stop_loss_price(price),
            take_profit_price=self.calculate_take_profit_price(price),
        )
