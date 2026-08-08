# Cryptocurrency Trading Bot Design for Kraken Exchange

## Overview

This document outlines the design and architecture for a cryptocurrency trading bot that integrates with the Kraken exchange, leveraging TradingView for charting and signal generation.

---

## Design Approaches

### 1. Signal-Based Automation (TradingView → Bot)

Since you have a TradingView subscription, you can leverage its Pine Script alerts:

- Create strategies/indicators in TradingView
- Use TradingView webhooks to send alerts to your bot
- Bot receives signals and executes trades on Kraken

| Pros | Cons |
|------|------|
| Leverage TradingView's charting, backtesting, and indicator library | Dependent on TradingView's webhook reliability |
| Visual strategy development | Slight latency in signal delivery |
| Large community of shared strategies | Monthly subscription cost |

### 2. Fully Autonomous Bot

Bot handles everything: data collection, analysis, signal generation, execution

- Fetch market data directly from Kraken API
- Implement your own technical indicators and strategies
- Execute trades programmatically

| Pros | Cons |
|------|------|
| Full control over all components | More complex to build and maintain |
| Lower latency | Need to implement own backtesting |
| No external dependencies | Requires more development time |

### 3. Hybrid Approach (Recommended)

- Use TradingView for strategy development and backtesting
- Export successful strategies to your bot for autonomous execution
- Bot can also accept TradingView webhook signals as secondary input

This approach provides the best of both worlds: rapid strategy prototyping with TradingView and reliable autonomous execution.

---

## Technology Stack

### Recommended: Python

Python is recommended due to its extensive ecosystem for trading, excellent libraries, and rapid prototyping capabilities.

#### Core Dependencies

| Component | Library | Purpose |
|-----------|---------|---------|
| Exchange API | `ccxt` | Unified exchange API (supports Kraken and 100+ exchanges) |
| Data Analysis | `pandas`, `numpy` | Data manipulation and numerical computing |
| Technical Indicators | `ta-lib` or `pandas-ta` | Technical analysis indicators |
| Web Framework | `FastAPI` | Webhook receiver and REST API |
| Database | `SQLite` / `PostgreSQL` | Trade history and configuration |
| Scheduling | `APScheduler` | Task scheduling and cron jobs |
| Configuration | `pydantic-settings` | Environment and secrets management |
| Logging | `loguru` | Structured logging |

#### Alternative Stacks

**Node.js/TypeScript** (Good for real-time applications)
- Node.js 20+ with TypeScript
- ccxt for exchange connectivity
- Express/Fastify for webhook server
- technicalindicators for TA library
- PostgreSQL + Prisma for database

**Go** (Best for performance-critical applications)
- Go 1.21+
- Custom Kraken API client
- Gin/Fiber for HTTP server
- PostgreSQL for database

---

## Architecture

```
┌─────────────────┐     Webhooks      ┌──────────────────┐
│   TradingView   │ ─────────────────▶│   Webhook API    │
└─────────────────┘                   └────────┬─────────┘
                                               │
                                               ▼
┌─────────────────┐                   ┌──────────────────┐
│  Kraken Market  │◀─────────────────▶│   Trading Bot    │
│     Data API    │                   │     Engine       │
└─────────────────┘                   └────────┬─────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
           ┌───────────────┐          ┌───────────────┐          ┌───────────────┐
           │   Strategy    │          │     Risk      │          │    Order      │
           │    Engine     │          │   Manager     │          │   Executor    │
           └───────────────┘          └───────────────┘          └───────────────┘
                                               │
                                               ▼
                                      ┌───────────────┐
                                      │   Database    │
                                      │ (Trade Log)   │
                                      └───────────────┘
```

### Component Descriptions

#### Webhook API
- Receives TradingView alerts via HTTP POST
- Validates and authenticates incoming signals
- Queues signals for processing

#### Trading Bot Engine
- Central orchestrator for all trading operations
- Manages component lifecycle
- Handles configuration and state

