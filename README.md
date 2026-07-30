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

   127 tests — config validation, the Kraken client, order executor, database layer, and the
   webhook API (invalid secret rejected, market order path, limit order path, bad-quantity
   validation, and more). All currently pass, at ~99.8% coverage.

3. **Run it for real** (paper trading, hits live Kraken market data for prices):

   ```bash
   uv run uvicorn src.main:app --reload
   ```

   Then in another terminal:

   ```bash
   curl -X POST http://localhost:8000/webhook/tradingview \
     -H "Content-Type: application/json" \
     -d '{"secret":"changeme","symbol":"BTC/USD","action":"buy","quantity":"0.001"}'

   curl http://localhost:8000/health
   ```

   Note `secret` must match `WEBHOOK_SECRET` in `.env` (default `changeme`), and `symbol` must be
   ccxt-style `BTC/USD`, not TradingView's `BTCUSD`. This is paper trading by default
   (`TRADING_MODE=paper` in `.env.example`), so no real funds move — it fetches the real Kraken
   BTC/USD price and simulates the fill against a virtual $10k balance. A `trading_bot.db` SQLite
   file will appear in the project root with the order/trade records; it's gitignored.

4. **Interactive API docs:** with the server running, open http://localhost:8000/docs for
   FastAPI's Swagger UI to try the webhook without curl.

## Quality Checks

```bash
uv run pytest         # unit tests + coverage (min 88%, see pyproject.toml)
uv run ruff check .   # lint
uv run mypy src tests # static type checks
uv run pip-audit      # dependency vulnerability scan
```

These four checks also run in CI on every push/PR to `main` (see `.github/workflows/ci.yml`).
