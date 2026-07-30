# Kraken Trading Bot

[![CI](https://github.com/bala1729/investing/actions/workflows/ci.yml/badge.svg)](https://github.com/bala1729/investing/actions/workflows/ci.yml)

Cryptocurrency trading bot for the Kraken exchange with TradingView webhook integration.
Supports paper and live trading modes.

See [docs/trading-bot-design.md](docs/trading-bot-design.md) for architecture and design notes,
and [CLAUDE_PROJECT_STATUS.md](CLAUDE_PROJECT_STATUS.md) for current implementation status.

## Setup

```bash
uv sync --extra dev
cp .env.example .env  # fill in Kraken API credentials
```

## Run

```bash
uv run uvicorn src.main:app --reload
```

## Test

```bash
uv run pytest         # unit tests + coverage (min 88%, see pyproject.toml)
uv run ruff check .   # lint
uv run mypy src tests # static type checks
uv run pip-audit      # dependency vulnerability scan
```

These four checks also run in CI on every push/PR to `main` (see `.github/workflows/ci.yml`).