#### Strategy Engine
- Implements trading strategies
- Processes market data and generates signals
- Supports multiple concurrent strategies

#### Risk Manager
- Enforces position sizing rules
- Manages stop-loss and take-profit levels
- Monitors account exposure and drawdown
- Prevents over-trading

#### Order Executor
- Interfaces with Kraken API via ccxt
- Handles order placement, modification, cancellation
- Manages order state and fills
- Implements retry logic for failed orders

#### Database
- Stores trade history and performance metrics
- Persists configuration and strategy parameters
- Enables post-trade analysis

---

## Project Structure

```
investing/
├── docs/
│   └── trading-bot-design.md
├── src/
│   ├── __init__.py
│   ├── main.py                 # Application entry point
│   ├── config.py               # Configuration management
│   ├── api/
│   │   ├── __init__.py
│   │   ├── webhooks.py         # TradingView webhook handlers
│   │   └── routes.py           # REST API routes
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── engine.py           # Main bot engine
│   │   ├── strategies/
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # Base strategy class
│   │   │   └── examples/       # Example strategies
│   │   └── indicators/
│   │       ├── __init__.py
│   │       └── custom.py       # Custom indicators
│   ├── exchange/
│   │   ├── __init__.py
│   │   ├── kraken.py           # Kraken-specific implementation
│   │   └── executor.py         # Order execution logic
│   ├── risk/
│   │   ├── __init__.py
│   │   └── manager.py          # Risk management
│   └── database/
│       ├── __init__.py
│       ├── models.py           # Database models
│       └── repository.py       # Data access layer
├── tests/
│   ├── __init__.py
│   ├── test_strategies.py
│   ├── test_executor.py
│   └── test_risk.py
├── scripts/
│   ├── backtest.py             # Backtesting script
│   └── paper_trade.py          # Paper trading script
├── .env.example                # Environment variables template
├── .gitignore
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Code Quality Standards

Mandatory for all code in this repository, enforced locally and gated in CI
(`.github/workflows/ci.yml`, running on every push/PR to `main`):

- **Linting**: `ruff check .` must pass with zero errors.
- **Type checking**: `mypy` (strict mode, configured in `pyproject.toml`) must pass with zero errors.
- **Test coverage**: Minimum **88% line coverage**, enforced automatically via `--cov-fail-under=88`
  in `pytest`'s config (`uv run pytest` fails the run if coverage drops below this).
- **Dependency vulnerabilities**: `pip-audit` must report no known vulnerabilities in the resolved
  dependency tree. A flagged CVE blocks the merge until the dependency is upgraded or the finding
  is otherwise resolved — it isn't waived silently.
- **File size**: No source file may exceed **1000 lines**. Split by responsibility (e.g. separate
  modules per exchange, per repository, per strategy) before a file grows past this.
- **Function size**: No single function or method may exceed **200 lines**. Extract helpers rather
  than growing one function — this also tends to make code easier to unit test in isolation.

These aren't aspirational — treat a lint failure, a type error, a coverage drop below 88%, a
flagged vulnerability, or a file/function blowing past the size limits as a blocker on the same
footing as a failing test.

---

## Key Features

### 1. Risk Management
- **Position Sizing**: Calculate position size based on account balance and risk percentage
- **Stop-Loss**: Automatic stop-loss placement on all trades
- **Max Drawdown**: Halt trading if drawdown exceeds threshold
- **Exposure Limits**: Maximum percentage of account in open positions

### 2. Paper Trading Mode
- Simulate trades without real money
- Use real market data for realistic testing
- Track hypothetical P&L and performance

### 3. Logging & Monitoring
- Structured logging of all decisions and trades
- Performance metrics and dashboards
- Alert notifications (email, Telegram, Discord)

### 4. Rate Limiting
- Respect Kraken API rate limits
- Implement exponential backoff
- Queue requests during high-frequency operations

### 5. Error Handling
- Graceful handling of network failures
- API error recovery and retry logic
- Partial fill management
- Circuit breaker pattern for repeated failures

### 6. Secrets Management
- Environment-based configuration
- Encrypted API key storage
- No secrets in version control

---

## Kraken API Integration

### Authentication
Kraken uses API key + secret for authentication. Keys should be created with minimal required permissions:

- **Query Funds**: Read account balance
- **Query Open Orders & Trades**: Read order status
- **Query Closed Orders & Trades**: Read trade history
- **Create & Modify Orders**: Place and cancel orders

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /0/public/Ticker` | Get current prices |
| `GET /0/public/OHLC` | Get candlestick data |
| `GET /0/private/Balance` | Get account balance |
| `POST /0/private/AddOrder` | Place new order |
| `POST /0/private/CancelOrder` | Cancel order |
| `GET /0/private/OpenOrders` | Get open orders |

