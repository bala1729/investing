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

## Backtesting Guide

Before any strategy touches a real (or even paper) order, validate it with `scripts/backtest.py` —
a walk-forward replay of the strategy against historical Kraken candles (`src/backtest/engine.py`).
It uses only Kraken's public market-data endpoint, so it needs no API credentials and never touches
the order executor, database, or webhook path.

Past sweeps are logged in [`docs/backtest-results.md`](backtest-results.md) — check it before
re-running a config someone already tried, and add to it (not over it) when you run a new sweep.

### Running it

```bash
# Quick look, ~30 days of hourly candles (Kraken's public OHLC endpoint caps around 720 candles
# per request regardless of --limit, so shorter timeframes mean shorter history)
uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1h --limit 500

# Longer, more meaningful lookback — use a coarser timeframe to fit more history in that same cap
uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1d --limit 720 --fast 10 --slow 30

# Override the fee/slippage assumptions, position sizing, or starting balance
uv run python scripts/backtest.py --symbol ETH/USD --fee-pct 0.4 --slippage-pct 0.1 \
  --position-size-pct 50 --balance 5000

# Compare the bundled example strategies (sma is the default; ema reacts faster but noisier;
# confluence adds MACD/RSI/Bollinger-Band confirmation on Heikin Ashi candles)
uv run python scripts/backtest.py --strategy ema --symbol BTC/USD --timeframe 1d --limit 720
uv run python scripts/backtest.py --strategy confluence --symbol BTC/USD --timeframe 1d --limit 720
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
- **Capped history.** Kraken's public OHLC endpoint returns at most ~720 candles per request,
  regardless of `--limit`. There's currently no way to pull deeper history through this integration.
- **Single-window, in-sample only.** A good result on one historical window is not evidence the
  strategy generalizes. Test multiple, non-overlapping periods and more than one asset — if it only
  "works" on the one window you happened to run, that's overfitting, not edge.
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
| `4h` | `1d` | `1w` |
| `1d` | `1w` | `2w` |

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
