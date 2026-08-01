# Kraken Trading Bot - Project Status

**Last Updated:** 2026-07-31
**Project Location:** `/Users/balan/workspace/github/investing`
**Repository:** [bala1729/investing](git@github.com:bala1729/investing.git) (git, remote `origin`)

## Project Overview

A cryptocurrency trading bot for Kraken exchange with TradingView webhook integration. Designed to support both paper trading and live trading modes.

## Implementation Status

### ✅ Completed

| Component | Location | Description |
|-----------|----------|-------------|
| Project Structure | Root directory | Full directory scaffold created |
| Configuration | `src/config.py` | Pydantic-based settings with env var support |
| Config Tests | `tests/test_config.py` | Unit tests for settings and trading mode |
| Dependencies | `pyproject.toml` | All required packages defined |
| Environment Template | `.env.example` | Template for required env variables |
| Design Documentation | `docs/trading-bot-design.md` | Comprehensive architecture docs |
| Git Ignore | `.gitignore` | Proper exclusions for secrets/artifacts |
| Kraken Client | `src/exchange/kraken.py` | Async Kraken exchange client using CCXT |
| Order Executor | `src/exchange/executor.py` | Order execution with paper trading simulation |
| Database Models | `src/database/models.py` | SQLAlchemy models (Trade, Order, Position, Performance) |
| Database Repository | `src/database/repository.py` | Data access layer with Unit of Work pattern |
| Webhook API | `src/api/`, `src/main.py` | FastAPI app with `POST /webhook/tradingview` (secret-validated) and `GET /health` |
| README | `README.md` | Setup/run/test instructions (was missing) |
| Quality Gate | `pyproject.toml`, `tests/` | `ruff` + `mypy --strict` clean; 88% min coverage enforced via `pytest --cov-fail-under=88` (currently ~99.8%); mandate incl. 1000-line file / 200-line function caps documented in `docs/trading-bot-design.md` |
| CI | `.github/workflows/ci.yml` | GitHub Actions: lint, typecheck, test+coverage, and `pip-audit` dependency vulnerability scan, all as separate jobs on push/PR to `main` |
| Strategy Framework | `src/bot/strategies/` | `Strategy` ABC + `Signal` value object + shared `detect_crossover()` helper (`base.py`), `ohlcv_to_dataframe()` helper, and two example strategies under `examples/`: `MovingAverageCrossoverStrategy` (SMA) and `EMACrossoverStrategy` (EMA), selectable via `scripts/backtest.py --strategy sma\|ema` for direct comparison. Pure functions of candle data → signal; no I/O, not yet wired into an engine |
| Backtesting Engine | `src/backtest/engine.py`, `scripts/backtest.py` | Walk-forward `Backtester`: replays a `Strategy` bar-by-bar over historical candles, no lookahead (signals fill on the *next* bar's open). Long-only spot model mirroring `PaperTradingSimulator`. Models `fee_pct`/`slippage_pct` per fill (engine defaults to 0/frictionless; CLI defaults to realistic non-zero values). `BacktestResult` reports total return, win rate, max drawdown, total fees paid, vs. a `buy_and_hold_return_pct()` baseline. CLI script runs it against real Kraken history (public endpoint, no API keys needed); `--timeframe` validated against `KrakenClient.TIMEFRAMES`. Interpretation guide in `docs/trading-bot-design.md` → "Backtesting Guide" |
| Risk Management | `src/risk/manager.py` | `RiskManager`: stateless, mirrors `Strategy`/`Backtester` (no I/O, everything passed explicitly). Position sizing at `max_position_size_pct` of balance, stop-loss/take-profit pricing (`default_stop_loss_pct` + configurable risk:reward ratio — first real use of `Position.stop_loss`/`take_profit`, unused until now), drawdown circuit breaker (`max_drawdown_pct`), exposure limit (new `max_open_positions` setting). `evaluate_signal()` gates BUY signals through all checks; SELL (closing) is always approved, never blocked. **Not yet wired into the webhook path or anywhere else — that's the Bot Engine's job.** |

### ⬜ Not Yet Implemented

| Component | Location | Priority | Description |
|-----------|----------|----------|-------------|
| Bot Engine | `src/bot/engine.py` | Medium | Main trading loop and orchestration — wires strategies + `RiskManager` + `OrderExecutor` together; webhook path and strategy-generated signals both still need to reach it and the risk gate |
| Technical Indicators | `src/bot/indicators/` | Low | Custom indicators beyond pandas-ta |

## Key Dependencies

- **ccxt** - Unified exchange API
- **fastapi** + **uvicorn** - Webhook server
- **pandas** + **pandas-ta** - Data analysis & indicators
- **sqlalchemy** + **aiosqlite** - Async SQLite database
- **pydantic-settings** - Configuration management
- **loguru** - Structured logging
- **apscheduler** - Task scheduling

## Configuration Parameters

Defined in `src/config.py`:
- Kraken API credentials
- Trading mode (paper/live)
- Webhook server settings
- Risk management limits (position size, drawdown, stop-loss)
- Logging configuration

## Next Steps (Suggested Order)

1. ~~**Exchange Integration** - Implement Kraken client for market data and order execution~~ ✅
2. ~~**Database Models** - Create models to persist trades and positions~~ ✅
3. ~~**Webhook API** - Build FastAPI endpoints for TradingView alerts~~ ✅
4. ~~**Strategy Framework** - Create base class and sample strategy~~ ✅
5. ~~**Risk Management** - Implement position sizing and risk controls~~ ✅
6. **Bot Engine** - Tie everything together with main trading loop (wire strategies + `RiskManager` + `OrderExecutor` into the actual trading loop; webhook path and strategy signals both still need to reach it and the risk gate)

## Architecture Notes

- Hybrid approach: receives TradingView signals AND can generate signals autonomously
- Paper trading mode for safe testing
- Async-first design using Python asyncio
- SQLite for local persistence (can upgrade to PostgreSQL)

## Resume Instructions

To continue development, mention:
- "Let's continue building the trading bot"
- Reference this file for current status
- Choose a component from "Not Yet Implemented" to work on next

---

*This file is auto-generated to track Claude Code session progress.*