### Rate Limits
- Public endpoints: 1 request/second
- Private endpoints: Tier-based (starts at 15 calls/minute)
- Implement request queuing and throttling

---

## TradingView Webhook Integration

### Webhook Payload Format

```json
{
  "secret": "your-webhook-secret",
  "symbol": "BTCUSD",
  "action": "buy",
  "price": 45000.00,
  "quantity": 0.01,
  "strategy": "momentum_breakout",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Security Considerations
- Use HTTPS only
- Validate webhook secret
- Rate limit incoming requests
- Validate payload structure

---

## Development Phases

### Phase 1: Foundation
- [x] Project setup and configuration
- [x] Kraken API integration (read-only)
- [x] Basic logging and error handling
- [x] Database schema and models

### Phase 2: Core Trading
- [x] Order execution engine
- [x] Paper trading mode
- [x] Basic risk management
- [x] TradingView webhook receiver

### Phase 3: Strategies
- [x] Strategy framework
- [x] Implement example strategies
- [x] Backtesting capabilities
- [ ] Performance metrics

### Phase 4: Production
- [ ] Monitoring and alerting
- [ ] Advanced risk management
- [ ] Performance optimization
- [ ] Documentation

---

## Stop-Loss Enforcement and the Trailing Ratchet

Positions have carried `stop_loss` and `take_profit` since the first version, but until
2026-08-05 **nothing could act on them** — the values were written on entry and only ever read
back for JSON serialisation. `KrakenClient.create_stop_loss_order()` existed and was called from a
unit test and nowhere else. A position's only exit was its strategy's own sell signal.

### Who enforces

`STOP_ENFORCEMENT` picks exactly one mechanism, never both:

| Mode | Who sells | Protects while bot is down | Works in paper |
|---|---|---|---|
| `off` (default) | nobody — only the strategy's exit signal | n/a | n/a |
| `poll` | the bot, comparing ticker to stop each cycle | no | yes |
| `native` | the exchange, via a resting stop order | yes | no |

**It ships `off`, and that is a measured decision rather than caution.** Across 8 stop widths
(2–10%) × 30 windows on `4h`, no stop configuration beat leaving stops off, and none reduced
average drawdown — see the 2026-08-05 entry in [backtest-results.md](backtest-results.md). These
strategies already exit on an indicator turn, so a price stop can only convert a held trade into an
earlier one, and each stop-out frees capital to re-enter and pay another round trip. A stop is
still *recorded* on every position for reference; `off` simply means nothing acts on it, which is
how the system behaved before enforcement existed.

Running both would sell the same position twice: the exchange fills its resting stop, and the bot —
still seeing the position in its own database — sends a second market sell, which either errors on
insufficient balance or, on margin, opens an unintended short. `Settings.effective_stop_enforcement`
is what the engine reads, and it forces `poll` whenever `TRADING_MODE=paper`, because
`PaperTradingSimulator` has no resting orders to fill.

`TradingEngine.enforce_stops()` runs **before** signal generation each cycle. Risk management
protecting capital should not queue behind a strategy that may produce no signal, and a strategy
should never be asked about a position that has already been stopped out.

### The ratchet

`RiskManager.calculate_trailing_stop_price()` is a pure function of `(entry, current_stop, price)`.
Once price reaches `TRAILING_STOP_TRIGGER_PCT` above entry, the stop moves to
`TRAILING_STOP_LOCK_PCT` above entry and holds. It is a **one-step ratchet, not a continuously
trailing stop** — the stop moves once.

Both mechanisms consume that same number: `poll` compares the live price to it, `native` submits it
as a resting order. That is what makes the ratchet identical in paper and live, and why switching
enforcement cannot change *where* the stop sits, only who acts on it.

Two properties worth knowing:

- **The result is monotonic.** A stop that can move down is not a stop, and on a cancel/replace
  mechanism a transient bad price could otherwise widen a resting order.
- **`stop_loss` is the ratchet's memory.** Once raised it stays raised, so a restart cannot forget
  that the trigger was reached and drop the stop back to its opening level. No separate
  high-water-mark column is needed — which also means no schema migration, and existing databases
  keep working.

`LOCK >= TRIGGER` is rejected at config load: the raised stop would sit at or above the price that
armed it and fill immediately, turning the feature into "exit at the trigger", which is a
take-profit.

### Native-mode hazards

- **Fills happen while the bot is away.** `_reconcile_external_close()` compares the exchange base
  balance against the recorded position; a materially smaller balance means the stop filled, and the
  position is closed locally at the actual fill price from `fetch_closed_orders()` (falling back to
  the stop price). Detection is by balance rather than order id so it survives restarts and also
  catches manual closes. A 1% tolerance keeps dust and rounding from looking like a fill.
- **Moving a resting stop is cancel-then-create.** Kraken has no in-place amend for this order type,
  so the replace briefly leaves the position unprotected — which is why the cancel is issued only
  when the ratchet actually moved the stop, not on every cycle. A cancel that fails because the
  order just filled is not an error; it is the race resolving in the exchange's favour, and the new
  order is still placed rather than skipped.

### In backtests

`Backtester` models stops, targets and the ratchet so the feature is measurable against the results
already logged. All four parameters default to 0, so every pre-existing result is unchanged.

- A bar whose `low` reaches the stop exits **at the stop price**; a bar whose `high` reaches the
  target exits at the target.
- **When one bar spans both, the stop wins.** OHLC cannot say which came first, and assuming the
  loss is the honest choice — the alternative flatters every result on a volatile bar.
- **The ratchet arms at the end of a bar, never within it.** Raising the stop on a bar's high and
  then testing it against that same bar's low would manufacture an exit the data cannot support.

```bash
uv run python scripts/backtest.py --strategy rsi --symbol SOL/USD --timeframe 4h \
  --stop-loss-pct 2 --trailing-trigger-pct 2 --trailing-lock-pct 1
