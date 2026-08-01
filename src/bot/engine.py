"""Trading engine: the single choke point where a signal becomes an order.

Both the TradingView webhook and an autonomous strategy loop route through
TradingEngine.process_signal(), so every trade - regardless of where the
signal came from - passes through the same risk gate before it can execute.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from loguru import logger

from src.bot.strategies.base import Signal, Strategy, ohlcv_to_dataframe
from src.config import Settings, get_settings
from src.database.repository import UnitOfWork
from src.exchange.executor import Order, OrderExecutor, OrderSide, OrderStatus
from src.exchange.kraken import KrakenClient
from src.risk.manager import RiskManager


@dataclass(frozen=True)
class EngineResult:
    """Outcome of running a signal through the trading engine."""

    executed: bool
    reason: str | None = None
    order: Order | None = None


class TradingEngine:
    """Orchestrates strategies, risk management, and order execution.

    Known limitations (v1):
      - One open position per symbol. A BUY signal for a symbol that's
        already held is skipped rather than pyramided into; a SELL with no
        open position is skipped rather than erroring.
      - Peak equity (for drawdown checks) is tracked in-memory per symbol
        for this process's lifetime only - it does not persist across
        restarts, so a restart resets the drawdown high-water mark.
      - An explicit `quantity` (e.g. from a TradingView webhook) is used
        as-is; the risk manager still gates *whether* the trade happens
        (drawdown/exposure) but does not clamp an externally-specified size.
    """

    def __init__(
        self,
        client: KrakenClient,
        executor: OrderExecutor,
        risk_manager: RiskManager,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._executor = executor
        self._risk_manager = risk_manager
        self._settings = settings or get_settings()
        self._peak_equity: dict[str, Decimal] = {}

    async def process_signal(
        self,
        signal: Signal,
        *,
        quantity: Decimal | None = None,
        limit_price: Decimal | None = None,
    ) -> EngineResult:
        """Risk-gate a signal and execute it if approved.

        Args:
            signal: The signal to act on (from a strategy or a webhook).
            quantity: Exact amount to trade, e.g. from a TradingView webhook.
                If omitted, the risk manager computes it from account balance.
            limit_price: Place a limit order at this price instead of a
                market order.

        Returns:
            Whether a trade executed, and why not if it didn't.
        """
        base, quote = signal.symbol.split("/")
        reference_price = limit_price
        if reference_price is None:
            ticker = await self._client.fetch_ticker(signal.symbol)
            reference_price = Decimal(str(ticker["last"]))

        balance = await self._executor.get_balance(quote)

        async with UnitOfWork() as uow:
            position = await uow.positions.get_by_symbol(signal.symbol)
            open_position_count = len(await uow.positions.get_all_open())

        # get_by_symbol() returns a row even after close_position() zeroes it out,
        # so "has a position" means amount > 0, not merely a non-None row.
        has_open_position = position is not None and position.amount > 0

        if signal.side == OrderSide.BUY and has_open_position:
            return EngineResult(
                executed=False, reason=f"Already holding a position in {signal.symbol}"
            )
        if signal.side == OrderSide.SELL and not has_open_position:
            return EngineResult(
                executed=False, reason=f"No open position in {signal.symbol} to sell"
            )

        position_value = (
            position.amount * reference_price
            if has_open_position and position is not None
            else Decimal("0")
        )
        current_equity = balance + position_value
        peak_equity = max(self._peak_equity.get(signal.symbol, current_equity), current_equity)
        self._peak_equity[signal.symbol] = peak_equity

        decision = self._risk_manager.evaluate_signal(
            signal=signal,
            balance=balance,
            price=reference_price,
            peak_equity=peak_equity,
            current_equity=current_equity,
            open_position_count=open_position_count,
        )
        if not decision.approved:
            logger.info(f"Signal rejected for {signal.symbol}: {decision.reason}")
            return EngineResult(executed=False, reason=decision.reason)

        if signal.side == OrderSide.BUY:
            amount = quantity if quantity is not None else decision.position_size
        else:
            # A SELL only reaches this point when has_open_position is True (see the
            # early return above), so `position` is guaranteed non-None here.
            assert position is not None
            if quantity is not None:
                amount = quantity
            else:
                # Position.amount is DB-rounded (8 decimal places) and can drift
                # slightly above what the executor actually holds - clamp to the
                # executor's real balance, which is always the ground truth for
                # what can actually be sold.
                available = await self._executor.get_balance(base)
                amount = min(position.amount, available)

        if amount is None or amount <= 0:
            return EngineResult(executed=False, reason="No amount to trade")

        if limit_price is not None:
            order = await self._executor.execute_limit_order(
                signal.symbol, signal.side, amount, limit_price
            )
        else:
            order = await self._executor.execute_market_order(signal.symbol, signal.side, amount)

        async with UnitOfWork() as uow:
            await uow.orders.create(order, strategy=signal.strategy)
            if order.status == OrderStatus.FILLED:
                await uow.trades.create(order, strategy=signal.strategy)
                if signal.side == OrderSide.BUY:
                    await uow.positions.create_or_update(
                        symbol=signal.symbol,
                        side="long",
                        amount=order.filled_amount,
                        entry_price=order.average_fill_price or reference_price,
                        strategy=signal.strategy,
                        is_paper=order.is_paper,
                        stop_loss=decision.stop_loss_price,
                        take_profit=decision.take_profit_price,
                    )
                else:
                    await uow.positions.close_position(
                        signal.symbol, order.average_fill_price or reference_price
                    )
            await uow.commit()

        logger.info(
            f"Signal executed: {signal.side.value} {order.amount} {signal.symbol} "
            f"-> {order.status.value}"
        )
        return EngineResult(executed=True, order=order)

    async def run_strategy_once(
        self,
        strategy: Strategy,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> EngineResult:
        """Fetch recent candles, ask the strategy for a signal, and process it if there is one.

        Fetches one extra candle and drops the newest before handing candles
        to the strategy — the most recent candle from the exchange is still
        forming (its close is just the latest trade price, and its H/L/V
        keep changing until the period actually closes). Acting on a signal
        computed against that partial bar would be inconsistent with
        backtesting, where every bar evaluated is always a closed historical
        candle ("repainting", in TradingView terms) — this keeps live signal
        generation on the same footing as the backtester.
        """
        ohlcv = await self._client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1)
        candles = ohlcv_to_dataframe(ohlcv[:-1])
        signal = strategy.generate_signal(symbol, candles)
        if signal is None:
            return EngineResult(executed=False, reason="Strategy produced no signal")
        return await self.process_signal(signal)

    async def run_forever(
        self,
        strategy: Strategy,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        poll_interval_seconds: float = 60,
    ) -> None:
        """Continuously poll for and act on strategy signals until the task is cancelled."""
        while True:
            try:
                await self.run_strategy_once(strategy, symbol, timeframe, limit)
            except Exception:
                logger.exception(f"Error running strategy cycle for {symbol}")
            await asyncio.sleep(poll_interval_seconds)
