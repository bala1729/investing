---
name: kraken-trading-bot
description: Workflow for the Kraken trading bot in this repo - backtesting a strategy or symbol, verifying the live order path via a smoke test, launching/restarting/stopping paper or live bots, and the go-live safety checklist. Use whenever asked to backtest a strategy or symbol, evaluate whether something is ready to trade real money, start/restart/stop a bot, check on running bots, or touch scripts/run_bot.py, scripts/backtest.py, tools/sweep.py, scripts/live_order_smoketest.py, scripts/watchdog.py, or scripts/rsi_scanner.py.
---

# Kraken trading bot workflow

Four things this project does repeatedly: backtest a strategy/symbol, verify the live order path
still works, run bots on paper money, run bots on real money. This skill is the distilled
procedure for each, plus the safety rules that came from real mistakes caught along the way -
read those before touching real money, not after.

**State that changes over time (which bots are running, current balances, positions) lives in
`~/kraken-bot-state/RESTART.md`, not here.** This skill is the procedure; that file is the current
snapshot. Always check it before assuming what's running, and always update it after anything
that changes the bot roster.

## 1. Backtesting

Two tools, same underlying `Backtester` (`src/backtest/engine.py`):

- **`scripts/backtest.py`** - one config, full CLI flag surface (strategy params, stop-loss/
  take-profit/trailing, fee/slippage, date range). Use for a single targeted run.
- **`tools/sweep.py <output-name> <config.json>`** - many configs replayed against candles loaded
  once per symbol. Use for anything comparing multiple arms (strategies, symbols, windows,
  take-profit widths). Config format and `SWEEP_SYMBOLS`/`CANDLE_CACHE`/`SWEEP_OUT` env vars are
  documented in `tools/README.md`; `tools/examples/*.json` has real configs from past sweeps to
  copy rather than write from scratch.

**Non-negotiable rules, all learned from real mistakes in this project's history:**

1. **Always include a control arm reproducing an existing logged number, and verify it matches
   before trusting anything else in the same run.** This has caught real bugs (a harness
   discrepancy) and real intentional changes (a strategy-logic change that made an old baseline
   stop reproducing) - either way, an unexplained mismatch means stop and investigate, not "the
   new numbers are probably fine."