```

## Operational Safety

Added 2026-08-08 while assessing readiness for live trading. Each item closes a specific way
the bot could have lost money quietly.

### Paper trading now charges fees

`PaperTradingSimulator` charged **nothing** until this change, while the backtester charged
0.26% + 0.05%. Every paper result was therefore optimistic relative to both live trading and
the logged backtests — and fee drag is what decided every result in
[backtest-results.md](backtest-results.md). `PAPER_FEE_PCT` defaults to Kraken's taker rate;
the fee is charged in quote currency on both sides, included in the affordability check, and
persisted onto the trade record.

A concrete illustration from the live paper bot: two round trips on 2026-08-05 inside a ~1%
price range showed **+$0.27 gross**. At 0.26% those four fills cost about $5.20, so the true
result was roughly **−$4.93**.

### Peak equity survives restarts

The drawdown limit measures decline from the account's best-ever equity. That high-water mark
used to live in a dict on `TradingEngine`, so **every restart reset it** to whatever equity
happened to be at that moment — silently disarming `MAX_DRAWDOWN_PCT` exactly when it mattered,
since a bot is most likely to be restarted right after something went wrong. It now lives in
the `peak_equity` table and only ever moves up. A new table rather than a new column, so
`create_all()` adds it to existing databases without a migration.

### Kill switch

`touch KILL_SWITCH` halts all **new entries** from the next cycle. Exits are never blocked — a
kill switch that trapped you in a position would be worse than none — so an open position stays
managed by its strategy. Delete the file to resume. No restart either way.

### SMS alerts and the watchdog

`SmsNotifier` sends via Twilio's REST API over plain HTTP (no SDK dependency, since every
dependency must clear pip-audit in CI). It is **off unless fully configured**, and every failure
path is swallowed and logged: an alerting outage must never be able to stop trading. Alerts fire
on entry and exit fills, tagged `[PAPER]` or `[LIVE]` because mistaking one for the other is the
expensive error.

`scripts/watchdog.py` checks liveness from cron and distinguishes the two cases that matter:

```bash
uv run python scripts/watchdog.py --pid-file bot.pid --symbol SOL/USD \
    --log-file bot.log --max-log-age-minutes 45
```

A dead bot with no position is an inconvenience. A dead bot **holding** a position is dangerous —
nothing is watching, no exit can fire, and with `STOP_ENFORCEMENT=off` there is no resting order
either. It also treats a stale log as failure, because a hung bot looks identical to a healthy one
in the process table.

**All credentials and the destination phone number belong in `.env` only.** This repository is
public; `.env.example` carries empty placeholders and nothing else.

## Backtesting Guide

Before any strategy touches a real (or even paper) order, validate it with `scripts/backtest.py` —
a walk-forward replay of the strategy against historical Kraken candles (`src/backtest/engine.py`).
It never touches the order executor, database, or webhook path, and needs no API credentials.

Past sweeps are logged in [`docs/backtest-results.md`](backtest-results.md) — check it before
re-running a config someone already tried, and add to it (not over it) when you run a new sweep.

### Data sources

| | `--data-source csv` (default) | `--data-source rest` |
|---|---|---|
| Source | Kraken's downloadable tick CSVs, resampled locally (`src/backtest/data.py`) | Kraken's public OHLC endpoint |
| History | Full — BTC from 2013, ETH from 2015, SOL from 2021 | **Capped at ~720 candles** per request |
| Reproducible | Yes — a given `--start`/`--end` always yields the same candles | **No** — always relative to *now* |
| Setup | Requires the download + `KRAKEN_DATA_DIR` | None |

The CSV path exists because the ~720-candle cap silently distorted every early sweep in this
project: `1h` runs covered only ~30 days, and one multi-timeframe sweep produced zero trades on 6 of
24 rows purely because its short window happened to be a sustained downtrend.

**Setup:** download Kraken's historical data, then point `KRAKEN_DATA_DIR` at the directory of
`*.csv` files (in `.env`, or pass `--data-dir`). The files are tick-level trades
(`timestamp,price,volume`, no header), not candles.

**Caching:** the first run per symbol resamples ticks into 1-minute candles (~5s for SOL, ~60s for
BTC's 129M ticks) and caches them under `data/candles/` (gitignored). Every coarser timeframe
derives from that cache exactly, so each tick file is read at most once.

**Two things worth knowing about Kraken's intervals** — both verified against its REST candles, and
both silently wrong if you reach for pandas' defaults:

- **`2w` is a 15-day interval** (21600 minutes), not 14 days. pandas' `2W` offset is 14 days.
- **Buckets are floored on the epoch grid**, not anchored to the first observation or to midnight —
  which is why Kraken's weekly candles land on a Thursday (epoch 0 was a Thursday) and its `2w`
  candles on a Tuesday. All resampling here uses `origin="epoch"`.

Cross-validated against the REST endpoint over 1,113 shared `1d`/`1w`/`2w` candles: highs and lows
match **exactly** (0.000000 difference). The only discrepancy found was a single Kraken `2w` candle
reported with `volume=0` and a flat OHLC, where the underlying ticks show real trading — i.e. the
local data was more accurate than the API's.

**Data cutoff:** the downloaded archive ends 2025-12-31. Results from it are not directly comparable
to older REST-sourced entries in the results log, which covered windows through mid-2026.

### Running it

```bash
# Full local history (default source), all of it
uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1h

