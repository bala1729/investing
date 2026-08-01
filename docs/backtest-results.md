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

---

## 2026-08-01 — HeikinAshiConfluenceStrategy sweep: 3 symbols x 4 timeframes

**Purpose:** Evaluate the newly-added `HeikinAshiConfluenceStrategy` (EMA(5,10) crossover on
Heikin Ashi candles, confirmed by MACD + RSI + Bollinger Bands) requested as a "2-year backtest
across BTC/USD, ETH/USD, SOL/USD on 1h/4h/1d/1w". Note up front: Kraken's ~720-candle cap means
"2 years" only actually lines up with the **1d** timeframe (720 daily candles ≈ 1.97 years); 1h
only spans ~21 days, 4h ~120 days, and 1w spans however much history Kraken has for that pair
(~13yr for BTC, ~11yr for ETH, only ~5.1yr for SOL, which listed on Kraken more recently).

**Commands run** (each `uv run python scripts/backtest.py --strategy confluence ...`, defaults
otherwise, `--limit 500` for 1h and `--limit 720` for 4h/1d/1w):

```bash
--symbol BTC/USD --timeframe 1h
--symbol BTC/USD --timeframe 4h
--symbol BTC/USD --timeframe 1d
--symbol BTC/USD --timeframe 1w
--symbol ETH/USD --timeframe 1h
--symbol ETH/USD --timeframe 4h
--symbol ETH/USD --timeframe 1d
--symbol ETH/USD --timeframe 1w
--symbol SOL/USD --timeframe 1h
--symbol SOL/USD --timeframe 4h
--symbol SOL/USD --timeframe 1d
--symbol SOL/USD --timeframe 1w
```

### Results

| Symbol | TF | Candles/Span | Return | Buy&Hold | Beat B&H? | Trades | Closed | Win Rate | Max DD |
|---|---|---|---|---|---|---|---|---|---|
| BTC/USD | 1h | ~21d | +3.94% | -1.92% | yes | 13 | 6 | 66.67% | 3.04% |
| BTC/USD | 4h | ~120d | -12.09% | -5.66% | no | 30 | 15 | 20.00% | 17.60% |
| BTC/USD | 1d | ~2yr | -7.31% | +7.36% | no | 30 | 15 | 20.00% | 32.44% |
| BTC/USD | 1w | ~13yr | +2520.82% | +51569.51% | no | 16 | 8 | 62.50% | 44.87% |
| ETH/USD | 1h | ~21d | +0.06% | +2.52% | no | 19 | 9 | 33.33% | 8.09% |
| ETH/USD | 4h | ~120d | -16.51% | -8.78% | no | 32 | 16 | 18.75% | 23.62% |
| ETH/USD | 1d | ~2yr | -34.75% | -26.79% | no | 33 | 16 | 18.75% | 44.92% |
| ETH/USD | 1w | ~11yr | +87.34% | +62267.33% | no | 12 | 6 | 50.00% | 56.95% |
| SOL/USD | 1h | ~21d | -6.72% | -6.55% | no | 20 | 10 | 30.00% | 9.35% |
| SOL/USD | 4h | ~120d | +16.34% | -9.23% | yes | 28 | 14 | 28.57% | 13.01% |
| SOL/USD | 1d | ~2yr | -26.31% | -48.49% | yes | 38 | 19 | 36.84% | 41.22% |
| SOL/USD | 1w | ~5.1yr | +484.06% | +81.23% | yes | 6 | 3 | 66.67% | 31.50% |

### Key takeaways

1. **On the window that actually matches "2 years" (1d), the strategy lost money on all three
   assets** and beat buy-and-hold on exactly one of them (SOL, and only by losing less than an
   even worse buy-and-hold: -26.31% vs -48.49%). BTC and ETH both underperformed simply holding.
2. **Across the full 12-run sweep, the strategy beat buy-and-hold in only 4 of 12 cases** —
   a worse record than the SMA-vs-EMA sweep above. Combining four indicators and adding
   confirmation filters did not produce a more robust edge here; if anything the extra selectivity
   correlated with worse relative performance than the simpler single-indicator crossovers.