2. **Check start-date sensitivity before trusting a full-history headline.** Sweep the same config
   from different start dates (`2018+`/`2020+`/`2022+` in the existing `WINDOWS` dict, or whatever
   distinct windows the symbol's history supports). This has reversed the conclusion of a
   full-history number multiple times in this project - a strategy that "beats buy-and-hold by
   1000x" over all history can still lose to it from a more recent start. If a symbol's history is
   too short for these cuts to differ (data starts after 2022), the check is vacuous - say so
   rather than presenting three identical numbers as three data points.
3. **Check per-year win rate, not just the multi-year multiple.** All-in/all-out compounding makes
   full-history figures explode even when a strategy loses in most individual years - the edge
   comes from avoiding a few bad years, not from winning consistently. A symbol that "wins" on
   full-history but loses 3 of 4 individual years is a much weaker case than one that wins 3 of 4.
4. **A config validated on one symbol does not transfer to another automatically.** A take-profit
   width that helped BTC/ETH/SOL was a mixed result on ADA specifically. Re-validate per symbol
   before funding it, even if the strategy code is identical.
5. **Check data availability before backtesting a new symbol.** Kraken's tick archive uses its own
   ticker codes for some assets (`BTC`->`XBT`, `DOGE`->`XDG` - see `_KRAKEN_ASSET_ALIASES` in
   `src/backtest/data.py`); confirm the file exists and how much history it covers before trusting
   any result, especially the start-date check above.
6. **Log every sweep to `docs/backtest-results.md`, including negative results.** A strategy that
   fails badly (e.g. a config that wipes the account, a symbol that loses to buy-and-hold every
   year) is exactly as valuable to have on record as one that works - it's what stops the same
   idea from being re-tried, or re-approved for real money, without evidence next time.
7. **Verify fee/slippage assumptions match the actual account.** Sweeps default to Kraken's typical
   taker rate (0.26%) - check the real account's fee tier before trusting absolute return numbers,
   though relative comparisons between arms are unaffected.

## 2. Paper trading

Launched via `scripts/run_bot.py --symbol X/USD --timeframe 4h --strategy rsi --exit-margin N
--poll-interval 900`, backgrounded with `caffeinate` so it survives the display sleeping:

```bash
cd ~/workspace/github/investing
DATABASE_URL="sqlite+aiosqlite:///$STATE/trading_bot_<label>.db" \
  nohup caffeinate -is uv run python scripts/run_bot.py \
    --symbol X/USD --timeframe 4h --strategy rsi --exit-margin N --poll-interval 900 \
    >> $STATE/paper_<label>.log 2>&1 &
echo $! > $STATE/paper_<label>.pid
```

Each bot is a separate process with its own `DATABASE_URL` - never share a database between bots.
`TRADING_MODE` defaults to `paper` (the shared `.env`'s setting), so no override is needed here.
State (`$STATE` = `~/kraken-bot-state/`, never the scratchpad - it's under `/private/tmp`, which
macOS purges) survives restarts via `OrderExecutor.restore_paper_state()`. **After any restart,
verify the resume actually happened** - `grep "Resumed paper balances" <log>` - rather than
assuming it. A missing line means the bot came back with fresh starting cash and an orphaned
position it can no longer sell.

## 3. Smoke testing the live order path

`scripts/live_order_smoketest.py` places one minimum-size real buy, verifies the fill against the
exchange's own record (not just the response), then sells it back - the only way to validate the
live order path against Kraken's actual API rather than a mock. It:

- Refuses to run unless `TRADING_MODE=live` is already set in the process env (never falls back to
  paper silently).
- Requires both `--yes-i-know-this-places-a-real-order` and an interactive typed `yes`.
- Sells back exactly what was *received* (not the requested amount), to survive a partial fill.
- Never auto-retries a leg that might have already gone through - retrying an order Kraken already
  accepted is exactly how a duplicate real order gets placed.

**Run it before ever running a strategy live for the first time, and again after any change to
`src/exchange/executor.py` or `src/exchange/kraken.py`.** It does not need to be re-run per new
symbol once the mechanism itself is validated - the order-execution code is symbol-agnostic. What
*does* need checking per new symbol is the minimum order size (see the go-live checklist below).

**This is a real-money action.** Preview it first with a non-`yes` answer (shows exact sizing,
balance, and cost with nothing placed), show the user the exact numbers, and only pipe a real `yes`
after the user has explicitly said to proceed in the conversation - not automatically as part of a
larger task. If the sell leg ever fails after a confirmed buy, use `--sell-only --amount X` to
close out the position rather than re-running the full script.

**Bugs found this way, not by review** (now fixed, but worth knowing the failure shape if something
similar shows up again): Kraken's create-order response carries no status/fill data at all, so it
must never be trusted directly - the real fill has to come from a follow-up `fetch_order`/
`fetch_my_trades` call. That follow-up can itself transiently raise (`OrderNotFound`) for an order
that already filled - retry it a few times before giving up, the same way a status still reading
"open" gets retried. ccxt's status vocabulary (`open`/`closed`/`canceled`/`expired`) doesn't match
this codebase's `OrderStatus` enum and needs explicit mapping, not a direct cast.

## 4. Going live: the checklist

Real money. Confirm every item before launching, and get explicit user sign-off before any step
that risks real funds (the smoke test, the actual launch) - don't just proceed through the list.

1. **Backtested** - control arm + start-date sensitivity + per-year check, per the rules in
   section 1. "Currently bullish" or "looks good right now" is not evidence; a logged backtest is.
2. **Live order path verified** - either already validated (check `RESTART.md`/memory for whether
   a smoke test has run since the last executor change) or run one now (section 3).
3. **Minimum order size checked** against what this account's actual position sizing would produce
   (`RiskManager.calculate_position_size` - the smaller of the 1%-risk-based size and the 5%-
   capital-cap size normally binds for a small account; compute both). Read-only, no funds at risk:
   `KrakenClient.get_minimum_order_amount(symbol)` plus the market's `limits.cost.min`.
4. **Account currency confirmed directly via `fetch_balance()`'s raw `free` dict, not a dashboard
   valuation.** A Kraken account can hold a different fiat than the pair being traded (e.g. CAD
   while trying to trade a `/USD` pair) - the dashboard shows a converted-to-USD *value*, which
   looks like a USD balance but isn't one. This has actually happened; check the raw balance.
5. **Kill switch decided** - a dedicated `KILL_SWITCH_LIVE` (recommended, isolates live from paper
   and, if there are several live bots, lets one shared file halt all of them at once) vs. sharing
   the paper bots' `KILL_SWITCH`.
6. **Monitoring in place before calling it unattended** - SMS alerting configured (`SMS_ALERTS_ENABLED`
   + Twilio **API Key** SID/secret in `.env`, not the account's own auth token - a leaked API key
   should be revocable without touching the whole Twilio account) and a `scripts/watchdog.py` cron
   entry per bot (mirrors the existing entries - checks pid/log liveness and alerts louder if the
   bot is down *while holding a position*, which is the case that actually matters).
7. **`TRADING_MODE=live` set only as a per-process env var on the launch command itself, never in
   the shared `.env`.** The shared file stays on `paper` so no other bot can go live by accident on
   its next restart.
8. **If other live bots already exist on the same account, consider shared-balance concurrency.**
   Every bot is a separate process with its own database, and each sizes its position from
   whatever balance it observes at its own poll moment - `max_open_positions` does not protect
   across bots, since each only ever sees its own database. Multiple bots signaling entries in the
   same window can each independently size off a near-stale balance and collectively deploy more
   than any single bot's sizing assumed. This has happened for real (~20% of an account deployed
   within seconds across 4 simultaneous launches). No code-level fix exists yet; it's an accepted
   risk at small balances, worth revisiting before scaling capital into an account running several
   live bots at once.
9. **Document the launch** in `~/kraken-bot-state/RESTART.md` (exact command, starting position/
   balance) and in memory - the next session needs to know what's running without re-deriving it.

## Finding new candidates: the RSI scanner

`scripts/rsi_scanner.py` scans Kraken's liquid USD pairs (volume-filtered - see its own docstring
for why scanning all 600+ listed pairs isn't practical) for symbols currently satisfying the same
entry condition the bots trade, by calling the strategy's own `generate_signal()` directly rather
than reimplementing the logic - so a flagged symbol is guaranteed to match what a bot would
actually decide. Runs hourly via cron, SMS-alerts only on symbols newly bullish since the last scan
(state-file dedup, so a symbol that stays bullish for days doesn't re-alert every cycle).

**This is informational only - it never places a trade.** A symbol showing up here still needs the
full backtest + go-live checklist above before any bot gets pointed at it. Treat its output as a
list of things worth checking, not a list of things worth funding.

## Where things live

- `src/backtest/engine.py`, `src/bot/strategies/` - the tested strategy logic itself.
- `scripts/run_bot.py`, `scripts/watchdog.py`, `scripts/live_order_smoketest.py`,
  `scripts/rsi_scanner.py` - operational CLIs, mypy-strict but not unit-tested directly (they're
  thin wrappers around tested `src/` logic, verified by actually running them).
- `tools/sweep.py`, `tools/examples/*.json`, `tools/README.md` - the backtest sweep harness,
  excluded from the strict/coverage gate (an instrument, not shipped code) but still `ruff`-clean.
- `docs/backtest-results.md` - the permanent record of every backtest finding, positive or
  negative. Read before repeating a sweep; append after running a new one.
- `~/kraken-bot-state/` - runtime state: per-bot SQLite databases, logs, PID files, and
  `RESTART.md` (the operational runbook - exact launch commands, current bot roster, current
  positions). Outside the repo, not committed, not in the scratchpad.
- `.env` (gitignored, real secrets) vs `.env.example` (tracked template) - keep the field names in
  sync between them; a stray mismatch has happened before and is easy to miss.