# A specific window — this is how you test out-of-sample across several periods
uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1h --start 2024-01-01 --end 2024-12-31

# Compare the bundled example strategies (sma is the default; ema reacts faster but noisier;
# macd triggers on the MACD signal-line cross; rsi trades RSI against the SMA drawn over it;
# confluence adds MACD/RSI/Bollinger-Band confirmation on Heikin Ashi candles)
uv run python scripts/backtest.py --strategy ema --symbol BTC/USD --timeframe 1d
uv run python scripts/backtest.py --strategy macd --symbol BTC/USD --timeframe 1d
uv run python scripts/backtest.py --strategy rsi --symbol BTC/USD --timeframe 1h
uv run python scripts/backtest.py --strategy confluence --symbol BTC/USD --timeframe 1d

# Override the fee/slippage assumptions, position sizing, or starting balance
uv run python scripts/backtest.py --symbol ETH/USD --fee-pct 0.4 --slippage-pct 0.1 \
  --position-size-pct 50 --balance 5000

# No local data downloaded? Fall back to the API (capped at ~720 candles, not reproducible)
uv run python scripts/backtest.py --data-source rest --symbol BTC/USD --timeframe 1h --limit 720
```

Run `uv run python scripts/backtest.py --help` for the full flag list.

### Reading the output

| Field | What it means | What to watch for |
|---|---|---|
| **Total return vs Buy & hold** | The single most important comparison. | If the strategy doesn't clear buy-and-hold by a comfortable margin, it isn't adding value over just holding the asset for that period. |
| **Win rate** | % of closed trades that were profitable. | Trend-following strategies (like the bundled SMA/EMA crossovers) are often profitable with a **low** win rate — many small losing whipsaws, a few large winning trends. Don't reject a strategy on win rate alone; read it together with total return. |
| **Max drawdown** | Worst peak-to-trough decline in equity during the run. | A risk/pain proxy, not just a return number — would you actually hold through that decline with real money? Weigh it against total return, not in isolation. |
| **Trades / closed trades** | How many round trips the strategy made. | Fewer than ~20–30 closed trades means the win rate and return numbers are easily noise, not signal. Prefer a longer lookback or a finer timeframe before trusting a result built on a handful of trades. |
| **Fees paid** | Total simulated trading fees across all fills. | Compare it against total return. On a real run, fees turned a 16.5% headline return into 6.4% — barely above buy-and-hold. A strategy that only "wins" before fees isn't a strategy, it's an illusion. |

### Known limitations

- **Idealized-but-not-perfect fills.** Signals fill at the *next* bar's open (no lookahead), which
  is realistic in direction but still an approximation — `--slippage-pct` narrows that gap, but pick
  a value that reflects the pair's actual liquidity/spread, not just the CLI default.
- **Capped history on `--data-source rest`.** The public OHLC endpoint returns at most ~720 candles
  per request regardless of `--limit`. Use the default CSV source for anything longer.
- **In-sample unless you make it otherwise.** A good result on one historical window is not evidence
  the strategy generalizes. With full local history there's no excuse not to check: run several
  non-overlapping `--start`/`--end` windows and more than one asset. If it only "works" on the one
  window you happened to run, that's overfitting, not edge.
- **No survivorship or delisting handling.** The archive only contains pairs Kraken still lists.
- **No minimum order size / lot constraints.** Kraken enforces per-pair minimum trade sizes
  (`KrakenClient.get_minimum_order_amount`); the backtester doesn't check against them.
- **Long-only, single position, spot only.** No shorting, no leverage, no multiple concurrent
  positions across pairs.

### Before connecting a strategy to real execution

1. Backtest across more than one timeframe and more than one historical window.
2. Confirm it beats buy-and-hold by a comfortable margin *after* realistic fees — not marginally,
   and not only before fees.
3. Check max drawdown against what you're actually willing to sit through with real money.
4. Even after a good backtest, start in paper trading (`TRADING_MODE=paper`) — a backtest validates
   historical mechanics, not future performance or live execution reliability.

---

## Multi-Timeframe Entry Confirmation

All three example strategies apply a standard top-down multi-timeframe filter on top of their own
crossover trigger: the timeframe a strategy runs on is the **entry** timeframe (it still generates
the actual trigger, unchanged), and two *higher* timeframes must independently show trend alignment
(`fast MA > slow MA`, using the strategy's own periods) before an entry is taken — trend on the
highest, setup on the middle, precise timing on the one you actually trade:

| Entry (`--timeframe`) | Setup | Trend |
|---|---|---|
| `5m` | `15m` | `1h` |
| `15m` | `1h` | `4h` |
| `1h` | `4h` | `1d` |
| `4h` | `1d` | *(none)* |
| `1d` | `1w` | `2w` |

**Why `4h` confirms against one timeframe instead of two.** A weekly EMA pair turns over very
slowly, so it can stay bearish for weeks after the daily has already turned — vetoing every `4h`
entry through the opening leg of a move, on a timeframe whose appeal is engaging early enough to
matter. Dropping the `1w` trend screen keeps the top-down discipline (the entry still has to agree
with the daily) while letting a position participate sooner. The other entries keep both screens.

Because tuple lengths now vary, consumers iterate `MTF_CONFIRMATION_MAP[tf]` rather than unpacking
it positionally.

This mapping lives in `MTF_CONFIRMATION_MAP` (`src/bot/strategies/base.py`), keyed by the entry
timeframe. Every other timeframe (`1m`, `30m`, `1w`, `2w`) has no mapping, so it behaves exactly
as before — single timeframe, no filtering.

Confirmation applies to **entries only** — exits (SELL) are never filtered, consistent with the
existing principle that an exit should never be harder to trigger than an entry (risk management
shouldn't be fighting a confirmation filter to get out of a position). Confirmation is *trend
alignment*, not a fresh crossover on each higher timeframe: requiring a simultaneous fresh cross on
all three timeframes would almost never align, since the entry timeframe crosses far more often
than the higher ones above it.

**On the Kraken history cap:** unlike an earlier (incorrect) version of this feature that put the
confirmation timeframes *below* the entry timeframe, this direction has no data-coverage problem.
Kraken's ~720-candle cap (see above) still limits how far back the *entry* timeframe's own history
reaches — same as it always did for a single-timeframe backtest — but the higher confirmation
timeframes cover a longer real-world span per candle, so their ~720-candle windows always reach
back at least as far as the entry timeframe's does, usually much further. There's nothing to flag
here beyond the cap that already applied before this feature existed.

---

## Security Best Practices

1. **API Keys**: Use environment variables, never commit to git
2. **Withdrawal Disabled**: Create API keys without withdrawal permission
3. **IP Whitelisting**: Restrict API access to known IPs
4. **2FA**: Enable on Kraken account
5. **Audit Logging**: Log all trading decisions for review
6. **Testing**: Extensive paper trading before live deployment

---

## Questions to Address

Before implementation, consider:

1. **Trading Strategies**: What strategies will be implemented? (momentum, mean reversion, arbitrage)
2. **Timeframes**: What trading frequency? (scalping, day trading, swing trading)
3. **Capital Allocation**: How much capital to allocate per trade?
4. **Risk Tolerance**: Maximum acceptable drawdown?
5. **Deployment**: Local machine, cloud server, or hybrid?

---

## Next Steps

1. Set up Python project with virtual environment
2. Install core dependencies
3. Create Kraken API keys (paper trading first)
4. Implement basic market data fetching
5. Build webhook receiver for TradingView
6. Create first simple strategy
7. Test thoroughly in paper trading mode
