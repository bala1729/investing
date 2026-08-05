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
        if not (0 < self._settings.risk_per_trade_pct <= 100):
            raise ValueError("risk_per_trade_pct must be between 0 (exclusive) and 100")
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

    def calculate_position_size(
        self,
        balance: Decimal,
        price: Decimal,
        stop_loss_price: Decimal,
        equity: Decimal | None = None,
    ) -> Decimal:
        """Size a new position from risk-per-trade, capped by `max_position_size_pct`.

        Risk-based: sized so that if the stop-loss is hit, the loss equals
        `risk_per_trade_pct` of account equity — this keeps risk-per-trade
        constant regardless of how close or far the stop happens to be,
        rather than sizing off `max_position_size_pct` alone (which lets the
        actual dollar risk balloon whenever the stop is wide).
        `max_position_size_pct` still applies as a secondary cap on capital
        deployed, so a very tight stop can't imply an oversized position.

        Args:
            balance: Available quote-currency balance (caps capital deployed).
            price: Entry price.
            stop_loss_price: Stop-loss price for this entry; must be below price.
            equity: Total account equity to size risk from. Defaults to
                `balance` if not given (e.g. no other open positions to add in).

        Returns:
            Position size in base-currency units.
        """
        if price <= 0:
            raise ValueError("price must be positive")
        if not (0 < stop_loss_price < price):
            raise ValueError("stop_loss_price must be positive and below price")

        equity_base = equity if equity is not None else balance
        risk_pct = Decimal(str(self._settings.risk_per_trade_pct))
        risk_amount = equity_base * risk_pct / 100
        stop_distance = price - stop_loss_price
        risk_based_size = risk_amount / stop_distance

        max_pct = Decimal(str(self._settings.max_position_size_pct))
        capital_cap_size = (balance * max_pct / 100) / price

        return min(risk_based_size, capital_cap_size)

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

    def calculate_trailing_stop_price(
        self, entry_price: Decimal, current_stop: Decimal | None, price: Decimal
    ) -> Decimal | None:
        """The stop-loss price after applying the trailing ratchet, or None to leave it alone.

        A one-step ratchet, not a continuously trailing stop: once `price` has
        reached `trailing_stop_trigger_pct` above entry, the stop moves up to
        `trailing_stop_lock_pct` above entry and then holds there for the life of
        the position.

        Deliberately returns a *price* and never touches storage or the exchange,
        so both enforcement mechanisms consume the same number: poll-based
        enforcement compares the live price to it, native enforcement submits it
        as a resting order. That is what makes the ratchet identical in paper and
        live trading.

        The result is monotonic - None is returned rather than a lower price when
        the ratchet would not raise the stop. A stop that can move down is not a
        stop; it would let a position that already ran up be closed further and
        further below its high, and on a cancel/replace mechanism a transient bad
        price could otherwise widen a resting order.
        """
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        trigger_pct = Decimal(str(self._settings.trailing_stop_trigger_pct))
        if trigger_pct <= 0:
            return None

        if price < entry_price * (1 + trigger_pct / 100):
            return None

        lock_pct = Decimal(str(self._settings.trailing_stop_lock_pct))
        raised = entry_price * (1 + lock_pct / 100)
        if current_stop is not None and raised <= current_stop:
            return None
        return raised

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

        stop_loss_price = self.calculate_stop_loss_price(price)
        take_profit_price = self.calculate_take_profit_price(price)
        position_size = self.calculate_position_size(
            balance, price, stop_loss_price, equity=current_equity
        )

        return RiskDecision(
            approved=True,
            position_size=position_size,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )
