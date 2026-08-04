# Kraken Trading Bot - Project Status

**Last Updated:** 2026-08-01 (session 3)
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
| Webhook API | `src/api/`, `src/main.py` | FastAPI app with `POST /webhook/tradingview` (secret-validated, risk-gated via `TradingEngine`) and `GET /health` |
| README | `README.md` | Setup/run/test instructions (was missing) |
| Quality Gate | `pyproject.toml`, `tests/` | `ruff` + `mypy --strict` clean; 88% min coverage enforced via `pytest --cov-fail-under=88` (currently ~99.8%); mandate incl. 1000-line file / 200-line function caps documented in `docs/trading-bot-design.md` |
| CI | `.github/workflows/ci.yml` | GitHub Actions: lint, typecheck, test+coverage, and `pip-audit` dependency vulnerability scan, all as separate jobs on push/PR to `main` |
| Strategy Framework | `src/bot/strategies/` | `Strategy` ABC + `Signal` value object + shared `detect_crossover()` helper (`base.py`), `ohlcv_to_dataframe()` helper, and five example strategies under `examples/`: `MovingAverageCrossoverStrategy` (SMA), `EMACrossoverStrategy` (EMA), and `HeikinAshiConfluenceStrategy` (EMA(5,10) crossover on Heikin Ashi candles, confirmed by MACD bullish + RSI not overbought + price below upper Bollinger Band; exit is a bare bearish EMA cross, deliberately unfiltered — never make an exit harder than an entry). `RSICrossoverStrategy` (RSI crossing the SMA drawn over it, matching TradingView's built-in RSI indicator with its optional moving average - threshold-free, so unlike a 30/70 overbought/oversold rule it does not fight a sustained trend; it confirms higher timeframes with its own RSI-vs-SMA reading rather than the shared `mtf_trend_confirms_buy()`, since an RSI strategy has no natural fast/slow price-EMA pair to borrow). All selectable via `scripts/backtest.py --strategy sma\|ema\|macd\|rsi\|confluence` and `scripts/run_bot.py`; the registry and period-flag validation are shared by both CLIs in `src/bot/strategies/registry.py`. Pure functions of candle data → signal; no I/O. Caught a real bug building the third strategy: `pandas_ta.bbands()`'s `std=` kwarg is silently swallowed by `**kwargs` and has zero effect at runtime — the real parameters are `lower_std`/`upper_std` — found via mypy strict flagging an odd type mismatch, then confirmed empirically that the "working" call produced identical output to no `std` arg at all. All three strategies also apply top-down multi-timeframe entry confirmation (`MTF_CONFIRMATION_MAP`, `mtf_trend_confirms_buy()` in `base.py`): the strategy's own crossover still triggers on the timeframe you run it on (the entry timeframe), gated by trend alignment on two *higher* timeframes — `5m`→`15m`+`1h`, `15m`→`1h`+`4h`, `1h`→`4h`+`1d`, `4h`→`1d`+`1w`, `1d`→`1w`+`2w`; other timeframes are unaffected. Entries only — exits stay unfiltered. An earlier version of this had the direction backwards (checking lower timeframes instead of higher ones); corrected after review, see `docs/backtest-results.md`. See `docs/trading-bot-design.md` → "Multi-Timeframe Entry Confirmation". |
| Backtesting Engine | `src/backtest/engine.py`, `scripts/backtest.py` | Walk-forward `Backtester`: replays a `Strategy` bar-by-bar over historical candles, no lookahead (signals fill on the *next* bar's open). Long-only spot model mirroring `PaperTradingSimulator`. Models `fee_pct`/`slippage_pct` per fill (engine defaults to 0/frictionless; CLI defaults to realistic non-zero values). `BacktestResult` reports total return, win rate, max drawdown, total fees paid, vs. a `buy_and_hold_return_pct()` baseline. CLI script runs it against real Kraken history; `--timeframe` validated against `KrakenClient.TIMEFRAMES`. Interpretation guide in `docs/trading-bot-design.md` → "Backtesting Guide". **Known scaling limit:** the backtester hands each bar the full candle prefix, so strategies recompute indicators over all history every bar — cost grows superlinearly (measured 1.5s at 8k candles, 27s at 64k, ~60s at 96k). Fine for windowed runs, noticeable on decade-long ones. |
| Historical Data | `src/backtest/data.py` | Builds candles from Kraken's downloadable tick archive instead of the REST endpoint, which caps at ~720 candles and is irreproducible (always relative to *now*). Streams the tick CSVs in chunks (BTC is 129M rows / 2.7GB), resamples to 1-minute candles, caches them gzipped under `data/candles/` (gitignored), and derives every coarser timeframe from that cache exactly — so each tick file is read at most once. Two Kraken quirks found and handled, both of which pandas' defaults get wrong: its **`2w` is a 15-day interval** (21600 min), not 14, and buckets are **floored on the epoch grid** (hence Thursday-anchored weeklies) rather than anchored to the data's start. Cross-validated against the REST endpoint over 1,113 shared `1d`/`1w`/`2w` candles: highs/lows match exactly, and the one discrepancy was a corrupt zero-volume candle on Kraken's side. Selected via `--data-source csv` (default) with `KRAKEN_DATA_DIR`; `--data-source rest` keeps the old path. |
| Risk Management | `src/risk/manager.py` | `RiskManager`: stateless, mirrors `Strategy`/`Backtester` (no I/O, everything passed explicitly). **Risk-based position sizing**: sized so a stopped-out trade loses exactly `risk_per_trade_pct` of account equity (industry-standard practice — decouples position size from stop distance, unlike sizing purely off balance %), with `max_position_size_pct` of balance kept as a secondary cap so a tight stop can't imply an oversized position. Stop-loss/take-profit pricing (`default_stop_loss_pct` + configurable risk:reward ratio — first real use of `Position.stop_loss`/`take_profit`), drawdown circuit breaker (`max_drawdown_pct`), exposure limit (`max_open_positions`). `evaluate_signal()` gates BUY signals through all checks; SELL (closing) is always approved, never blocked. |
| Bot Engine | `src/bot/engine.py`, `scripts/run_bot.py` | `TradingEngine` — the single choke point where any signal (webhook or autonomous strategy) becomes an order: risk-gates via `RiskManager`, executes via `OrderExecutor`, persists via `UnitOfWork`. `process_signal()` used directly by the webhook; `run_strategy_once()`/`run_forever()` poll a `Strategy` on an interval for autonomous trading. One open position per symbol (a BUY when already holding is skipped, not pyramided); peak-equity drawdown tracking is in-memory per symbol per process (resets on restart — documented limitation). Two real bugs found and fixed while running this live (not by review — by actually running it): (1) `Position.amount` is DB-rounded to 8dp and can read back slightly above what `PaperTradingSimulator` actually holds, so a SELL clamps to the executor's real balance rather than trusting the DB value; (2) `run_strategy_once()` was generating signals against the exchange's most recent candle, which is usually still forming — a live/backtest inconsistency equivalent to Pine Script "repainting" — fixed by always fetching one extra candle and dropping the newest before handing candles to the strategy; (3) `scripts/run_bot.py` never called `init_database()`, so any signal that reached the DB layer crashed with "no such table" — only surfaced once a real signal fired in production use. `scripts/run_bot.py` runs the autonomous loop against live Kraken data (paper by default). |

### ⬜ Not Yet Implemented

| Component | Location | Priority | Description |
|-----------|----------|----------|-------------|
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
6. ~~**Bot Engine** - Tie everything together with main trading loop~~ ✅
7. ~~**Backtesting exploration** - Sweep SMA vs EMA across symbols/timeframes/periods before paper trading~~ ✅ — logged in [`docs/backtest-results.md`](docs/backtest-results.md); no config showed a robust standalone edge, parameter sensitivity was severe (exact 4-4 split on return and drawdown across 8 comparisons). Leaning toward BTC/USD SMA(10,30) as the least-cherry-picked paper-trading candidate.
8. ~~**Paper trading** - Started BTC/USD EMA(10,30) autonomous paper trading via `scripts/run_bot.py`~~ ✅ — running continuously since 2026-08-01, monitored via an hourly cron check-in. No trades yet as of last check (crossover detected but no open position to act on it).
9. ~~**Third strategy + sweep** - Built `HeikinAshiConfluenceStrategy` (EMA(5,10) + MACD + RSI + Bollinger Bands on Heikin Ashi candles) and swept it across BTC/USD, ETH/USD, SOL/USD x 1h/4h/1d/1w~~ ✅ — logged in `docs/backtest-results.md`. Beat buy-and-hold in only 4 of 12 runs; on the ~2yr (1d) window it lost money on all three assets. More indicators/filters did not produce a more robust edge than the simpler single-indicator crossovers.
10. ~~**Multi-timeframe entry confirmation** - Added top-down MTF confirmation (higher timeframes confirm trend, entry timeframe stays where the trigger fires) to all three strategies for `15m`/`1h`/`4h`/`1d` entries, and swept `ema`/`confluence` across BTC/USD, ETH/USD, SOL/USD on all four~~ ✅ — first version had the direction backwards (caught during review, corrected); see `docs/backtest-results.md` for the corrected sweep. Beat buy-and-hold in 9 of 15 non-trivial runs; best single result was `ema` on BTC/USD `1d` (+40.99% vs +6.92% B&H, 8 closed trades) but every row remains well under the trade-count threshold to trust.
11. ~~**Fourth strategy** - `MACDCrossoverStrategy` (MACD line crossing its signal line), selectable as `--strategy macd`~~ ✅
12. ~~**Local historical data** - Backtests now build candles from Kraken's downloadable tick archive instead of the ~720-candle REST endpoint~~ ✅ — see the Historical Data row above. This removes the single biggest distortion in every earlier sweep in this file: short windows (a `1h` sweep covered ~30 days) and thin trade counts (1-2 closed trades on many rows). Full history is now available (BTC from 2013) and runs are reproducible.
13. **Next up (unprioritized):** Re-evaluate every earlier conclusion in `docs/backtest-results.md` against the full-history re-runs — the pre-2026-08-02 entries were measured on windows too short to support them; technical indicators beyond pandas-ta; production concerns (monitoring/alerting); optimize the backtester's superlinear per-bar cost if decade-long sweeps become routine; consider whether any tested config is actually worth paper-trading given none has shown a robust edge so far

## Architecture Notes

- Hybrid approach: receives TradingView signals AND can generate signals autonomously — both paths now converge on the same risk-gated `TradingEngine.process_signal()`, not just superficially "supported"
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
