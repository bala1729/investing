# Backtest Results Log

A running record of `scripts/backtest.py` sweeps, kept so future runs can be compared against
past ones — did a config's numbers hold up, drift, or was a "good" result just noise on one
historical window? See [`docs/trading-bot-design.md` → "Backtesting Guide"](trading-bot-design.md#backtesting-guide)
for how to interpret the metrics below and the engine's limitations before trusting any of this.

**Important caveat on reproducibility:** Kraken's public OHLC endpoint always returns the most
recent ~720 candles — there's no way to pin a specific historical window. Re-running the exact
same command next week will fetch a different (shifted-forward) set of candles and will *not*
reproduce these exact numbers. Treat each entry here as a dated snapshot, not a fixed regression
test. Fee/slippage defaults at the time of each run: `--fee-pct 0.26 --slippage-pct 0.05` (CLI
defaults) unless noted otherwise.

---

## 2026-07-31 — SMA vs EMA sweep across periods, symbols, and timeframes

**Purpose:** Compare the two example crossover strategies before pointing the bot at any paper
trades, per `CLAUDE_PROJECT_STATUS.md`'s roadmap (backtesting exploration before live/paper runs).

**Commands run** (each `uv run python scripts/backtest.py ...`, defaults except as shown):

```bash
--symbol BTC/USD --timeframe 1d --limit 720 --strategy sma --fast 10 --slow 30
--symbol BTC/USD --timeframe 1d --limit 720 --strategy ema --fast 10 --slow 30
--symbol BTC/USD --timeframe 1d --limit 720 --strategy sma --fast 5  --slow 20
--symbol BTC/USD --timeframe 1d --limit 720 --strategy ema --fast 5  --slow 20
--symbol BTC/USD --timeframe 1d --limit 720 --strategy sma --fast 20 --slow 50
--symbol BTC/USD --timeframe 1d --limit 720 --strategy ema --fast 20 --slow 50
--symbol ETH/USD --timeframe 1d --limit 720 --strategy sma --fast 10 --slow 30
--symbol ETH/USD --timeframe 1d --limit 720 --strategy ema --fast 10 --slow 30
--symbol ETH/USD --timeframe 1d --limit 720 --strategy sma --fast 5  --slow 20
--symbol ETH/USD --timeframe 1d --limit 720 --strategy ema --fast 5  --slow 20
--symbol BTC/USD --timeframe 1h --limit 500 --strategy sma --fast 10 --slow 30
--symbol BTC/USD --timeframe 1h --limit 500 --strategy ema --fast 10 --slow 30
--symbol BTC/USD --timeframe 1w --limit 720 --strategy sma --fast 10 --slow 30
--symbol BTC/USD --timeframe 1w --limit 720 --strategy ema --fast 10 --slow 30
```

### Results

| Symbol | TF | Params | Return | Buy&Hold | Trades | Closed | Win Rate | Max DD | Fees Paid |
|---|---|---|---|---|---|---|---|---|---|
| BTC/USD | 1d (~2yr) | SMA 10/30 | +3.16% | +7.25% | 29 | 14 | 28.57% | 39.93% | 935.22 |
| BTC/USD | 1d (~2yr) | EMA 10/30 | +21.00% | +7.25% | 26 | 13 | 30.77% | 33.88% | 898.14 |
| BTC/USD | 1d (~2yr) | SMA 5/20 | +14.38% | +7.25% | 40 | 20 | 30.00% | 31.83% | 1366.77 |
| BTC/USD | 1d (~2yr) | EMA 5/20 | +4.52% | +7.25% | 42 | 21 | 19.05% | 41.16% | 1366.85 |
| BTC/USD | 1d (~2yr) | SMA 20/50 | −23.09% | +7.24% | 17 | 8 | 12.50% | 33.26% | 404.95 |
| BTC/USD | 1d (~2yr) | EMA 20/50 | −13.38% | +7.24% | 10 | 5 | 20.00% | 33.79% | 260.45 |
| ETH/USD | 1d (~2yr) | SMA 10/30 | +20.59% | −26.96% | 29 | 14 | 35.71% | 47.34% | 950.90 |
| ETH/USD | 1d (~2yr) | EMA 10/30 | +14.00% | −26.96% | 21 | 10 | 30.00% | 45.55% | 614.22 |
| ETH/USD | 1d (~2yr) | SMA 5/20 | −33.34% | −26.96% | 43 | 21 | 23.81% | 53.43% | 971.13 |
| ETH/USD | 1d (~2yr) | EMA 5/20 | +39.55% | −26.96% | 33 | 16 | 25.00% | 45.60% | 1158.12 |
| BTC/USD | 1h (~21d) | SMA 10/30 | −3.39% | −1.77% | 16 | 8 | 50.00% | 5.79% | 413.72 |
| BTC/USD | 1h (~21d) | EMA 10/30 | −5.57% | −1.77% | 14 | 7 | 0.00% | 7.43% | 355.66 |
| BTC/USD | 1w (~13yr) | SMA 10/30 | +7058.62% | +51523.36% | 22 | 11 | 54.55% | 67.37% | 18862.84 |
| BTC/USD | 1w (~13yr) | EMA 10/30 | +11895.92% | +51523.36% | 16 | 8 | 50.00% | 68.33% | 11127.17 |

### Key takeaways

1. **Parameter instability is the headline finding.** ETH/USD 1d: SMA(5,20) loses 33.3%, EMA(5,20)
   gains 39.6% — a 73-point swing from switching MA type alone on identical data. BTC's SMA(20,50)
   loses 23.1% while SMA(10,30) gains 3.2%. Results this sensitive to arbitrary parameter choices
   are the classic signature of curve-fit noise, not a robust edge — don't trust any single row in
   isolation.
2. **Recent short-term conditions (1h, ~21 days) were bad for both strategies.** Both lost money
   and underperformed buy-and-hold; EMA's win rate was 0% (0 of 7 closed trades profitable).
   Starting paper trading in this kind of window should be expected to look like this, not treated
   as a sign something is broken.
3. **Long-run (13yr) both "win" in absolute terms but badly lag buy-and-hold** (7,059%/11,896% vs
   51,523%) — a long-only crossover system exits and re-enters repeatedly through a multi-year
   secular bull run, missing large chunks of the move each time it's flat.
4. **No single config won cleanly across every horizon tested.** BTC/USD SMA(10,30) — the least
   "cherry-picked" choice in the set — beat buy-and-hold modestly on the 1d window, but lost to it
   on the 1h window and badly lagged it on the 1w window.
5. Several closed-trade counts are thin (5–8 for the 20/50 pair and the 1w runs) — per the
   Backtesting Guide's own guidance, under ~20–30 closed trades means the win rate is easily noise.

### Conclusion at the time of this run

No config here inspired strong confidence in a standalone edge — the data reads more as "this
parameter space is noisy" than "here's the edge." Leaning toward **BTC/USD, SMA(10,30)** as the
first paper-trading candidate specifically *because* it's the closest thing to an unremarkable,
non-cherry-picked default in the sweep — not because it had the best headline number (EMA(5,20) on
ETH/USD did, and is likely the most overfit-looking result in the table).

---

## 2026-07-31 (continued) — SMA vs EMA(10/30) head-to-head across timeframes

**Purpose:** The sweep above showed EMA(10,30) clearly beating SMA(10,30) on BTC/USD 1d (return
+21.0% vs +3.16%, and a lower max drawdown too), which raised a fair question: is EMA actually the
better choice, and was leaning toward SMA above the wrong call? Filled out the grid — both assets
already tested (BTC/USD, ETH/USD), across all four timeframes already used (1h, 4h, 1d, 1w) — to
check whether that one comparison generalizes or was a one-off.

**Commands run** (each `uv run python scripts/backtest.py --fast 10 --slow 30 ...`, `--strategy`
and `--symbol`/`--timeframe` varied, `--limit` 500 for 1h and 720 for 4h/1d/1w):

```bash
--symbol BTC/USD --timeframe 1h --limit 500 --strategy sma   # (already had this + 1d + 1w from the sweep above)
--symbol BTC/USD --timeframe 1h --limit 500 --strategy ema
--symbol BTC/USD --timeframe 4h --limit 720 --strategy sma
--symbol BTC/USD --timeframe 4h --limit 720 --strategy ema
--symbol ETH/USD --timeframe 1h --limit 500 --strategy sma
--symbol ETH/USD --timeframe 1h --limit 500 --strategy ema
--symbol ETH/USD --timeframe 4h --limit 720 --strategy sma
--symbol ETH/USD --timeframe 4h --limit 720 --strategy ema
--symbol ETH/USD --timeframe 1w --limit 720 --strategy sma
--symbol ETH/USD --timeframe 1w --limit 720 --strategy ema
```

### Results (full grid, combining with the 1d/1h/1w BTC/USD rows from the sweep above)

| Symbol | TF | SMA Return | EMA Return | Winner (return) | SMA Max DD | EMA Max DD | Winner (DD) |
|---|---|---|---|---|---|---|---|
| BTC/USD | 1h | −3.39% | −5.57% | SMA | 5.79% | 7.43% | SMA |
| BTC/USD | 4h | −22.41% | −16.37% | EMA | 25.43% | 20.23% | EMA |
| BTC/USD | 1d | +3.16% | +21.00% | EMA | 39.93% | 33.88% | EMA |
| BTC/USD | 1w | +7058.62% | +11895.92% | EMA | 67.37% | 68.33% | SMA |
| ETH/USD | 1h | +0.11% | −3.56% | SMA | 6.20% | 8.04% | SMA |
| ETH/USD | 4h | −23.84% | −9.10% | EMA | 28.20% | 16.96% | EMA |
| ETH/USD | 1d | +20.59% | +14.00% | SMA | 47.34% | 45.55% | EMA |
| ETH/USD | 1w | +32001.80% | +12869.31% | SMA | 72.64% | 89.23% | SMA |

**Return: EMA wins 4/8, SMA wins 4/8. Max drawdown: EMA wins 4/8, SMA wins 4/8.** An exact split
on both axes across 8 independent (asset, timeframe) combinations.

### Key takeaways

1. **The BTC/USD 1d result that favored EMA does not generalize.** It was one of the four cases
   where EMA happened to win, not evidence of a general EMA edge — widening the comparison from 1
   data point to 8 flips the apparent "EMA is better" signal into a clean coin-flip.
2. **This is a sharper version of the same conclusion as the sweep above**, now specifically on
   the SMA-vs-EMA axis rather than the period-choice axis: an exact 4-4 split on both return and
   drawdown is about as clean a "no consistent winner" signal as a small grid like this can produce.
3. **Mild, low-confidence pattern:** EMA won on every 4h test (both BTC and ETH). Could be a real
   timeframe-specific effect, or could just be 2 correlated data points — not enough to act on
   alone, but worth another look if more 4h evidence accumulates later.
4. Revises the earlier "lean toward SMA because it's the more vanilla default" framing — that
   reasoning was weak (EMA(10,30) is just as standard/common as SMA(10,30), not more "exotic" or
   cherry-picked). The stronger, corrected justification for not preferring one over the other:
   there is no evidence either one has a real edge, so pick based on something more stable, like
   the max drawdown you're actually willing to tolerate, not on backtested return.
