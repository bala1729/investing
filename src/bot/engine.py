"""Trading engine: the single choke point where a signal becomes an order.

Both the TradingView webhook and an autonomous strategy loop route through
TradingEngine.process_signal(), so every trade - regardless of where the
signal came from - passes through the same risk gate before it can execute.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from loguru import logger

from src.bot.strategies.base import MTF_CONFIRMATION_MAP, Signal, Strategy, ohlcv_to_dataframe
from src.config import Settings, StopEnforcement, get_settings
from src.database.repository import UnitOfWork
from src.exchange.executor import Order, OrderExecutor, OrderSide, OrderStatus
from src.exchange.kraken import KrakenClient
from src.journal import record_execution
from src.notifications import SmsNotifier, format_fill_alert
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
      - Peak equity (for drawdown checks) is persisted per symbol in the
        peak_equity table, so the high-water mark survives restarts. It is
        never lowered; clearing that row is the only way to reset it.
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
        notifier: SmsNotifier | None = None,
    ) -> None:
        self._client = client
        self._executor = executor
        self._risk_manager = risk_manager
        self._settings = settings or get_settings()
        self._notifier = notifier or SmsNotifier(self._settings)

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

        # Kill switch gates entries only. Blocking an exit would trap capital in
        # exactly the situation someone reaches for a kill switch.
        if signal.side == OrderSide.BUY and self._kill_switch_engaged():
            logger.warning(
                f"Kill switch engaged ({self._settings.kill_switch_file}); "
                f"refusing new entry in {signal.symbol}"
            )
            return EngineResult(
                executed=False, reason="Kill switch engaged; new entries are halted"
            )

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
        # Persisted rather than in-memory: a restart used to reset the mark to
        # whatever equity happened to be at that moment, which disarmed the
        # drawdown limit exactly when it mattered - a bot is most likely to be
        # restarted right after something went wrong.
        async with UnitOfWork() as uow:
            peak_equity = await uow.peak_equity.record(signal.symbol, current_equity)
            await uow.commit()

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
                full_amount = min(position.amount, available)
                # The == 1.0 branch avoids Decimal trailing-zero padding from an
                # unnecessary multiply, so the default (full-exit) case is the
                # exact same Decimal it always was.
                amount = (
                    full_amount
                    if signal.exit_fraction == 1.0
                    else full_amount * Decimal(str(signal.exit_fraction))
                )

        if amount is None or amount <= 0:
            return EngineResult(executed=False, reason="No amount to trade")

        if limit_price is not None:
            order = await self._executor.execute_limit_order(
                signal.symbol, signal.side, amount, limit_price
            )
        else:
            order = await self._executor.execute_market_order(signal.symbol, signal.side, amount)

        closed_pnl: Decimal | None = None
        hold_seconds: float | None = None
        return_pct: float | None = None
        async with UnitOfWork() as uow:
            await uow.orders.create(order, strategy=signal.strategy)
            if order.status == OrderStatus.FILLED:
                await uow.trades.create(
                    order,
                    strategy=signal.strategy,
                    fee=order.fee,
                    fee_currency=order.fee_currency,
                )
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
                    # Same guarantee as the sizing branch above: a SELL that
                    # reached this point always had a real position.
                    assert position is not None
                    exit_price = order.average_fill_price or reference_price
                    remaining = position.amount - order.filled_amount
                    if remaining <= Decimal("0.00000001"):
                        closed = await uow.positions.close_position(signal.symbol, exit_price)
                    else:
                        closed = await uow.positions.reduce_position(
                            signal.symbol,
                            order.filled_amount,
                            exit_price,
                            clear_stop_loss=(signal.strategy == "stop_loss"),
                            clear_take_profit=(signal.strategy == "take_profit"),
                        )
                    if closed is not None:
                        closed_pnl = (exit_price - position.entry_price) * order.filled_amount
                        # SQLite drops tzinfo on round-trip even though the column is
                        # declared timezone=True - opened_at comes back naive, but it was
                        # always written as UTC (see Position.opened_at's default), so treat
                        # a naive value as UTC rather than let subtraction raise.
                        opened_at = position.opened_at
                        if opened_at.tzinfo is None:
                            opened_at = opened_at.replace(tzinfo=UTC)
                        hold_seconds = (datetime.now(UTC) - opened_at).total_seconds()
                        if position.entry_price:
                            return_pct = float(
                                (exit_price - position.entry_price)
                                / position.entry_price
                                * 100
                            )
            await uow.commit()

        logger.info(
            f"Signal executed: {signal.side.value} {order.amount} {signal.symbol} "
            f"-> {order.status.value}"
        )
        if order.status == OrderStatus.FILLED:
            await self._alert_fill(signal, order, closed_pnl)
            self._record_journal(signal, order, hold_seconds, return_pct, closed_pnl)
        return EngineResult(executed=True, order=order)

    def _kill_switch_engaged(self) -> bool:
        """Whether the kill-switch file exists right now.

        Re-read every cycle rather than cached at startup, so engaging it takes
        effect on the next poll without restarting anything.
        """
        path = self._settings.kill_switch_file
        return bool(path) and Path(path).exists()

    async def _alert_fill(
        self, signal: Signal, order: Order, closed_pnl: Decimal | None
    ) -> None:
        """Send a fill alert, never letting a notification failure reach the caller.

        SmsNotifier already swallows its own errors; this second guard covers
        anything raised while *building* the message. A trade that executed
        must never be reported as failed because an SMS could not be formatted.
        """
        try:
            await self._notifier.send(
                format_fill_alert(
                    action="ENTRY" if signal.side == OrderSide.BUY else "EXIT",
                    symbol=signal.symbol,
                    side=signal.side.value,
                    amount=f"{order.filled_amount:.6f}".rstrip("0").rstrip("."),
                    price=order.average_fill_price,
                    strategy=signal.strategy,
                    pnl=None if closed_pnl is None else f"{closed_pnl:+.2f}",
                    is_paper=order.is_paper,
                )
            )
        except Exception:
            logger.exception(f"Could not send fill alert for {signal.symbol}")

    def _record_journal(
        self,
        signal: Signal,
        order: Order,
        hold_seconds: float | None,
        return_pct: float | None,
        closed_pnl: Decimal | None,
    ) -> None:
        """Append to the shared trade journal, never letting a write failure reach the caller.

        Same philosophy as _alert_fill: a trade that executed must never be
        reported as failed - or worse, left half-applied - because a journal
        write hit a locked file or a full disk.
        """
        try:
            record_execution(
                self._settings.journal_db_path,
                symbol=signal.symbol,
                side=signal.side.value,
                strategy=signal.strategy,
                reason=signal.reason,
                amount=order.filled_amount,
                price=order.average_fill_price or Decimal("0"),
                fee=order.fee or Decimal("0"),
                is_paper=order.is_paper,
                hold_seconds=hold_seconds,
                return_pct=return_pct,
                realized_pnl=closed_pnl,
            )
        except Exception:
            logger.exception(f"Could not write trade journal entry for {signal.symbol}")

    async def enforce_stops(self, symbol: str) -> EngineResult | None:
        """Apply the trailing ratchet, and act on a stop-loss or take-profit, before any
        strategy runs.

        Returns None when the cycle should carry on to signal generation, or an
        EngineResult when the position was closed or reduced (by a level here,
        or by the exchange while the bot was away) and there is nothing
        further to do this cycle.

        Runs ahead of the strategy deliberately: risk management protecting
        capital must not wait behind a strategy that may or may not produce a
        signal, and a strategy should never be asked about a position that has
        already been stopped out or taken profit on.

        Stop-loss and take-profit are independently gated
        (`stop_enforcement`/`take_profit_enforcement`) and share one position
        load and one ticker fetch, but are otherwise separate mechanisms - a
        bot can run NATIVE stop-loss with POLL take-profit, take-profit only
        with stops off, or any other combination. If both would fire on the
        same read, stop-loss wins (matches Backtester's "assume the loss"
        precedent) - structurally unreachable for any valid config, since the
        take-profit target is always above entry and the stop always below,
        but checked in that order as defense in depth regardless. Take-profit
        is poll-only: no take-profit order type exists on the exchange client,
        so there is no NATIVE path for it the way there is for the stop.

        Exactly one mechanism ever sells the stop side. Under POLL the bot
        compares the ticker to the stop and sells at market; under NATIVE the
        exchange owns that decision and this method only keeps the resting
        order in sync. Both consume the same stop price from RiskManager, so
        switching mechanisms cannot change *where* the stop sits, only who
        acts on it.
        """
        enforcement = self._settings.effective_stop_enforcement
        stop_active = enforcement is not StopEnforcement.OFF
        tp_active = self._settings.take_profit_enforcement
        # Checked before touching the database: with both off this must cost
        # nothing at all, since it runs on every cycle of every bot.
        if not stop_active and not tp_active:
            return None

        async with UnitOfWork() as uow:
            position = await uow.positions.get_by_symbol(symbol)
            # A closed position leaves a zeroed row behind, so amount is the test.
            if position is None or position.amount <= 0:
                return None
            entry_price = position.entry_price
            amount = position.amount
            stop_price = position.stop_loss
            target_price = position.take_profit

        if stop_active and enforcement is StopEnforcement.NATIVE:
            reconciled = await self._reconcile_external_close(symbol, amount, stop_price)
            if reconciled is not None:
                return reconciled

        ticker = await self._client.fetch_ticker(symbol)
        price = Decimal(str(ticker["last"]))

        if stop_active:
            raised_stop = self._risk_manager.calculate_trailing_stop_price(
                entry_price, stop_price, price
            )
            stop_moved = False
            if raised_stop is not None:
                async with UnitOfWork() as uow:
                    stop_moved = await uow.positions.raise_stop_loss(symbol, raised_stop)
                    await uow.commit()
                if stop_moved:
                    stop_price = raised_stop
                    logger.info(
                        f"Trailing stop raised for {symbol}: stop now {raised_stop} "
                        f"(entry {entry_price}, price {price})"
                    )

            if stop_price is not None and enforcement is StopEnforcement.NATIVE:
                await self._sync_native_stop(symbol, amount, stop_price, replace=stop_moved)

        stop_breach = (
            stop_active
            and enforcement is not StopEnforcement.NATIVE
            and stop_price is not None
            and price <= stop_price
        )
        target_breach = tp_active and target_price is not None and price >= target_price

        if stop_breach:
            logger.warning(f"Stop-loss breached for {symbol}: price {price} <= stop {stop_price}")
            return await self.process_signal(
                Signal(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    strategy="stop_loss",
                    reason=f"Stop-loss hit: price {price} at or below stop {stop_price}",
                )
            )

        if target_breach:
            logger.info(f"Take-profit hit for {symbol}: price {price} >= target {target_price}")
            exit_fraction = float(Decimal(str(self._settings.take_profit_exit_pct)) / 100)
            return await self.process_signal(
                Signal(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    strategy="take_profit",
                    reason=f"Take-profit hit: price {price} at or above target {target_price}",
                    exit_fraction=exit_fraction,
                )
            )

        return None

    async def _reconcile_external_close(
        self, symbol: str, expected_amount: Decimal, stop_price: Decimal | None
    ) -> EngineResult | None:
        """Detect a position the exchange closed while the bot was not looking.

        Under NATIVE enforcement the stop rests on the exchange and can fill at
        any time, including while this process is stopped. The engine otherwise
        assumes it is the only actor - every database write follows an order it
        placed itself - so without this the bot would carry on believing it holds
        a position that no longer exists, and would refuse every subsequent BUY
        as "already holding".

        Detection is by balance rather than by order id: an order id would have
        to survive a restart in a column that does not exist, whereas the base
        balance is ground truth and also catches a manual close or an order
        placed outside the bot.
        """
        base = symbol.split("/")[0]
        available = await self._executor.get_balance(base)
        # Tolerate dust and rounding: only a materially smaller balance means gone.
        if available >= expected_amount * Decimal("0.99"):
            return None

        exit_price = await self._find_external_fill_price(symbol) or stop_price
        if exit_price is None:
            logger.error(
                f"{symbol} was closed externally but no fill price could be determined; "
                f"leaving the position open for manual reconciliation"
            )
            return None

        async with UnitOfWork() as uow:
            await uow.positions.close_position(symbol, exit_price)
            await uow.commit()
        logger.warning(
            f"Reconciled {symbol}: exchange balance {available} is below the recorded "
            f"position {expected_amount}, so the resting stop filled while the bot was "
            f"away. Closed locally at {exit_price}."
        )
        return EngineResult(
            executed=False,
            reason=f"Position in {symbol} was closed on the exchange; reconciled locally",
        )

    async def _find_external_fill_price(self, symbol: str) -> Decimal | None:
        """Best-effort actual fill price of an externally-closed position.

        Falls back to None (callers then use the stop price) rather than
        guessing: a wrong price here silently corrupts realized P&L, so an
        approximation is only acceptable when it is the stop we asked for.
        """
        try:
            closed = await self._client.fetch_closed_orders(symbol, limit=10)
        except Exception:
            logger.exception(f"Could not fetch closed orders for {symbol}")
            return None
        for order in closed:
            if order.get("side") != "sell":
                continue
            filled_price = order.get("average") or order.get("price")
            if filled_price:
                return Decimal(str(filled_price))
        return None

    async def _sync_native_stop(
        self, symbol: str, amount: Decimal, stop_price: Decimal, replace: bool
    ) -> None:
        """Ensure exactly one resting stop order sits at `stop_price`.

        Kraken has no in-place amend for this order type, so moving the stop is
        cancel-then-create. That gap is unavoidable and briefly leaves the
        position unprotected, which is why the cancel is only issued when the
        ratchet actually moved the stop (`replace`) rather than on every cycle.

        A cancel that fails because the order just filled is not an error - it is
        the race resolving in the exchange's favour, and the fill gets picked up
        by _reconcile_external_close() on the next cycle. Creating the new order
        is what must not be skipped.
        """
        try:
            resting = [
                order
                for order in await self._client.fetch_open_orders(symbol)
                if str(order.get("type", "")).replace("-", "_").startswith("stop")
            ]
        except Exception:
            logger.exception(f"Could not list open orders for {symbol}; skipping stop sync")
            return

        if resting and not replace:
            return

        for order in resting:
            try:
                await self._client.cancel_order(str(order["id"]), symbol)
            except Exception:
                # Most likely already filled - reconciliation will catch it.
                logger.warning(
                    f"Could not cancel resting stop {order.get('id')} for {symbol}; "
                    f"it may have just filled"
                )

        try:
            await self._client.create_stop_loss_order(
                symbol, "sell", float(amount), float(stop_price)
            )
            logger.info(f"Resting stop for {symbol} placed at {stop_price}")
        except Exception:
            logger.exception(
                f"FAILED to place resting stop for {symbol} at {stop_price} - the position "
                f"is unprotected until the next cycle"
            )

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
        stop_result = await self.enforce_stops(symbol)
        if stop_result is not None:
            return stop_result

        ohlcv = await self._client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1)
        candles = ohlcv_to_dataframe(ohlcv[:-1])

        higher_tf_candles: dict[str, pd.DataFrame] | None = None
        mtf_timeframes = MTF_CONFIRMATION_MAP.get(timeframe)
        if mtf_timeframes is not None:
            higher_tf_candles = {}
            for tf in mtf_timeframes:
                higher_ohlcv = await self._client.fetch_ohlcv(symbol, timeframe=tf, limit=limit + 1)
                higher_tf_candles[tf] = ohlcv_to_dataframe(higher_ohlcv[:-1])

        signal = strategy.generate_signal(symbol, candles, higher_tf_candles)
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
        cycle_timeout_seconds: float = 60,
    ) -> None:
        """Continuously poll for and act on strategy signals until the task is cancelled.

        Each cycle is bounded by cycle_timeout_seconds. Without this, a cycle
        that stalls (observed 2026-08-15: no exception, no open socket, event
        loop idle - reproducible even against a freshly created exchange
        client, pointing at ccxt's async throttler rather than the network)
        hangs forever with no recovery short of a manual kill. On timeout the
        exchange client is torn down and recreated - a fresh ccxt instance
        carries a fresh throttler/session, discarding whatever got wedged.
        """
        while True:
            try:
                await asyncio.wait_for(
                    self.run_strategy_once(strategy, symbol, timeframe, limit),
                    timeout=cycle_timeout_seconds,
                )
            except TimeoutError:
                logger.error(
                    f"Strategy cycle for {symbol} exceeded {cycle_timeout_seconds}s - "
                    "reconnecting exchange client"
                )
                await self._client.close()
                await self._client.initialize()
            except Exception:
                logger.exception(f"Error running strategy cycle for {symbol}")
            await asyncio.sleep(poll_interval_seconds)