3. **Data availability is uneven across symbols.** SOL/USD only has ~268 weekly candles on
   Kraken (~5.1 years) versus BTC's ~13 and ETH's ~11 — its 1w row is not a comparable window to
   the other two.
4. **Several rows have too few closed trades to trust the win rate.** SOL 1w closed only 3
   trades, ETH 1w closed 6, BTC 1w closed 8 — per the Backtesting Guide's own guidance, under
   ~20-30 closed trades the win rate is easily noise, not signal.
5. Combined with the earlier SMA-vs-EMA sweep's exact 4-4 split, the pattern across both
   exploration sessions is consistent: nothing tested so far shows a standalone edge that
   survives being checked across more than one condition. That includes this newer, more
   "sophisticated" strategy — added complexity did not translate into added robustness.

---

## 2026-08-01 (continued) — EMA(10,30) sweep, same 3 symbols x 4 timeframes, for direct comparison

**Purpose:** Run the identical grid (BTC/USD, ETH/USD, SOL/USD x 1h/4h/1d/1w, same `--limit`
values) with `--strategy ema` instead of `confluence`, to directly compare the two on the exact
same data rather than across different sweeps.

**Commands run:** identical to the confluence sweep above, with `--strategy ema` in place of
`--strategy confluence` (default periods, i.e. `ema_crossover_10_30`).

### Results

| Symbol | TF | Return | Buy&Hold | Beat B&H? | Trades | Closed | Win Rate | Max DD |
|---|---|---|---|---|---|---|---|---|
| BTC/USD | 1h | -5.57% | -1.95% | no | 14 | 7 | 0.00% | 7.43% |
| BTC/USD | 4h | -16.37% | -5.69% | no | 24 | 12 | 16.67% | 20.23% |
| BTC/USD | 1d | +21.00% | +7.33% | yes | 26 | 13 | 30.77% | 33.88% |
| BTC/USD | 1w | +11895.92% | +51557.87% | no | 16 | 8 | 50.00% | 68.33% |
| ETH/USD | 1h | -0.75% | +2.47% | no | 14 | 7 | 42.86% | 8.04% |
| ETH/USD | 4h | -9.10% | -8.82% | no | 22 | 11 | 27.27% | 16.96% |
| ETH/USD | 1d | +14.20% | -26.83% | yes | 21 | 10 | 30.00% | 45.55% |
| ETH/USD | 1w | +12869.31% | +62242.33% | no | 16 | 8 | 37.50% | 89.23% |
| SOL/USD | 1h | -3.08% | -6.59% | yes | 10 | 5 | 20.00% | 6.39% |
| SOL/USD | 4h | -9.00% | -9.26% | yes | 24 | 12 | 25.00% | 15.48% |
| SOL/USD | 1d | -38.86% | -48.51% | yes | 28 | 14 | 28.57% | 62.16% |
| SOL/USD | 1w | +178.38% | +81.16% | yes | 4 | 2 | 50.00% | 64.81% |

**EMA(10,30) beat buy-and-hold in 6 of 12 — better than confluence's 4 of 12 on this identical grid.**

### Direct comparison on the 1d (~2yr) timeframe — the window that actually matches "2 years"

| Symbol | EMA(10,30) | Confluence | Buy & Hold |
|---|---|---|---|
| BTC/USD | +21.00% | -7.31% | +7.36% |
| ETH/USD | +14.20% | -34.75% | -26.79% |
| SOL/USD | -38.86% | -26.31% | -48.49% |

EMA(10,30) beat buy-and-hold on all three assets on this timeframe; confluence beat it on only
one (SOL, by losing less than an even worse buy-and-hold).

### Key takeaways

1. **Simpler beat more complex on this identical grid.** The single-indicator EMA crossover beat
   buy-and-hold more often (6/12) than the four-indicator confluence strategy (4/12), and swept
   all three assets on the specific timeframe that maps to the requested "2 years". Combining
   more indicators/filters did not produce a more robust result here — the opposite, in fact.
