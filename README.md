# Kraken Trading Bot

[![CI](https://github.com/bala1729/investing/actions/workflows/ci.yml/badge.svg)](https://github.com/bala1729/investing/actions/workflows/ci.yml)

Cryptocurrency trading bot for the Kraken exchange with TradingView webhook integration.
Supports paper and live trading modes.

See [docs/trading-bot-design.md](docs/trading-bot-design.md) for architecture and design notes,
and [CLAUDE_PROJECT_STATUS.md](CLAUDE_PROJECT_STATUS.md) for current implementation status.

## Quickstart

1. **Setup:**

   ```bash
   uv sync --extra dev
   cp .env.example .env  # defaults work fine for paper trading
   ```

2. **Automated tests:**

   ```bash
   uv run pytest -v
   ```

   228 tests — config validation, the Kraken client, order executor, database layer, the webhook
   API, the strategy framework, the backtesting engine, risk management, and the trading engine.
   All currently pass, at ~99.7% coverage.

3. **Backtest a strategy before it ever touches an order** — walk-forward simulation against real
   historical Kraken candles (no live/paper orders involved, no API credentials needed):

   ```bash
   uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1d --limit 720
   ```

   Prints starting/ending balance, total return, trade count, win rate, max drawdown, fees paid,
   and a buy-and-hold baseline for comparison. Two example crossover strategies are included —
   `--strategy sma` (default, simple moving average) or `--strategy ema` (exponential — reacts
   faster, noisier) — so you can compare them directly on the same data. Tune it with `--fast`,
   `--slow`, `--balance`, `--position-size-pct`, `--fee-pct`, `--slippage-pct`, or point it at a
   different `--symbol`/`--timeframe`. Signals fill at the *next* candle's open (never the same
   bar they were generated on), so results aren't inflated by lookahead bias, and fees/slippage are
   modeled by default so returns aren't inflated by ignoring trading costs either.

   **Read [docs/trading-bot-design.md → "Backtesting Guide"](docs/trading-bot-design.md#backtesting-guide)
   before trusting any result** — it covers how to interpret each metric (a low win rate doesn't
   mean a bad strategy; a good result on one window doesn't mean it generalizes) and the engine's
   current limitations (capped history, no lookahead but still idealized fills, in-sample only).

4. **Run the bot autonomously** (paper trading by default, hits live Kraken market data):

   ```bash
   uv run python scripts/run_bot.py --symbol BTC/USD --timeframe 1h --strategy sma
   ```

   Polls for candles on an interval (`--poll-interval`, default 60s), asks the strategy for a
   signal, and routes any signal through the same risk-gated `TradingEngine` the webhook uses —
   sized by `RiskManager`, executed by `OrderExecutor`, persisted to the database. Stop with
   Ctrl+C. Trading mode and risk limits come from `.env`, not CLI flags — double-check
   `TRADING_MODE` before ever pointing this at a live account.

5. **Or trigger trades via the TradingView webhook:**

   ```bash
   uv run uvicorn src.main:app --reload
   ```

   Then in another terminal:

   ```bash
   curl -X POST http://localhost:8000/webhook/tradingview \
     -H "Content-Type: application/json" \
     -d '{"secret":"changeme","symbol":"BTC/USD","action":"buy"}'

   curl http://localhost:8000/health
   ```

   Note `secret` must match `WEBHOOK_SECRET` in `.env` (default `changeme`), and `symbol` must be
   ccxt-style `BTC/USD`, not TradingView's `BTCUSD`. `quantity` is optional — omit it to let
   `RiskManager` size the position automatically, or pass an explicit amount to use it as-is; a
   `price` field places a limit order instead of a market order. The response includes
   `"approved": false` with a `reason` if the risk manager rejects the trade (drawdown breached,
   exposure limit reached, already holding a position in that symbol, or nothing to sell) — that's
   not an HTTP error, just the engine's decision. This is paper trading by default
   (`TRADING_MODE=paper` in `.env.example`), so no real funds move. A `trading_bot.db` SQLite file
   will appear in the project root with the order/trade/position records; it's gitignored.

6. **Interactive API docs:** with the server running, open http://localhost:8000/docs for
   FastAPI's Swagger UI to try the webhook without curl.

## Quality Checks

```bash
uv run pytest                 # unit tests + coverage (min 88%, see pyproject.toml)
uv run ruff check .           # lint
uv run mypy src tests scripts # static type checks
uv run pip-audit              # dependency vulnerability scan
```

These four checks also run in CI on every push/PR to `main` (see `.github/workflows/ci.yml`).
