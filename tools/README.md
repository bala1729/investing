# tools/

Analysis harnesses. These produced the tables in
[`docs/backtest-results.md`](../docs/backtest-results.md) and are kept so those numbers can be
re-derived rather than merely trusted.

They are **not part of the bot**. `ruff` applies (it runs over the whole repo), but they are
deliberately outside the `mypy --strict` and coverage gate, which target `src`, `tests` and
`scripts`. Treat them as instruments, not shipped code.

Paths come from the environment with repo-relative defaults, so nothing here hardcodes a
home directory:

| Variable | Default | Meaning |
|---|---|---|
| `KRAKEN_DATA_DIR` | `settings.kraken_data_dir` | Kraken tick-CSV archive |
| `CANDLE_CACHE` | `data/candles` | Cached 1-minute candles |
| `SWEEP_OUT` | `data/sweeps` | Where result JSON is written |
| `SWEEP_SYMBOLS` | `BTC/USD,ETH/USD,SOL/USD` | Symbols to sweep |

---

## `sweep.py` — replay many configurations

`scripts/backtest.py` reloads and resamples the 1-minute cache on every invocation, which is
wasteful across a hundred-config sweep. This loads each symbol once and replays everything
against the same frames.

```bash
uv run python tools/sweep.py my_sweep tools/examples/margin.json
SWEEP_SYMBOLS="SOL/USD" uv run python tools/sweep.py sol_only tools/examples/margin.json
```

Config is a JSON list. `arm` labels a variant in the output; `stops` enables stop-loss,
take-profit and the trailing ratchet; `no_mtf` and `mtf` change the confirmation ladder for a
run **without editing `MTF_CONFIRMATION_MAP`**, so a hypothesis can be tested while the shipped
map stays as it is.

**Always include a control arm** that reproduces an existing logged baseline, and verify it
matches before trusting the comparison. Several conclusions in this project only held up
because the control caught a changed assumption — see the `margin 0` control in the
2026-08-08 exit-margin work, which reproduced the logged baseline in 15/15 cells.

## `income.py` — is this a *regular income* strategy?

Total return says nothing about whether money arrives predictably. This reports trades per
week, holding-period distribution, and the weekly return profile — including the longest run
of consecutive non-positive weeks, which is the dry spell someone drawing an income actually
has to survive. Buy-and-hold's weekly profile is computed alongside for comparison.

```bash
SYMBOL="SOL/USD" START=2022-01-01 TFS="1h,4h" MARGINS="0,2,5" OUT=income_sol \
    uv run python tools/income.py
```

## `backfill_paper_balances.py` — repair a pre-2026-08-08 database

Paper balances only began persisting on 2026-08-08. An older database has trades and positions
but no balances, so a restarted bot resumes with starting cash and no base currency, orphaning
any open position. This replays the trade log to reconstruct them.

```bash
DATABASE_URL="sqlite+aiosqlite:///$HOME/kraken-bot-state/trading_bot_sol_4h_rsi_m2.db" \
    uv run python tools/backfill_paper_balances.py
```

---

## Two things worth remembering when using these

**Fee drag decides nearly everything.** A round trip costs ~0.62% (0.26% fee twice, 0.05%
slippage twice). Changes that increase turnover have lost almost every time; changes that
reduce it have won. Always look at closed-trade counts alongside returns.

**Full-history returns need a start-date check.** Four separate headline results in this
project were reversed by re-running from a later start date. The `2018+`, `2020+` and `2022+`
windows exist for exactly that, and a long-window number should not be quoted without one.