2. **This isn't strong evidence EMA(10,30) has a real edge either.** The same caveats from every
   prior entry apply: thin closed-trade counts on several rows (SOL 1w: 2 closed; ETH/BTC 1w: 8),
   single-window/in-sample only, and the SMA-vs-EMA sweep from 2026-07-31 already showed this
   exact strategy type splits close to evenly against its SMA counterpart depending on
   asset/timeframe. Outperforming confluence on one grid is a relative comparison, not proof of a
   standalone edge — treat it as "confluence added complexity without demonstrated benefit" more
   than "EMA(10,30) works."

---

## 2026-08-01 (continued) — Multi-timeframe entry confirmation sweep

**⚠️ Correction (2026-08-01, later same day): this entire section used the wrong MTF direction.**
It checked *lower* timeframes as confirmation (e.g. `4h` entry confirmed by `1h`+`15m`), which is
backwards from standard top-down multi-timeframe analysis — the higher timeframes should confirm
the trend, and the timeframe you trade on is the entry. This was caught and fixed; the corrected
implementation and a full re-sweep are in the next section,
["Multi-timeframe entry confirmation sweep (corrected direction)"](#2026-08-01-continued-2--multi-timeframe-entry-confirmation-sweep-corrected-direction).
The numbers below are kept for the record but should not be used to judge the feature.

**What changed:** All three strategies now require lower-timeframe trend alignment before an entry
(not an exit) fires — `4h` confirms against `1h`+`15m`, `1d` confirms against `4h`+`1h`. See
[`docs/trading-bot-design.md` → "Multi-Timeframe Entry Confirmation"](trading-bot-design.md#multi-timeframe-entry-confirmation).
This re-runs the `ema` and `confluence` sweeps from above, but **only on `4h` and `1d`** — the two
timeframes actually affected by this change (`1h`/`1w` have no lower-timeframe mapping and are
unchanged from the entries earlier in this file).

**Commands run:** `scripts/backtest.py --strategy ema|confluence --symbol {BTC/USD,ETH/USD,SOL/USD} --timeframe {4h,1d} --limit 720`
(default periods, `--fee-pct`/`--slippage-pct` at CLI defaults).

### Results

| Strategy | Symbol | TF | Return | Buy&Hold | Beat B&H? | Trades | Closed | Win Rate | Max DD |
|---|---|---|---|---|---|---|---|---|---|
| ema | BTC/USD | 4h | -3.52% | -6.21% | yes | 4 | 2 | 0.00% | 3.52% |
| ema | BTC/USD | 1d | 0.00% | +6.92% | no | 0 | 0 | n/a | 0.00% |
| ema | ETH/USD | 4h | -1.95% | -10.08% | yes | 2 | 1 | 0.00% | 4.45% |
| ema | ETH/USD | 1d | 0.00% | -27.75% | yes* | 0 | 0 | n/a | 0.00% |
| ema | SOL/USD | 4h | -3.63% | -10.56% | yes | 2 | 1 | 0.00% | 3.63% |
| ema | SOL/USD | 1d | 0.00% | -49.21% | yes* | 0 | 0 | n/a | 0.00% |
| confluence | BTC/USD | 4h | -4.15% | -6.20% | yes | 4 | 2 | 0.00% | 4.76% |
| confluence | BTC/USD | 1d | +0.58% | +6.93% | no | 2 | 1 | 100.00% | 4.31% |
| confluence | ETH/USD | 4h | -0.65% | -10.05% | yes | 2 | 1 | 0.00% | 4.54% |
| confluence | ETH/USD | 1d | 0.00% | -27.73% | yes* | 0 | 0 | n/a | 0.00% |
| confluence | SOL/USD | 4h | -2.04% | -10.56% | yes | 2 | 1 | 0.00% | 2.04% |
| confluence | SOL/USD | 1d | 0.00% | -49.21% | yes* | 0 | 0 | n/a | 0.00% |

`*` = zero trades executed, not a skillful call — see takeaway 2 below. On these rows "beats
buy-and-hold" only means "didn't lose money by holding," not "the strategy did anything."

### Why every 1d row (except BTC) shows 0 trades

`--limit 720` on `1d` requests ~2 years of daily candles, but its confirmation timeframes (`4h`,
`1h`) are themselves capped at ~720 candles by Kraken's public endpoint — `1h` only reaches back to
2026-07-02 (~30 days) and `4h` only to 2026-04-04 (~120 days). Every `1d` bar older than that has no
lower-timeframe data to confirm against, so it can never produce a confirmed entry, exactly as
flagged as a known limitation in the design doc before this sweep was run. BTC/USD 1d got lucky
enough to have one crossover land inside the ~30-day confirmable window; ETH and SOL didn't.

### Before/after comparison — same symbol/timeframe rows, MTF confirmation off vs on

| Strategy | Symbol | TF | Return (no MTF) | Return (MTF) | Trades (no MTF → MTF) |
|---|---|---|---|---|---|
| ema | BTC/USD | 4h | -16.37% | -3.52% | 24 → 4 |
| ema | BTC/USD | 1d | +21.00% | 0.00% | 26 → 0 |
| ema | ETH/USD | 4h | -9.10% | -1.95% | 22 → 2 |
| ema | ETH/USD | 1d | +14.20% | 0.00% | 21 → 0 |
| ema | SOL/USD | 4h | -9.00% | -3.63% | 24 → 2 |
| ema | SOL/USD | 1d | -38.86% | 0.00% | 28 → 0 |
| confluence | BTC/USD | 4h | -12.09% | -4.15% | 30 → 4 |
| confluence | BTC/USD | 1d | -7.31% | +0.58% | 30 → 2 |
| confluence | ETH/USD | 4h | -16.51% | -0.65% | 32 → 2 |
| confluence | ETH/USD | 1d | -34.75% | 0.00% | 33 → 0 |
| confluence | SOL/USD | 4h | +16.34% | -2.04% | 28 → 2 |
| confluence | SOL/USD | 1d | -26.31% | 0.00% | 38 → 0 |

### Key takeaways

1. **On `4h`, MTF confirmation cut trade count by roughly 6-15x and improved (or barely changed)
   the return on every single row** for both strategies — every `4h` return moved closer to zero
   or flipped positive relative to its pre-MTF number, and every `4h` row beat buy-and-hold
   afterward versus only some doing so before. This is the one genuinely encouraging result in
   this sweep: on `4h`, where the confirmation data actually covers the whole backtest window,
   filtering out unconfirmed entries reduced losses substantially across the board.
2. **On `1d`, the result is mostly an artifact of the data cap, not a strategy improvement.** 5 of
   6 `1d` rows dropped to 0 trades because `1h`/`4h` confirmation data doesn't reach back far
   enough to cover a ~720-candle daily window (see explanation above). A 0.00% return "beating"
   a strongly negative buy-and-hold is not the strategy doing anything skillful — it's the
   strategy being unable to act at all for almost the entire backtest. The one row that did trade
   (confluence BTC/USD 1d) turned a losing pre-MTF result (-7.31%) into a small gain (+0.58%) on
   a single closed trade — informative as a data point, not as evidence of an edge.
3. **This makes `1d` backtests of MTF-confirmed strategies effectively untestable with the
   current data source** until either the backtest window is shortened to match `1h`'s ~30-day
   coverage, or a paid/deeper historical data source replaces Kraken's public endpoint (already
   flagged as a "Next up" item). The live paper-trading bot doesn't have this problem — it only
   ever needs *recent* lower-timeframe candles, which Kraken's cap always covers going forward.
4. **The `4h` result is worth taking seriously enough to revisit before choosing what to paper
   trade next**, but it's still a single ~120-day window on 2 closed trades per asset at best —
   the Backtesting Guide's own ~20-30 closed trade threshold for trusting a win rate is nowhere
   close to met here. Treat it as a promising direction, not a validated edge.

---

## 2026-08-01 (continued 2) — Multi-timeframe entry confirmation sweep (corrected direction)

**What changed:** The section above had the MTF direction backwards. Standard top-down
multi-timeframe analysis confirms the trend on *higher* timeframes and times the entry on the
timeframe you actually trade — not the other way around. Fixed: the strategy's crossover still
triggers on `--timeframe` candles exactly as before; confirmation now checks two *higher*
timeframes for trend alignment. New mapping (`MTF_CONFIRMATION_MAP` in `src/bot/strategies/base.py`):

| Entry (`--timeframe`) | Setup | Trend |
|---|---|---|
| `15m` | `1h` | `4h` |
| `1h` | `4h` | `1d` |
| `4h` | `1d` | `1w` |
| `1d` | `1w` | `2w` |

This also removes the data-coverage problem the previous section flagged as a known limitation —
higher timeframes always have *at least* as much history as the entry timeframe within Kraken's
~720-candle cap, usually much more, so there's no gap to worry about (see
[`docs/trading-bot-design.md` → "Multi-Timeframe Entry Confirmation"](trading-bot-design.md#multi-timeframe-entry-confirmation)).

**Commands run:** `scripts/backtest.py --strategy ema|confluence --symbol {BTC/USD,ETH/USD,SOL/USD} --timeframe {15m,1h,4h,1d} --limit 720`
(default periods, `--fee-pct`/`--slippage-pct` at CLI defaults).

### Results

| Strategy | Symbol | Entry TF | Confirms against | Return | Buy&Hold | Beat B&H? | Trades | Closed | Win Rate | Max DD |
|---|---|---|---|---|---|---|---|---|---|---|
| ema | BTC/USD | 15m | 1h+4h | -1.03% | -1.89% | yes | 2 | 1 | 0.00% | 1.03% |
| ema | BTC/USD | 1h | 4h+1d | -1.57% | +2.28% | no | 4 | 2 | 0.00% | 3.14% |
| ema | BTC/USD | 4h | 1d+1w | 0.00% | -6.21% | yes* | 0 | 0 | n/a | 0.00% |
| ema | BTC/USD | 1d | 1w+2w | +40.99% | +6.92% | yes | 16 | 8 | 37.50% | 21.41% |
| ema | ETH/USD | 15m | 1h+4h | -6.16% | -0.55% | no | 8 | 4 | 0.00% | 6.16% |
| ema | ETH/USD | 1h | 4h+1d | -0.91% | +8.95% | no | 14 | 7 | 42.86% | 7.55% |
| ema | ETH/USD | 4h | 1d+1w | 0.00% | -10.11% | yes* | 0 | 0 | n/a | 0.00% |
| ema | ETH/USD | 1d | 1w+2w | -22.75% | -27.78% | yes | 4 | 2 | 0.00% | 23.63% |
| ema | SOL/USD | 15m | 1h+4h | -2.41% | -2.71% | yes | 2 | 1 | 0.00% | 3.24% |
| ema | SOL/USD | 1h | 4h+1d | -6.69% | -10.75% | yes | 8 | 4 | 0.00% | 6.81% |
| ema | SOL/USD | 4h | 1d+1w | 0.00% | -10.61% | yes* | 0 | 0 | n/a | 0.00% |
| ema | SOL/USD | 1d | 1w+2w | -10.35% | -49.23% | yes | 12 | 6 | 33.33% | 44.25% |
| confluence | BTC/USD | 15m | 1h+4h | 0.00% | -1.89% | yes* | 0 | 0 | n/a | 0.00% |
| confluence | BTC/USD | 1h | 4h+1d | +1.81% | +2.29% | no | 2 | 1 | 100.00% | 1.27% |
| confluence | BTC/USD | 4h | 1d+1w | -0.54% | -6.20% | yes | 4 | 2 | 50.00% | 6.78% |
| confluence | BTC/USD | 1d | 1w+2w | -8.24% | +6.92% | no | 6 | 3 | 0.00% | 12.87% |
| confluence | ETH/USD | 15m | 1h+4h | -0.26% | -0.55% | yes | 2 | 1 | 0.00% | 0.83% |
| confluence | ETH/USD | 1h | 4h+1d | -4.38% | +8.95% | no | 12 | 6 | 33.33% | 5.91% |
| confluence | ETH/USD | 4h | 1d+1w | 0.00% | -10.11% | yes* | 0 | 0 | n/a | 0.00% |
| confluence | ETH/USD | 1d | 1w+2w | -21.98% | -27.77% | yes | 4 | 2 | 0.00% | 21.98% |
| confluence | SOL/USD | 15m | 1h+4h | 0.00% | -2.73% | yes* | 0 | 0 | n/a | 0.00% |
| confluence | SOL/USD | 1h | 4h+1d | -1.87% | -10.77% | yes | 2 | 1 | 0.00% | 2.39% |
| confluence | SOL/USD | 4h | 1d+1w | 0.00% | -10.61% | yes* | 0 | 0 | n/a | 0.00% |
| confluence | SOL/USD | 1d | 1w+2w | -5.09% | -49.23% | yes | 4 | 2 | 50.00% | 15.55% |

`*` = zero trades executed — the higher-timeframe trend gate never once aligned bullish anywhere
in the backtest window, so "beats buy-and-hold" here means "did nothing while the asset fell,"
not "the strategy performed well." Verified directly for the `4h` entry / BTC/USD case: walking
the exact backtester logic bar-by-bar across all 720 `4h` candles, the `1d`+`1w` EMA(10,30) trend
was never simultaneously bullish once in the whole ~120-day window (0/720 bars confirmed) — a real
market condition (BTC/ETH/SOL all in a weekly downtrend the entire window per the raw EMA check),
not a bug.

### Why every `4h` entry row shows 0 trades

The `4h` entry timeframe is gated by `1d` and, above that, `1w` — a genuinely slow-moving trend
filter (EMA(30) on weekly bars smooths over ~30 weeks / ~7 months). Across the ~120-day window
these `4h` backtests cover, the weekly trend for BTC, ETH, and SOL was bearish the entire time, so
no `4h` crossover — no matter how many fired — could ever pass confirmation. This is the filter
doing exactly what a trend filter is supposed to do (refuse to buy dips inside a broader
downtrend); whether that's the right tradeoff depends on whether you'd rather sit out a downtrend
entirely or catch the bounces within it. It is not evidence of a bug, and it is not evidence the
`4h` config is "safe" — it's evidence this particular ~120-day window was a sustained downtrend.

### Key takeaways

1. **Discard the previous (wrong-direction) section's conclusions entirely** — they were measuring
   a different, backwards mechanism. Nothing about "which timeframes had enough data" carries over;
   the coverage-cap problem that section's takeaways centered on doesn't exist in the corrected
   direction.
2. **Excluding the zero-trade rows, MTF confirmation beat buy-and-hold in 9 of 15 real (non-trivial)
   runs** — `ema`: BTC/15m, SOL/15m, SOL/1h, BTC/1d, ETH/1d, SOL/1d (6/9 non-trivial ema rows);
   `confluence`: BTC/4h, ETH/15m, SOL/1h, ETH/1d, SOL/1d (5/9, though BTC/4h and SOL/1d only had
   2 closed trades each). Better than a coin flip, but every row is well under the ~20-30 closed
   trades needed to trust a win rate — treat this as a promising direction, not a validated edge.
3. **The best-looking single result, `ema` on BTC/USD `1d` (+40.99% vs +6.92% buy-and-hold, 8
   closed trades, 37.5% win rate)**, is also the row with the most closed trades in this whole
   sweep — worth a closer look (different symbols, different windows) before reading too much
   into one number, but it's the one result here that clears the trade-count bar enough to take
   seriously.
4. **`4h` entries were unconditionally net-negative for testability this window** — 5 of 6 `4h`
   rows produced zero trades because of the sustained bearish weekly trend described above, not
   because of a data limitation. A `4h`-entry/`1w`-trend combination will only ever be useful in a
   market that's had a bullish weekly trend at some point in the test window — worth re-running
   this specific combination during a different market regime before drawing any conclusion from
   it either way.
5. **As with every sweep in this file, this remains single-window, in-sample, and thin on closed
   trades** — no result here should move the paper-trading bot's configuration on its own. It's a
   data point to weigh alongside the earlier sweeps, not a replacement for them.

---

## 2026-08-01 (continued 3) — SOL/USD scalping timeframes: 5m vs 15m, EMA(10,30) vs EMA(5,10)

**Purpose:** Compare the two fastest entry timeframes against each other on SOL/USD, with both a
slower and a faster EMA pair, to see whether short-timeframe trading is viable at all here.

**Setup note:** `5m` had no `MTF_CONFIRMATION_MAP` entry before this run, which would have made the
comparison meaningless — `5m` would have run unfiltered against a `15m` that was MTF-gated. Added
`5m` → `15m` (setup) + `1h` (trend) first, following the same ladder as the other rows, so both
timeframes in this comparison are confirmed the same way.

**Commands run:** `scripts/backtest.py --strategy ema --symbol SOL/USD --timeframe {5m,15m} --fast {10,5} --slow {30,10} --limit 720`
(`--fee-pct`/`--slippage-pct` at CLI defaults).

### Results

| Entry TF | Confirms against | Periods | Return | Buy&Hold | Beat B&H? | Trades | Closed | Win Rate | Fees (% of start) | Max DD |
|---|---|---|---|---|---|---|---|---|---|---|
| 5m | 15m+1h | EMA(10,30) | -4.79% | -2.97% | no | 10 | 5 | 0.00% | 2.55% | 4.79% |
| 5m | 15m+1h | EMA(5,10) | -8.04% | -2.97% | no | 22 | 11 | 0.00% | 5.50% | 8.04% |
| 15m | 1h+4h | EMA(10,30) | -2.41% | -2.74% | yes | 2 | 1 | 0.00% | 0.51% | 3.24% |
| 15m | 1h+4h | EMA(5,10) | -10.05% | -2.74% | no | 26 | 13 | 7.69% | 6.49% | 10.05% |

### Key takeaways

1. **Every config lost money, and fees explain most of the spread.** Adding fees back gives rough
   gross returns of -2.2%, -2.5%, -1.9%, -3.6% — all clustered near buy-and-hold's ~-2.9%. The net
   differences between these four are almost entirely trading costs, not signal quality. (Rough
   figures: fees compound within the run, so this is an approximation, not an exact gross return.)
2. **EMA(5,10) is decisively worse than EMA(10,30) on both timeframes**, and the period choice
   matters more than the timeframe choice. It roughly doubled trade count and roughly doubled
   losses on each timeframe, paying 5.5-6.5% of the account in fees alone. At these speeds the
   strategy is mostly paying the exchange.
3. **Win rates of 0.00%, 0.00%, 0.00%, 7.69% across 30 closed trades combined** is the strongest
   signal in this table, and it's negative. Not one config produced a meaningfully profitable
   trade. That's worse than coin-flip-like behavior on trades that each cost ~0.5% round trip.
4. **The single "win" (15m EMA(10,30), -2.41% vs -2.74%) is noise** — it beat buy-and-hold by
   0.33pp on exactly one closed trade, mostly by trading so rarely it barely participated.
5. **These windows are far shorter than anything else in this file.** Kraken's ~720-candle cap
   means `5m` covers only ~2.5 days and `15m` only ~7.5 days, versus months or years for the
   coarser timeframes. Nothing here generalizes; treat it as a snapshot of one week at most.
6. **Practical read: short-timeframe EMA crossover scalping on SOL/USD looks unpromising once
   realistic fees are modeled.** The faster you trade, the more reliably fees dominate. If
   short-timeframe trading is worth pursuing, it likely needs either a much lower fee tier, a
   signal with a materially better win rate, or holding periods long enough that ~0.5% round-trip
   costs stop being the deciding factor.
