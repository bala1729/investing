# Backtest Results Log

A running record of `scripts/backtest.py` sweeps, kept so future runs can be compared against
past ones — did a config's numbers hold up, drift, or was a "good" result just noise on one
historical window? See [`docs/trading-bot-design.md` → "Backtesting Guide"](trading-bot-design.md#backtesting-guide)
for how to interpret the metrics below and the engine's limitations before trusting any of this.

**Two eras of entries in this file — read the caveat that applies to the one you're looking at.**

**Entries before 2026-08-02 are REST-sourced and irreproducible.** Kraken's public OHLC endpoint
always returns the most recent ~720 candles, with no way to pin a historical window — re-running
the same command later fetches a different, shifted-forward set of candles and will *not* reproduce
those numbers. Worse, the cap silently truncated the windows themselves: `1h` sweeps covered only
~30 days and `4h` only ~120 days, which is why several of those sweeps produced 1-2 closed trades
per row, and why one multi-timeframe sweep produced *zero* trades on 6 of 24 rows purely because
its short window happened to be a sustained downtrend. Treat every pre-2026-08-02 entry as a dated
snapshot of a short window, not as evidence about a strategy.

**Entries from 2026-08-02 onward are CSV-sourced and reproducible.** They build candles from
Kraken's downloadable tick archive (`--data-source csv`, the default), so a given `--start`/`--end`
always yields identical candles and the numbers can be re-derived exactly. Full history is
available: BTC from 2013, ETH from 2015, SOL from 2021. The archive ends **2025-12-31**, so these
entries cover different windows than the older ones and are **not** directly comparable to them.

Fee/slippage defaults at the time of each run: `--fee-pct 0.26 --slippage-pct 0.05` (CLI defaults)
unless noted otherwise.

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

---

## 2026-08-02 — First full-history sweep (CSV data): 159 runs

**This is the first entry in this file built on reproducible, full-history data.** Everything above
was measured through Kraken's REST endpoint on windows of ~30-120 days with, in many rows, 1-2
closed trades — sample sizes that cannot support the conclusions drawn from them.

**Setup:** `--data-source csv` over the full tick archive. 159 runs. Multi-timeframe confirmation is
active throughout (each entry timeframe gated by its two higher timeframes). Windows are the four
calendar years 2022-2025 plus `full` (BTC from 2013, ETH from 2015, SOL from 2021; archive ends
2025-12-31). `15m` has no `full` row — BTC alone would be ~385k candles, and the backtester's
per-bar cost grows superlinearly.

> **Correction:** an earlier version of this section was published with slightly different numbers.
> `--start` was being applied to the confirmation timeframes as well as the entry timeframe, which
> starved their indicators of warmup (a calendar year holds only ~25 of Kraken's 15-day `2w`
> candles, fewer than an EMA(30) needs). Fixed in `167616a`; every number below is post-fix. The
> qualitative conclusions were unchanged — the per-year pattern in particular came out identical.

### The pending question: MACD vs EMA (1h)

| Symbol | Window | EMA(10,30) | EMA(9,26) | MACD(12,26,9) | Buy&Hold |
|---|---|---|---|---|---|
| BTC/USD | 2022 | -13.52% | -11.94% | **-42.94%** | -64.08% |
| BTC/USD | 2023 | -14.44% | -14.61% | **-36.04%** | +156.22% |
| BTC/USD | 2024 | -12.77% | -3.08% | **-45.35%** | +118.33% |
| BTC/USD | 2025 | -27.12% | -27.02% | **-42.69%** | -5.56% |
| BTC/USD | full | +598.75% | +553.31% | **-97.78%** | +71621.39% |
| ETH/USD | 2022 | -19.89% | -25.70% | **-35.41%** | -67.44% |
| ETH/USD | 2023 | -24.87% | -36.92% | **-38.67%** | +92.53% |
| ETH/USD | 2024 | +14.82% | +14.10% | **-27.96%** | +45.63% |
| ETH/USD | 2025 | +67.46% | +28.81% | **-12.69%** | -11.13% |
| ETH/USD | full | +7893.50% | +1571.94% | **-73.28%** | +98804.33% |
| SOL/USD | 2022 | +17.90% | +7.27% | **-1.97%** | -94.13% |
| SOL/USD | 2023 | +272.34% | +177.98% | **+0.22%** | +928.59% |
| SOL/USD | 2024 | +9.02% | +11.06% | **-51.61%** | +86.50% |
| SOL/USD | 2025 | -26.83% | -3.32% | **-34.20%** | -33.95% |
| SOL/USD | full | +448.30% | +381.94% | **-11.69%** | +209.30% |

**MACD(12,26,9) made money in 1 of 15 runs, and that one was +0.22%.** Over full history it
destroyed the account on BTC (-97.78%, 99.2% max drawdown) and ETH (-73.28%, 94.7%). The mechanism
is in the trade counts: MACD closed 2.4-2.7x as many trades as EMA on the same data (BTC 1456 vs
543, ETH 1180 vs 462, SOL 420 vs 178). Its signal-line crossover fires when momentum turns rather
than when price crosses, which is genuinely earlier — but at ~0.5% round-trip cost that extra
sensitivity is a pure liability. **Is MACD better than EMA here? No, and not marginally.**

EMA(9,26) vs EMA(10,30) is a coin flip (9/26 won 7 of 15 cells, differences mostly inside the
noise). The earlier REST-based hint that 9/26 might edge out 10/30 rested on 1-2 closed trades per
row and should be disregarded.

### Entry timeframe matters more than strategy choice

Yearly windows only (2022-2025 x 3 symbols = 12 runs per cell):

| Strategy | Entry TF | Confirms against | Avg return | Beat B&H | Profitable | Closed trades | Avg maxDD |
|---|---|---|---|---|---|---|---|
| ema(10,30) | **15m** | 1h+4h | **-59.35%** | 1/12 | **0/12** | 2420 | 66.2% |
| ema(10,30) | 1h | 4h+1d | +20.17% | 5/12 | 5/12 | 469 | 27.3% |
| ema(10,30) | 4h | 1d+1w | +7.15% | 5/12 | 5/12 | 114 | 17.0% |
| ema(10,30) | 1d | 1w+2w | +12.61% | 5/12 | 5/12 | 22 | 17.0% |
| confluence | **15m** | 1h+4h | **-13.16%** | 4/12 | 2/12 | 1131 | 28.5% |
| confluence | 1h | 4h+1d | +3.23% | 6/12 | 5/12 | 233 | 12.9% |
| confluence | 4h | 1d+1w | +4.77% | 6/12 | 4/12 | 76 | 8.8% |
| confluence | 1d | 1w+2w | +7.55% | 5/12 | 4/12 | 16 | 7.7% |

**`15m` entries lost money in 12 of 12 runs for EMA** — average -59% per year, with 2420 closed
trades against `1d`'s 22. Drawdown also falls monotonically as the timeframe coarsens (66% → 27% →
17% → 17%). This is the fee-drag result from the earlier scalping comparison, now measured on
adequate samples: **the faster you trade these crossovers, the more reliably costs dominate.**

### Full history, 4h and 1d

| Strategy | Symbol | TF | Return | Buy&Hold | Closed | MaxDD |
|---|---|---|---|---|---|---|
| ema(10,30) | BTC/USD | 1d | +13653.43% | +71621.39% | 28 | 52.5% |
| ema(10,30) | ETH/USD | 1d | +1321.76% | +98804.33% | 21 | 52.4% |
| ema(10,30) | SOL/USD | 1d | -9.45% | +209.30% | 10 | 54.4% |
| ema(10,30) | BTC/USD | 4h | +2354.16% | +71621.39% | 149 | 47.4% |
| ema(10,30) | ETH/USD | 4h | +5270.42% | +98804.33% | 126 | 59.1% |
| ema(10,30) | SOL/USD | 4h | +25.97% | +209.30% | 32 | 42.2% |
| confluence | BTC/USD | 1d | +1300.59% | +71621.39% | 23 | 32.4% |
| confluence | ETH/USD | 1d | +95.84% | +98804.33% | 16 | 36.7% |
| confluence | SOL/USD | 1d | -13.04% | +209.30% | 5 | 21.9% |
| confluence | BTC/USD | 4h | +54.12% | +71621.39% | 82 | 32.6% |
| confluence | ETH/USD | 4h | +2967.86% | +98804.33% | 67 | 39.0% |
| confluence | SOL/USD | 4h | +136.25% | +209.30% | 24 | 21.0% |

**Not one full-history row beat buy-and-hold.** Confluence trades less and draws down less than EMA
(21-39% vs 42-59%) but also returns far less — it is a lower-exposure version of the same thing,
not a better signal.

### The headline finding: "beats buy-and-hold" has been measuring market direction

Beat-buy-and-hold on `1h`, per year, aggregated across the three symbols:

| Year | Avg buy&hold | sma | ema(10,30) | ema(9,26) | macd | confluence |
|---|---|---|---|---|---|---|
| 2022 | **-75.22%** | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| 2023 | **+392.44%** | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| 2024 | **+83.49%** | 0/3 | 0/3 | 0/3 | 0/3 | 1/3 |
| 2025 | **-16.88%** | 2/3 | 2/3 | 2/3 | 0/3 | 2/3 |

In the two down years nearly every strategy beat buy-and-hold on nearly every symbol; in the two up
years nearly none did. That is the signature of **reduced market exposure**, not predictive skill —
a long-only strategy that sits in cash part of the time mechanically loses less in a crash and
captures less in a rally. You would get the same shape from flipping a coin about when to hold.

The practical consequence: **beating buy-and-hold on a window that happened to be a drawdown is not
evidence of edge**, and every "beat B&H N/M" claim earlier in this file was partly measuring which
way the market went during a short window. Judge configs within a regime, or against an
exposure-matched baseline.

### A real design flaw: confirmation can permanently veto a trend

15 of 159 runs made **zero trades**, all in 2022 or 2023. 2022 is legitimate (higher timeframes were
bearish ~98% of the year). 2023 is not, and the trace is instructive — BTC/USD `1d`, 2023, a +156%
year, produced 7 crossovers:

| Date | Signal | Higher TFs confirmed? |
|---|---|---|
| 2023-01-09 | buy | no |
| 2023-03-06 | sell | no |
| 2023-03-15 | buy | no |
| 2023-05-09 | sell | no |
| 2023-06-21 | buy | no |
| 2023-07-26 | sell | **yes** |
| 2023-09-29 | buy | **yes** |

Entry requires a *fresh crossover* **and** confirmation **on the same bar**. Every BUY before
September fired while the weekly trend was still bearish and was discarded. By the time the weekly
turned bullish (54% of 2023 qualified), the daily EMAs had long since crossed — so there was no
fresh cross left to trigger on, and the strategy sat out the year.

**This is a design flaw, not a bug.** A state-based entry ("enter when confirmed *and* fast > slow")
would have caught the trend; the current cross-only entry cannot. Worth fixing before drawing
further conclusions about whether MTF confirmation helps.

### Key takeaways

1. **MACD(12,26,9) is not viable on `1h`** — 1/15 profitable, near-total drawdowns over long
   windows. Do not paper-trade it.
2. **Entry timeframe dominates strategy choice.** `15m` lost money in 12/12 EMA runs; coarser
   timeframes were consistently better on both return and drawdown. Fees explain it.
3. **"Beats buy-and-hold" tracked market direction, not skill** — see the per-year table. This
   undermines the headline claim of nearly every earlier entry in this file.
4. **No full-history row beat buy-and-hold on any asset.**
5. **The MTF entry rule has a defect** that can veto an entire trend (above). Any conclusion about
   whether multi-timeframe confirmation helps is premature until that is addressed.
6. **Sample sizes are finally adequate** — 5 to 2420 closed trades per cell, versus the 1-2 several
   earlier entries rested on. Where this sweep contradicts an earlier entry, believe this one.

---

## 2026-08-02 (continued) — Same 159 runs, with state-based entry

**What changed:** entries now key off "is the trend bullish now" rather than "did it just turn
bullish" (`bbe79ca`), fixing the flaw documented in the previous section where a crossover vetoed by
higher-timeframe confirmation was discarded permanently. Identical sweep otherwise, so every row
below is directly comparable to the one above it.

### The fix works as intended

| | Before | After |
|---|---|---|
| Runs making zero trades | 15 | 10 |
| `ema(10,30)` profitable | 23/57 | **32/57** |
| `confluence` profitable | 23/57 | **32/57** |
| `ema(10,30)` beat B&H | 17/57 | 22/57 |
| `confluence` beat B&H | 21/57 | 23/57 |
| Full-history rows beating B&H | **0/27** | **10/27** |

The specific case that motivated the change: BTC/USD `1d` in 2023 went from sitting out a +156% year
to +52.53%; ETH/USD `1d` 2023 went from zero trades to +13.02%.

### But the headline result does not survive scrutiny

Going from 0 to 10 full-history wins looks like vindication. It isn't. **All ten have the same
yearly record — win the down years, lose the up years:**

| Config | 2022 (B&H −75%) | 2023 (B&H +392%) | 2024 (B&H +83%) | 2025 (B&H −17%) |
|---|---|---|---|---|
| ema(10,30) ETH 1h | **W** | L | L | **W** |
| ema(9,26) ETH 1h | **W** | L | L | **W** |
| confluence ETH 4h | **W** | L | L | **W** |
| confluence ETH 1d | **W** | L | **W** | **W** |
| sma(10,30) SOL 1h | **W** | L | L | **W** |
| ema(10,30) SOL 1h | **W** | L | L | **W** |
| ema(9,26) SOL 1h | **W** | L | L | **W** |
| confluence SOL 1h | **W** | L | L | **W** |
| ema(10,30) SOL 4h | **W** | L | L | **W** |
| confluence SOL 1d | **W** | L | L | **W** |

10/10 won 2022. 10/10 lost 2023. 9/10 lost 2024. 10/10 won 2025. A full-history win is therefore
just what happens when a long window contains crashes: sidestepping a −67% year compounds enough to
carry the whole record, even while losing to buy-and-hold in every rally.

**Confirmed independently by moving the start date.** `confluence` on ETH/USD `1d`:

| Window start | Strategy | Buy&Hold | |
|---|---|---|---|
| 2015-08 (full) | +473706.78% | +98804.33% | beats B&H 4.8x |
| 2018-01 | +788.42% | +298.60% | beats B&H |
| **2020-01** | **+374.38%** | **+2206.18%** | **loses by ~6x** |

The +473,706% is an artifact of compounding through 2015-2017, when ETH went from ~$1 to ~$1400 on
thin Kraken liquidity — the era where the 100%-position-size, fill-at-the-open model is least
believable. Start in 2020 and the same config loses to buy-and-hold badly.

**The per-year beat-B&H table is byte-identical to the pre-fix sweep** (3/3, 0/3, 0/3, 2/3 for
almost every strategy). State-based entry improved *absolute* returns by letting positions be taken
at all; it did not change what these strategies are.

### Entry timeframe, before vs after

Yearly windows (12 runs per cell):

| Strategy | Entry TF | Avg return | was | Beat B&H | Profitable | Closed | Avg maxDD |
|---|---|---|---|---|---|---|---|
| ema(10,30) | **15m** | **-56.40%** | -59.35% | 1/12 | 1/12 | 3309 | 68.9% |
| ema(10,30) | 1h | +34.14% | +20.17% | 5/12 | 7/12 | 662 | 27.9% |
| ema(10,30) | 4h | +32.69% | +7.15% | 7/12 | 8/12 | 150 | 17.2% |
| ema(10,30) | 1d | +19.05% | +12.61% | 6/12 | 7/12 | 28 | 19.9% |
| confluence | **15m** | **-74.72%** | -13.16% | 1/12 | 0/12 | 5606 | 80.2% |
| confluence | 1h | +28.17% | +3.23% | 6/12 | 7/12 | 1122 | 23.4% |
| confluence | 4h | +10.53% | +4.77% | 5/12 | 7/12 | 268 | 18.0% |
| confluence | 1d | **+41.56%** | +7.55% | 7/12 | 9/12 | 50 | 16.3% |

Every timeframe improved except `15m`, which got *worse* for confluence (-13% -> -75%) — state-based
entry means more participation, and on a timeframe where fees already dominate, more participation
is more damage. 5,606 closed trades at ~0.5% round-trip is the entire story. **`15m` remains
unusable: 0/12 profitable for confluence, 1/12 for EMA.**

### Key takeaways

1. **The fix is real and worth keeping** — 5 fewer dead runs, ~40% more profitable runs, and the
   specific missed-trend failure is gone.
2. **It did not produce edge.** The down-year/up-year pattern is unchanged, and the new
   full-history wins are a compounding artifact of including crash years, demonstrated two ways
   (uniform W-L-L-W yearly records; ETH from 2020 losing to buy-and-hold by ~6x).
3. **These remain drawdown-avoidance systems, not alpha.** That is a legitimate thing to want — the
   `1d` configs cut max drawdown to 16-20% against buy-and-hold's much deeper holes — but it should
   be chosen deliberately, not mistaken for outperformance.
4. **Faster is still worse.** `15m` lost money in 23 of 24 runs across both strategies.
5. **Long-window headline returns should not be quoted without a start-date sensitivity check.**
   One start date moved a result from "beats buy-and-hold 4.8x" to "loses by 6x".

---

## 2026-08-03 — EMA(5,10) vs EMA(10,30) on 1h, and a start-date sensitivity check

**Purpose:** Settle whether the faster EMA pair is worth its extra turnover, on the timeframe both
paper-trading bots actually run. Then test whether the full-history headline numbers survive a
later start date — the check that reversed the ETH result in the previous entry.

**How run:** a sweep harness that loads each symbol's cached 1-minute candles once and replays
every config against them, rather than re-reading the cache per invocation. Same engine, fees and
slippage as `scripts/backtest.py` (`0.26%` / `0.05%`), `1h` entry with MTF confirmation against
`4h`+`1d`. Windows bound the entry timeframe only; confirmation timeframes keep their warmup bars
(see the 2026-08-02 entry on `--start` starving confirmation).

### Per-year and full history

| Symbol | Window | EMA(5,10) | EMA(10,30) | Buy & hold | 5,10 closed | 10,30 closed |
|---|---|---|---|---|---|---|
| BTC/USD | 2022 | -1.31% | -24.60% | -64.08% | 109 | 31 |
| BTC/USD | 2023 | -32.61% | -6.52% | 156.22% | 205 | 77 |
| BTC/USD | 2024 | -20.04% | 14.14% | 118.33% | 186 | 72 |
| BTC/USD | 2025 | -45.44% | -20.10% | -5.56% | 149 | 58 |
| BTC/USD | **full** | 66.25% | 3,350.39% | 71,621.39% | 1976 | 743 |
| ETH/USD | 2022 | 6.47% | -8.24% | -67.44% | 108 | 30 |
| ETH/USD | 2023 | -37.26% | -24.41% | 92.53% | 187 | 83 |
| ETH/USD | 2024 | 37.51% | 27.16% | 45.63% | 138 | 59 |
| ETH/USD | 2025 | 38.00% | 49.24% | -11.13% | 119 | 44 |
| ETH/USD | **full** | 9,588.48% | 236,664.53% | 98,804.33% | 1657 | 644 |
| SOL/USD | 2022 | 16.82% | 28.44% | -94.13% | 85 | 19 |
| SOL/USD | 2023 | 235.10% | 332.46% | 928.59% | 177 | 73 |
| SOL/USD | 2024 | -31.53% | 12.08% | 86.50% | 178 | 71 |
| SOL/USD | 2025 | 10.33% | 30.02% | -33.95% | 119 | 45 |
| SOL/USD | **full** | 1,013.47% | 1,922.28% | 209.30% | 641 | 246 |

**EMA(10,30) wins 12 of 15 windows.** EMA(5,10) takes only BTC 2022, ETH 2022 and ETH 2024, and
two of those are the crash year where any fast exit flatters itself.

### The mechanism is fee drag, not signal quality

Win rates are close (BTC full history: 26.9% for the fast pair vs 29.2% for the slow one), but the
fast pair closes roughly 2.5-3x as many trades to get there:

| Run | Closed trades | Fees paid on a $10,000 start |
|---|---|---|
| BTC/USD 2022 ema(5,10) | 109 | $5,953 |
| BTC/USD 2022 ema(10,30) | 31 | $1,395 |
| BTC/USD 2024 ema(5,10) | 186 | $8,513 |
| BTC/USD 2024 ema(10,30) | 72 | $4,007 |
| ETH/USD 2023 ema(5,10) | 187 | $7,652 |
| ETH/USD 2023 ema(10,30) | 83 | $3,976 |
| SOL/USD 2024 ema(5,10) | 178 | $7,366 |
| SOL/USD 2024 ema(10,30) | 71 | $3,987 |

BTC 2024 on the fast pair burned 85% of starting capital in round-trip costs in a single year. Max
drawdown is worse too — 85.8% vs 54.0% over BTC's full history. The faster pair is not finding worse
trades; it is paying roughly triple for comparable ones.

### Start-date sensitivity

Every window below ends 2025-12-31; only the start moves.

| Symbol | From | EMA(5,10) | EMA(10,30) | Buy & hold | 10,30 vs B&H |
|---|---|---|---|---|---|
| BTC/USD | 2018+ | -76.98% | 162.99% | 526.29% | loses |
| BTC/USD | 2020+ | -79.11% | 63.76% | 1,120.65% | loses |
| BTC/USD | 2022+ | -71.25% | -31.75% | 89.60% | loses |
| ETH/USD | 2018+ | 63.22% | 772.41% | 298.60% | **beats** |
| ETH/USD | 2020+ | 37.25% | 528.55% | 2,206.18% | loses |
| ETH/USD | 2022+ | 26.76% | 35.55% | -19.28% | **beats** |
| SOL/USD | 2018+ | 1,013.47% | 1,922.28% | 209.30% | **beats** |
| SOL/USD | 2020+ | 1,013.47% | 1,922.28% | 209.30% | **beats** |
| SOL/USD | 2022+ | 195.71% | 748.08% | -26.78% | **beats** |

SOL's `2018+` and `2020+` rows are duplicates of its full history (its data begins 2021-06-17), so
they are not independent evidence.

### Key takeaways

1. **EMA(10,30) beats EMA(5,10) in 21 of 24 windows** (12/15 per-year, 9/9 start-date) and has
   lower max drawdown in *every* cell without exception.
2. **EMA(5,10) on BTC loses money over every multi-year window tested** — -76.98%, -79.11%,
   -71.25%. 1,319 closed trades since 2018 at a ~27% win rate is a fee shredder.
3. **The ETH full-history headline is again an artifact of the earliest years.** +236,664% from
   2015 becomes +772% from 2018 and +529% from 2020 — against buy-and-hold's +2,206%, a 4x loss.
   Third independent confirmation that long-window returns must not be quoted without this check.
4. **Neither pair beats buy-and-hold on BTC in any window.** Across all start dates EMA(10,30)
   beats B&H 5 of 9 times, but strip SOL's two duplicate rows and it is 3 of 7, with BTC 0 for 3.
   Wins cluster where buy-and-hold did badly; losses where it did well. Same signature as always.

---

## 2026-08-03 (continued) — New RSI strategy across 1h, 4h and 1d vs EMA(10,30)

**Purpose:** Evaluate the newly added `RSICrossoverStrategy` (commit `56c0445`), which trades RSI
against a simple moving average drawn over the RSI itself — TradingView's built-in RSI indicator
configuration (RSI Length 14, Source Close, MA Type SMA, Length 14). Entry is the state "RSI above
its SMA"; exit is a bearish cross of the same pair. Unlike a 30/70 threshold rule it never fights a
sustained trend, but it also gives up RSI's mean-reversion edge.

Higher-timeframe confirmation uses the strategy's own RSI-vs-SMA reading rather than the shared
`mtf_trend_confirms_buy()`: an RSI strategy has no natural fast/slow price-EMA pair to borrow.

### 1h — far too active

| Symbol | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| BTC/USD RSI | -59.53% | -18.86% | -31.61% | -47.09% |
| BTC/USD EMA(10,30) | -24.60% | -6.52% | 14.14% | -20.10% |
| ETH/USD RSI | -30.12% | -4.04% | -5.23% | 46.79% |
| ETH/USD EMA(10,30) | -8.24% | -24.41% | 27.16% | 49.24% |
| SOL/USD RSI | 68.59% | 238.39% | -1.90% | 22.52% |
| SOL/USD EMA(10,30) | 28.44% | 332.46% | 12.08% | 30.02% |

RSI closes ~250 trades a year here and loses to EMA(10,30) in 9 of 12 windows. SOL/USD 2024 alone
paid **$12,935 in fees on a $10,000 account** (263 closed trades) to return -1.90%.

> **Superseded for `4h`:** these `4h` rows were produced when `4h` confirmed against `1d`+`1w`.
> The `1w` trend screen was dropped on 2026-08-04 (see the entry below), which changes every `4h`
> number here. The `1h` and `1d` rows are unaffected.

### 4h and 1d — turnover falls ~30x and the ranking flips

| TF | Symbol | Window | RSI | EMA(10,30) | Buy & hold | RSI closed | EMA closed | RSI maxDD | EMA maxDD |
|---|---|---|---|---|---|---|---|---|---|
| 4h | BTC/USD | 2022 | 2.93% | 0.00% | -64.15% | 54 | 0 | 16.2% | 0.0% |
| 4h | BTC/USD | 2023 | 53.78% | 14.82% | 154.95% | 58 | 22 | 14.1% | 20.5% |
| 4h | BTC/USD | 2024 | 22.61% | 65.11% | 118.48% | 52 | 23 | 15.5% | 20.1% |
| 4h | BTC/USD | 2025 | -3.30% | 7.13% | -5.39% | 48 | 20 | 18.0% | 17.2% |
| 4h | BTC/USD | **full** | 6,254.51% | 15,341.56% | 71,621.39% | 658 | 183 | 22.3% | 43.9% |
| 4h | ETH/USD | 2022 | 5.85% | 0.00% | -67.52% | 59 | 0 | 17.4% | 0.0% |
| 4h | ETH/USD | 2023 | 9.32% | -9.51% | 91.08% | 58 | 20 | 19.3% | 24.9% |
| 4h | ETH/USD | 2024 | 27.26% | 67.76% | 46.15% | 47 | 13 | 16.1% | 20.0% |
| 4h | ETH/USD | 2025 | 86.15% | 20.51% | -10.99% | 32 | 10 | 8.2% | 22.2% |
| 4h | ETH/USD | **full** | 63,534.87% | 26,585.29% | 98,804.33% | 485 | 155 | 26.2% | 52.0% |
| 4h | SOL/USD | 2022 | -14.21% | 0.00% | -94.26% | 40 | 0 | 30.2% | 0.0% |
| 4h | SOL/USD | 2023 | 701.32% | 185.53% | 909.73% | 75 | 7 | 20.1% | 25.1% |
| 4h | SOL/USD | 2024 | 1.86% | 37.79% | 86.36% | 42 | 24 | 16.9% | 33.2% |
| 4h | SOL/USD | 2025 | 89.78% | 3.14% | -33.50% | 50 | 11 | 13.2% | 23.0% |
| 4h | SOL/USD | **full** | 1,591.85% | 264.96% | 209.30% | 208 | 43 | 30.2% | 43.7% |
| 1d | BTC/USD | 2022 | 0.00% | 0.00% | -64.19% | 0 | 0 | 0.0% | 0.0% |
| 1d | BTC/USD | 2023 | 57.68% | 52.53% | 155.54% | 13 | 1 | 9.3% | 8.0% |
| 1d | BTC/USD | 2024 | 18.28% | 70.61% | 120.95% | 12 | 5 | 27.9% | 31.4% |
| 1d | BTC/USD | 2025 | -9.34% | 2.38% | -6.27% | 9 | 5 | 11.8% | 20.0% |
| 1d | BTC/USD | **full** | 21,016.07% | 13,653.28% | 71,621.39% | 116 | 34 | 27.9% | 48.9% |
| 1d | ETH/USD | 2022 | -2.16% | 0.00% | -67.49% | 4 | 0 | 8.8% | 0.0% |
| 1d | ETH/USD | 2023 | 0.02% | 13.02% | 90.96% | 17 | 0 | 15.0% | 7.7% |
| 1d | ETH/USD | 2024 | 28.93% | -2.73% | 46.07% | 10 | 5 | 16.6% | 40.3% |
| 1d | ETH/USD | 2025 | 43.77% | 18.57% | -10.99% | 8 | 2 | 14.7% | 27.2% |
| 1d | ETH/USD | **full** | 13,759.90% | 46,899.35% | 98,804.33% | 109 | 26 | 36.2% | 48.9% |
| 1d | SOL/USD | 2022 | 0.00% | 0.00% | -94.14% | 0 | 0 | 0.0% | 0.0% |
| 1d | SOL/USD | 2023 | 174.18% | 64.80% | 920.86% | 22 | 0 | 24.9% | 15.9% |
| 1d | SOL/USD | 2024 | 28.37% | 37.65% | 85.72% | 6 | 6 | 24.7% | 53.6% |
| 1d | SOL/USD | 2025 | 20.14% | -28.24% | -34.14% | 7 | 4 | 20.1% | 34.6% |
| 1d | SOL/USD | **full** | 447.96% | 13.33% | 209.30% | 40 | 12 | 39.5% | 57.7% |

**Head-to-head across these 30 cells: RSI 16, EMA(10,30) 12, 2 ties** — a reversal of the 1h
result, where RSI won only 3 of 12.

### Key takeaways

1. **Fee drag was the entire problem.** RSI's annual cost on a $10,000 account falls from ~$7-13k
   at `1h` to ~$2-4k at `4h` to ~$400-900 at `1d`. The signal was never the issue; the turnover was.
   `4h` looks like the sweet spot — RSI is positive in 11 of 15 `4h` cells versus 4 of 12 at `1h`.
2. **RSI's clearest advantage is that it trades at all.** EMA(10,30) produced **zero trades in 3 of
   15 `4h` cells and 5 of 15 `1d` cells** — the MTF gate never opened, and all three symbols sat out
   2022 entirely at `4h`. Those 0.00% rows "beat" a -64% to -94% buy-and-hold by doing nothing. RSI
   has no zero-trade cells at `4h`.
3. **RSI has lower max drawdown in every full-history cell**, often by half (ETH `4h`: 26.2% vs
   52.0%; SOL `1d`: 39.5% vs 57.7%). This is the most consistent result in the comparison — more
   consistent than the returns.
4. **Still no edge over buy-and-hold.** RSI beats B&H 7/15 at `4h` and 6/15 at `1d`; EMA(10,30) 8/15
   and 6/15. Wins remain clustered in the down years. The full-history figures inherit the
   start-date sensitivity demonstrated in the entry above.
5. **A note for anyone tuning the periods:** a saturated RSI generates no entries. On a monotonic
   advance RSI pins at exactly 100, its SMA is also 100, and `trend_is_bullish()` correctly reports
   "not bullish" on equal lines. This surfaced as five failing tests built on unrealistic fixtures.

---

## 2026-08-04 — `4h` entries confirm against `1d` only (dropping the `1w` trend screen)

**Change:** `MTF_CONFIRMATION_MAP["4h"]` went from `("1d", "1w")` to `("1d",)`. Every other entry
timeframe is unchanged, so only `4h` results move; the `1h` numbers below are directly comparable
to the 2026-08-03 entry.

**Why:** a weekly EMA pair turns over very slowly and can stay bearish for weeks after the daily has
already turned, vetoing every `4h` entry through the opening leg of a move. This is the same
"confirmation permanently vetoes a trend" failure documented on 2026-08-02, and here it was severe
enough to produce complete sit-outs: with the `1w` screen, `ema(10,30)` on `4h` closed **zero
trades in all of 2022 on all three symbols**.

### Effect on `4h` — `ema(10,30)`

| Symbol | Window | `1d`+`1w` | `1d` only | Buy & hold | Closed trades |
|---|---|---|---|---|---|
| BTC/USD | 2022 | 0.00% | -34.20% | -64.15% | 0 -> 16 |
| BTC/USD | 2023 | 14.82% | 56.68% | 154.95% | 22 -> 26 |
| BTC/USD | 2024 | 65.11% | 65.11% | 118.48% | 23 -> 23 |
| BTC/USD | 2025 | 7.13% | 7.13% | -5.39% | 20 -> 20 |
| BTC/USD | **full** | 15,341.56% | 105,716.31% | 71,621.39% | 183 -> 238 |
| ETH/USD | 2022 | 0.00% | -16.93% | -67.52% | 0 -> 11 |
| ETH/USD | 2023 | -9.51% | 1.93% | 91.08% | 20 -> 29 |
| ETH/USD | 2024 | 67.76% | 53.58% | 46.15% | 13 -> 19 |
| ETH/USD | 2025 | 20.51% | 22.61% | -10.99% | 10 -> 20 |
| ETH/USD | **full** | 26,585.29% | 342,163.37% | 98,804.33% | 155 -> 222 |
| SOL/USD | 2022 | 0.00% | 12.38% | -94.26% | 0 -> 8 |
| SOL/USD | 2023 | 185.53% | 442.92% | 909.73% | 7 -> 22 |
| SOL/USD | 2024 | 37.79% | 37.79% | 86.36% | 24 -> 24 |
| SOL/USD | 2025 | 3.14% | 24.05% | -33.50% | 11 -> 16 |
| SOL/USD | **full** | 264.96% | 2,615.43% | 209.30% | 43 -> 87 |

**Better in 9 of 15 windows, unchanged in 3, worse in 3.** All three full-history cells improved sharply, and the three zero-trade 2022 cells now trade.

### Effect on `4h` — `rsi(14,14)`

| Symbol | Window | `1d`+`1w` | `1d` only | Buy & hold | Closed trades |
|---|---|---|---|---|---|
| BTC/USD | 2022 | 2.93% | -31.09% | -64.15% | 54 -> 103 |
| BTC/USD | 2023 | 53.78% | 35.97% | 154.95% | 58 -> 88 |
| BTC/USD | 2024 | 22.61% | 23.03% | 118.48% | 52 -> 99 |
| BTC/USD | 2025 | -3.30% | -16.74% | -5.39% | 48 -> 101 |
| BTC/USD | **full** | 6,254.51% | 10,377.56% | 71,621.39% | 658 -> 1272 |
| ETH/USD | 2022 | 5.85% | -8.70% | -67.52% | 59 -> 109 |
| ETH/USD | 2023 | 9.32% | -11.01% | 91.08% | 58 -> 101 |
| ETH/USD | 2024 | 27.26% | 43.08% | 46.15% | 47 -> 102 |
| ETH/USD | 2025 | 86.15% | 37.59% | -10.99% | 32 -> 95 |
| ETH/USD | **full** | 63,534.87% | 340,460.56% | 98,804.33% | 485 -> 1042 |
| SOL/USD | 2022 | -14.21% | 23.28% | -94.26% | 40 -> 98 |
| SOL/USD | 2023 | 701.32% | 512.27% | 909.73% | 75 -> 100 |
| SOL/USD | 2024 | 1.86% | -11.50% | 86.36% | 42 -> 111 |
| SOL/USD | 2025 | 89.78% | 182.56% | -33.50% | 50 -> 87 |
| SOL/USD | **full** | 1,591.85% | 8,762.06% | 209.30% | 208 -> 444 |

**Better in 7 of 15 windows, worse in 8.** The per-year record is mixed, but all three full-history cells improved (BTC 1.7x, ETH 5.4x, SOL 5.5x).

### RSI(14,14) across `1h` and `4h`, all three symbols

`1h` confirms against `4h`+`1d` (unchanged); `4h` confirms against `1d` (this change).

| Symbol | Window | `1h` | `4h` | Buy & hold | `1h` closed | `4h` closed |
|---|---|---|---|---|---|---|
| BTC/USD | 2022 | -59.53% | -31.09% | -64.15% | 274 | 103 |
| BTC/USD | 2023 | -18.86% | 35.97% | 154.95% | 209 | 88 |
| BTC/USD | 2024 | -31.61% | 23.03% | 118.48% | 243 | 99 |
| BTC/USD | 2025 | -47.09% | -16.74% | -5.39% | 260 | 101 |
| BTC/USD | **full** | -95.55% | 10,377.56% | 71,621.39% | 3019 | 1272 |
| ETH/USD | 2022 | -30.12% | -8.70% | -67.52% | 269 | 109 |
| ETH/USD | 2023 | -4.04% | -11.01% | 91.08% | 218 | 101 |
| ETH/USD | 2024 | -5.23% | 43.08% | 46.15% | 236 | 102 |
| ETH/USD | 2025 | 46.79% | 37.59% | -10.99% | 228 | 95 |
| ETH/USD | **full** | 2,296.06% | 340,460.56% | 98,804.33% | 2520 | 1042 |
| SOL/USD | 2022 | 68.59% | 23.28% | -94.26% | 251 | 98 |
| SOL/USD | 2023 | 238.39% | 512.27% | 909.73% | 244 | 100 |
| SOL/USD | 2024 | -1.90% | -11.50% | 86.36% | 263 | 111 |
| SOL/USD | 2025 | 22.52% | 182.56% | -33.50% | 251 | 87 |
| SOL/USD | **full** | 2,924.05% | 8,762.06% | 209.30% | 1128 | 444 |

**`4h` beats `1h` in 11 of 15 windows.** The gap is turnover: RSI closes roughly 3x as many
trades on `1h` (BTC full history: 3,019 vs 1,272), and at ~0.62% per round trip that compounds
against it. BTC on `1h` ends at -95.55% over full history despite the confirmation gate.

### Start-date sensitivity on the new `4h` ladder

Every window ends 2025-12-31; only the start moves.

| Symbol | From | `rsi(14,14)` | `ema(10,30)` | Buy & hold |
|---|---|---|---|---|
| BTC/USD | 2018+ | 357.07% | 1,435.05% | 526.29% |
| BTC/USD | 2020+ | 149.34% | 846.17% | 1,120.65% |
| BTC/USD | 2022+ | -5.41% | 81.34% | 89.60% |
| ETH/USD | 2018+ | 1,784.23% | 1,787.31% | 298.60% |
| ETH/USD | 2020+ | 1,347.43% | 985.67% | 2,206.18% |
| ETH/USD | 2022+ | 74.34% | 49.19% | -19.28% |
| SOL/USD | 2018+ | 8,762.06% | 2,615.43% | 209.30% |
| SOL/USD | 2020+ | 8,762.06% | 2,615.43% | 209.30% |
| SOL/USD | 2022+ | 2,440.38% | 837.95% | -26.78% |

SOL's `2018+` and `2020+` rows duplicate its full history (data begins 2021-06-17).

### Key takeaways

1. **The change fixes a real defect, not just a number.** The `1w` screen was causing total
   sit-outs — `ema(10,30)` traded zero times in 2022 on all three symbols. SOL 2022 goes 0.00% ->
   +12.38% against a -94% buy-and-hold simply by being allowed to participate.
2. **`ema(10,30)` improves in 9 of 15 `4h` windows and worsens in 3**; RSI is more mixed (7 better,
   8 worse per-year) but improves on every full-history cell.
3. **On full history the new ladder makes `ema(10,30)` beat buy-and-hold on all three symbols at
   once** — the first config in this log to do so. **It does not survive the start-date check:**
   from 2020, BTC returns +846% against buy-and-hold's +1,121% and ETH +986% against +2,206%. That
   is the fourth independent confirmation that full-history headlines in this file must not be
   quoted without this test.
4. **The wins that do survive are in flat-to-down periods.** From 2022, SOL returns +837.95%
   (`ema`) and +2,440.38% (`rsi`) against a -26.78% buy-and-hold, and ETH beats buy-and-hold with
   both strategies. BTC remains the weak spot, losing to buy-and-hold at every start date.
5. **`4h` remains the better timeframe for RSI**, beating `1h` in most windows for the same
   turnover reason established on 2026-08-03.

---

## 2026-08-05 — Stop-losses and a trailing ratchet: 8 widths x 30 windows, all worse than no stop

**What was tested.** Stop-loss enforcement and a one-step trailing ratchet became implementable
this session (until now `stop_loss` was recorded on a position but nothing ever acted on it, and
`Backtester` modelled no stops at all). The question was whether either helps.

**Ratchet definition:** once price reaches TRIGGER above entry, the stop moves once to LOCK above
entry and holds. Tested as `trigger = stop width`, `lock = stop width / 2`.

**Setup:** `4h` entry with `1d` confirmation, three symbols, per-year plus full history, 0.26% fee
+ 0.05% slippage. 240 runs. Baseline is the 2026-08-04 no-stop result, unchanged.

### Summary — 15 windows per arm

| Arm | rsi beats base | rsi avg maxDD | rsi avg win% | ema beats base | ema avg maxDD | ema avg win% |
|---|---|---|---|---|---|---|
| baseline (no stop) | — | 31.4% | 33.0% | — | 31.5% | 32.7% |
| stop 2% | 1/15 | 33.4% | 30.0% | 1/15 | 35.7% | 21.7% |
| stop 2% + ratchet | 3/15 | 33.2% | 44.2% | 1/15 | 40.0% | 44.9% |
| stop 4% | 0/15 | 35.0% | 32.3% | 4/15 | 33.8% | 29.9% |
| stop 4% + ratchet | 0/15 | 36.0% | 36.0% | 1/15 | 36.5% | 42.3% |
| stop 6% | 1/15 | 33.8% | 32.8% | 2/15 | 33.1% | 32.7% |
| stop 6% + ratchet | 1/15 | 32.9% | 34.6% | 2/15 | 35.2% | 40.8% |
| stop 8% | 1/15 | 32.3% | 32.9% | 1/15 | 34.1% | 32.5% |
| stop 8% + ratchet | 2/15 | 33.2% | 33.7% | 1/15 | 34.6% | 37.8% |
| stop 10% | 1/15 | 32.7% | 32.9% | 1/15 | 33.6% | 32.4% |
| stop 10% + ratchet | 3/15 | 32.8% | 33.4% | 1/15 | 35.4% | 35.8% |

### Full-history returns by stop width

Widening the stop helps monotonically - by getting further out of the way. The trend points
straight at "no stop at all", which is another way of saying the stop contributes no edge.

| Stop width | rsi BTC | rsi ETH | rsi SOL | ema BTC | ema ETH | ema SOL |
|---|---|---|---|---|---|---|
| baseline (no stop) | 10,378% | 340,461% | 8,762% | 105,716% | 342,163% | 2,615% |
| stop 2% | 800% | 19,358% | 5,055% | 17,573% | 40,234% | 1,667% |
| stop 4% | 1,009% | 19,605% | 3,695% | 26,510% | 34,387% | 1,848% |
| stop 6% | 2,397% | 42,600% | 4,022% | 43,007% | 41,373% | 1,844% |
| stop 8% | 3,311% | 58,673% | 5,940% | 41,732% | 43,201% | 1,766% |
| stop 10% | 3,897% | 76,705% | 5,613% | 58,384% | 53,935% | 1,885% |

### Why stops lose here

1. **The strategies already have an exit.** Both sell on an indicator turn, so a price stop can
   only fire *earlier* - it exclusively converts trades the strategy would have held into early
   exits. On this data the held versions were better on average.
2. **Each stop-out buys another round trip.** Closing frees capital to re-enter, and every
   re-entry pays ~0.62% in fees and slippage. Closed-trade counts rise as stops tighten:
   `ema(10,30)` goes from 781 closed with no stop to 1,522 at a 2% stop and 2,729 with the 2%
   ratchet.
3. **Drawdown does not improve, which was the whole rationale.** The best arm on either strategy
   is `rsi` with an 8% stop at 32.3% average max drawdown, against the no-stop baseline's 31.4%.
   Every other arm is worse; `ema` with the 2% ratchet reaches 40.0%.

### The ratchet's win rate is an illusion

The ratchet raises win rate sharply - `rsi` 33.0% -> 44.2%, `ema` 32.7% -> 44.9% - while lowering
returns in nearly every window. It converts large winners into small ones capped at the lock level.
More trades close green; less money is made. **A win-rate improvement with a return decline is the
signature of truncating winners, and it is worth treating as a warning rather than a result.**
The ratchet is worse than the plain stop it modifies at every width, on both strategies.

### Outcome

Shipped, and **disabled by default** (`STOP_ENFORCEMENT=off`). The machinery is worth having - stops
are now genuinely enforceable, poll and native mechanisms are mutually exclusive by construction,
and `Backtester` can measure any future variant - but no configuration tested here is worth
enabling. All backtest stop parameters default to 0, so every earlier entry in this file remains
valid.

**Caveats on the negative result:** one timeframe (`4h`), two strategies, and the ratchet's
trigger/lock pair was tied to the stop width rather than swept independently. A different pairing
might behave differently. Given the direction is consistent across 8 widths and 30 windows, that
would need a specific reason to pursue.

---

## 2026-08-09 — 15m RSI with no MTF confirmation, plain and with a 1% take-profit: total account loss in every window

**What was tested.** A day-trading variant: `rsi_m0` (RSI(14) vs its own SMA(14), the plain
crossover exit) on `15m` with the multi-timeframe confirmation gate turned off (`no_mtf`), so entry
depends only on the 15m candles - no `1h`/`4h` agreement required. Two arms: the bare strategy, and
the same thing with a full-position take-profit at +1% layered on top (`stops.target=1`). No new
strategy class was needed - `RSICrossoverStrategy` already skips confirmation when it isn't given
higher-timeframe candles; `tools/sweep.py`'s existing `no_mtf` flag does exactly this.

**Setup:** 3 symbols x 5 calendar years (2021-2025) x 2 arms = 30 runs, plus a `15m` **with** MTF
arm for comparison and a `1h`-with-MTF control arm to validate the harness before trusting anything
below. `full` was not run at `15m` - BTC alone is ~385k `15m` candles and, per the 2026-08-02 entry,
the backtester's per-bar cost grows superlinearly at that size.
Config: `tools/examples/rsi_15m_tp1_no_mtf.json`. Command: `uv run python tools/sweep.py
rsi_15m_tp1_no_mtf tools/examples/rsi_15m_tp1_no_mtf.json`.

**Control arm caught a real change, not a bug.** The `1h`-with-MTF control (SOL/USD, 2024) returned
+103.50% (201 closed) against this file's logged baseline of -1.90% (263 closed, $12,935 fees) from
2026-08-03. Confirmed by direct comparison (monkeypatching the new check back to always-true
reproduces -1.90%/263 exactly) that the cause is the RSI-slope confirmation added to
`mtf_rsi_confirms_buy()` earlier the same session (guards against confirming a BUY off a higher
timeframe that's above its SMA but already declining) - not a harness defect. Every MTF-confirmed
RSI baseline elsewhere in this file predates that change and is no longer reproducible as logged.

### Results: `no_mtf` and `no_mtf` + 1% take-profit

**Every one of the 30 windows returned -100% (or -99.99%) and none differ from any other in kind -
this was total, not partial, account loss.** Representative rows (fees on a $10,000 start):

| Arm | Symbol | Window | Return | Closed trades | Fees |
|---|---|---|---|---|---|
| no_mtf | BTC/USD | 2021 | -100.00% | 2,998 | $9,977 |
| no_mtf | ETH/USD | 2021 | -100.00% | 2,955 | $13,730 |
| no_mtf | SOL/USD | 2021 | -99.99% | 1,668 | $7,777 |
| no_mtf_tp1 | BTC/USD | 2021 | -100.00% | 3,870 | $8,429 |
| no_mtf_tp1 | ETH/USD | 2021 | -100.00% | 4,205 | $10,553 |
| no_mtf_tp1 | SOL/USD | 2021 | -100.00% | 2,505 | $5,856 |

Fees alone consumed $5,856-$13,730 of the $10,000 starting balance in every single symbol/year,
before counting realized trading losses - full 30-row output in `data/sweeps/rsi_15m_tp1_no_mtf.json`.

**Why:** the MTF gate is this codebase's only throttle on a state-based entry ("buy on every bar RSI
sits above its SMA"). Remove it and the strategy re-evaluates and re-fires on every `15m` bar,
closing 1,700-4,300 trades a year - roughly one round trip every 90-150 minutes, around the clock.
At 0.26% fee + 0.05% slippage per fill that is enough to grind any starting balance to dust well
before the year ends (see the last closed trades in a raw run: position sizes down to
0.000002 SOL). Adding the 1% take-profit made turnover *higher*, not lower, in every case (e.g. BTC
2021: 2,998 -> 3,870 closed) - it adds another automatic exit-then-re-entry cycle on top of an
already-unfiltered entry, accelerating the same fee bleed rather than protecting against it.

For reference, `15m` **with** MTF confirmation (also run, `baseline_15m_mtf` arm) avoids total wipeout
but is still weak and inconsistent - e.g. SOL/USD ranges from +497% (2022) to -59% (2025) - consistent
with every prior finding in this file that `15m` entries are fee-dominated and unreliable even when
filtered.

### Outcome

**Not viable as tested - this is a wipeout result, not a marginal loss, and consistent across all 3
symbols and all 5 years.** Not shipped; no code changes. The MTF gate on `15m` isn't optional
overhead, it's the only thing standing between this entry rule and total fee-driven ruin - any future
`15m` day-trading variant needs either MTF confirmation kept on or some other hard cap on trade
frequency (e.g. a minimum bars-between-entries rule), not just a profit target layered on top.

---

## 2026-08-10 — Re-sweeping `4h` after the RSI-slope confirmation: first strategy in this file to survive the start-date check on every symbol

**Why this run exists.** The RSI-slope confirmation added 2026-08-09 (`ff706bd`) hadn't been
re-swept on `4h` - the only place it had been checked was a `1h` control arm, where it moved
SOL/USD 2024 from -1.90% to +103.50%. Before treating `SOL/USD 4h rsi_m2` (the config the two live
paper bots run) as good enough to consider live, it needed the same full-history + start-date
treatment every other headline number in this file gets.

**Setup:** `tools/examples/margin.json` (control=`rsi_m0`, `m2`, `m5`, all `4h` confirming against
`1d`), 3 symbols, 2022-2025 + full, then a follow-up `tools/examples/margin_4h_startdate.json` for
the `2018+`/`2020+`/`2022+` start-date check. Commands: `uv run python tools/sweep.py
rsi_margin_4h_post_slope tools/examples/margin.json` and `... rsi_margin_4h_startdate
tools/examples/margin_4h_startdate.json`.

**Control arm validated the harness, not just the strategy.** Monkeypatching the slope check back
to always-true reproduced the exact pre-slope baseline (BTC full 10,377.56%/1,272 closed, matching
2026-08-04 exactly) - confirming the difference below is caused by the slope filter alone, not a
data refresh or a sweep bug.

### Full-history `4h`, before vs after the slope confirmation (`rsi(14,14)` / `rsi_m0`)

| Symbol | Pre-slope (2026-08-04) | Post-slope | Multiple | Closed trades (pre → post) |
|---|---|---|---|---|
| BTC/USD | 10,377.56% | 233,587.49% | 22.5x | 1,272 → 1,087 |
| ETH/USD | 340,460.56% | 4,225,942.06% | 12.4x | 1,042 → 908 |
| SOL/USD | 8,762.06% | 53,731.97% | 6.1x | 444 → 382 |

The filter blocked only ~13-14% of entries on each symbol. A change of this size from that small a
change in trade count is a compounding effect, not linear: on 100%-of-balance, all-in/all-out
compounding, removing entries made right as the higher-timeframe (`1d`) RSI was already rolling
over disproportionately removes trades that were about to go badly, and a handful of avoided bad
entries early in a multi-year run changes every subsequent position size downstream.

### Start-date sensitivity - the check that has reversed 4 prior headlines in this file

Every window ends 2025-12-31; only the start moves. `rsi_m2` is what the two live paper bots run.

| Symbol | Start | `rsi_m0` | `rsi_m2` | Buy & hold |
|---|---|---|---|---|
| BTC/USD | 2018+ | 4,005.72% | 7,789.41% | 526.29% |
| BTC/USD | 2020+ | 1,201.42% | 2,041.90% | 1,120.65% |
| BTC/USD | 2022+ | 214.75% | 328.25% | 89.60% |
| ETH/USD | 2018+ | 10,871.13% | 38,544.99% | 298.60% |
| ETH/USD | 2020+ | 4,610.38% | 11,384.59% | 2,206.18% |
| ETH/USD | 2022+ | 281.30% | 519.49% | -19.28% |
| SOL/USD | 2018+/2020+ | 53,731.97% | 135,437.78% | 209.30% |
| SOL/USD | 2022+ | 12,042.89% | 25,136.55% | -26.78% |

**Beats buy-and-hold in all 9 symbol/start-date cells, for both `rsi_m0` and `rsi_m2`.** This is
the first strategy logged in this file to clear that bar - the 2026-08-04 entry explicitly
documented `rsi(14,14)` *failing* this exact check (BTC lost to buy-and-hold at every start date;
ETH lost from 2020). The slope filter is what closed that gap: BTC 2020+ went from 149.34% (losing
to buy-and-hold's 1,120.65%) to 2,041.90% on `rsi_m2` (beating it).

**`rsi_m2` beats `rsi_m0` in every cell above**, consistent with the live bots' exit-margin choice.

### Caveats before reading too much into this

1. **Per-year is much less clean than full-history.** `rsi_m2` on BTC/USD: +20.82% (2022), +71.90%
   (2023), +91.36% (2024), +8.50% (2025) against buy-and-hold's -64.15%/154.95%/118.48%/-5.39% -
   **it loses to buy-and-hold in 2023 and 2024**, both strong bull years, and wins are still
   concentrated in the down/choppy years (2022, 2025). The full-history and start-date numbers look
   dominant because compounding rewards *not losing 64% in 2022*, not because every year wins.
2. **These are full-balance, all-in/all-out compounding figures**, same caveat as every other
   number in this file - real execution (partial fills, slippage in fast markets, not always being
   able to enter/exit at the exact bar close) will not reproduce numbers like SOL's 135,437.78%
   literally. Read the multiples over buy-and-hold and the start-date robustness as the finding, not
   the absolute percentages.
3. **One filter, one confirmation timeframe (`1d`), three correlated crypto assets.** All three
   symbols moved in the same direction by a similar mechanism - encouraging, but it is not
   independent confirmation the way a genuinely different asset class would be.
4. **The live order path is untested regardless of this result.** No backtest result changes that;
   see the paper-bot state notes.

### Outcome

Not a code change - this is a re-validation of the config the live paper bots already run
(`rsi_m2`, `4h`, confirms against `1d`). The strategy's statistical case is now meaningfully
stronger than it was a week ago: it's the first to survive the start-date check on every symbol
tested. Raises confidence in the *entry logic*; does not by itself clear the bot for live trading -
the live order-execution path (`OrderExecutor` against Kraken, not the paper simulator) has never
placed a real order and this sweep says nothing about it.

---

## 2026-08-10 (continued) — Partial-position exits: infrastructure, not a strategy result

**What landed.** Every SELL in this codebase used to close 100% of a position, everywhere -
`Signal`, the live `TradingEngine`, and `Backtester`. Added the ability to close a fraction instead,
from two independent places: a strategy's own signal (`Signal.exit_fraction`, 0-1, default 1.0) and
the engine-level take-profit/stop-loss mechanism (`Backtester`'s new `take_profit_exit_pct`/
`stop_loss_exit_pct` constructor params, 0-100, default 100). Both single-shot even when partial - a
fired level clears immediately rather than re-firing on every later bar the price lingers past it,
which would otherwise ladder the remainder down to dust. Full design rationale in the plan this
session produced; not repeated here.

**Default behavior verified byte-for-byte unchanged**, not just by inspection: ran `rsi_m2` `4h`
SOL/USD 2018+ through `scripts/backtest.py` on the code before and after this change (`git stash`
before/after) - both produced the exact same 137,424.35% return, 621 trades, $4,045,300.53 in fees.

**Demonstration run** (not a strategy recommendation - one config, one symbol, no start-date check
run against it): same config with `--take-profit-pct 15 --take-profit-exit-pct 70` (bank 70% of the
position once price is +15% from entry, let the rest ride under the strategy's own exit).

| | No take-profit (baseline) | 15% target, 70% partial exit |
|---|---|---|
| Return | 137,424.35% | 104,199.24% |
| Closed trades | 310 | 359 |
| Win rate | 49.68% | 56.55% |
| Max drawdown | 27.63% | 22.43% |
| Fees | $4,045,300.53 | $3,122,227.22 |

**Same signature as the 2026-08-05 stop-loss finding: win rate up, drawdown down, total return
down.** Banking part of a winner early converts some of the strategy's biggest compounding moves
into smaller, earlier-realized ones - exactly what "let a fraction ride" should do, and exactly why
that entry called a win-rate improvement alongside a return decline "the signature of truncating
winners" rather than a free win. Whether that trade (lower ceiling, lower drawdown) is worth taking
is a strategy question for a future session, not something this one demonstration run settles.

**Outcome:** shipped as opt-in infrastructure (default 100% preserves every existing result).
`RiskManager` and live take-profit enforcement (which does not exist today even at 100%) were
explicitly left untouched - this pass only builds the plumbing to close a fraction, not a new
strategy or tiered-target system on top of it.

---

## 2026-08-10 (continued 2) — `rsi_m2` `4h` SOL/USD partial-take-profit sweep: wide targets beat the no-TP baseline on every metric

**What was tested.** `rsi_m2` (the live bots' config), `4h`, SOL/USD only, take-profit target width
swept at 5/10/15/20/30% with a fixed 70% partial exit at each, against a `control_no_tp` arm
reproducing the exact 2026-08-10 baseline (135,437.78%, 311 closed - confirmed matching before
trusting anything else here). `tools/sweep.py` gained two new `stops` keys this session
(`target_exit_pct`/`stop_exit_pct`) wired straight to the new `Backtester` params, so this sweep also
served as the first real usage of the partial-exit infrastructure added earlier today. Config:
`tools/examples/rsi_m2_4h_partial_tp_sweep.json`, followed by a start-date check on the two
strongest arms: `tools/examples/rsi_m2_4h_partial_tp_startdate.json`.

### Full-history and the widest, most skeptical start-date window

| Arm | Full-history return | Full closed | Full win% | Full maxDD | 2022+ return | 2022+ maxDD |
|---|---|---|---|---|---|---|
| control (no TP) | 135,437.78% | 311 | 49.52% | 27.63% | 25,136.55% | 27.63% |
| tp5, 70% exit | 20,413.59% | 468 | 67.74% | 18.25% | - | - |
| tp10, 70% exit | 58,253.57% | 399 | 60.90% | 22.51% | - | - |
| tp15, 70% exit | 102,692.62% | 360 | 56.39% | 22.43% | - | - |
| **tp20, 70% exit** | **165,282.50%** | 342 | 54.39% | **22.36%** | **33,991.35%** | **22.36%** |
| tp30, 70% exit | 169,871.93% | 323 | 51.39% | 24.63% | 29,847.93% | 24.63% |

**Narrow targets (5-15%) behave exactly like the 2026-08-05 stop-loss finding** - win rate up
sharply, drawdown down, but total return well below the no-TP baseline. Banking 70% of the position
every time a modest move happens converts big compounding winners into small realized ones, same
mechanism as before.

**Wide targets (20-30%) break that pattern - `tp20_e70` beats the no-TP baseline on every metric at
once, in the full-history window and independently at every start date tested (2018+/2020+/2022+
all show the same ranking).** Not just a full-history compounding artifact: at 2022+, the window this
project's start-date check has burned four separate times, `tp20_e70` still shows +33,991% vs
control's +25,136%, 53.82% win rate vs 49.64%, and 22.36% maxDD vs 27.63%. Per-year detail (full
window) tells the same story - `tp20_e70` beats or matches control's return in 3 of 4 years (loses
only in 2025: 265.34% vs 313.44%) and **improves max drawdown in all 4 years without exception**
(e.g. 2023: 22.36% vs 27.63%). `tp30_e70` is even more conservative: in years the wide target never
triggers (2022, 2024) its numbers are identical to control by construction; in years it does trigger
(2023, 2025) every metric improves or ties.

**Why wide beats narrow here, tentatively:** a target set far enough out fires rarely, so most of the
time this is just the unmodified `rsi_m2` baseline - the 70% partial exit only intervenes on the
minority of trades that run unusually hard, banking some of an outsized move rather than truncating
an ordinary one the way a tight target does on nearly every trade. That is a hypothesis from the
shape of the data (trade counts stay close to baseline: 342/323 vs 311, versus 468 at `tp5`), not a
mechanism verified independently here.

### Caveats

1. **One symbol (SOL/USD), one strategy config (`rsi_m2`), one timeframe (`4h`).** Everything else
   tested today for the partial-take-profit feature was SOL-only; BTC/ETH are untested with this
   exact target-width sweep.
2. **These are full-balance, all-in/all-out compounding figures** - same caveat as every number in
   this file. Read "beats the baseline on return, win rate, and drawdown simultaneously, and does so
   at every start date" as the finding, not the six-figure percentages themselves.
3. **Not yet live-actionable.** Live take-profit enforcement (fractional or not) still does not
   exist in `TradingEngine`/`enforce_stops()` - this is a backtest-only result until that's built.

### Outcome (superseded by the cross-symbol extension immediately below)

Not shipped to the live bots (no live enforcement exists yet to ship it to). Worth extending this
exact sweep to BTC/ETH before treating "≈20-30% target, 70% exit" as a real recommendation rather
than a promising SOL-only result. See the next entry - that extension is now done.

---

## 2026-08-10 (continued 3) — Same partial-take-profit sweep extended to BTC and ETH: `tp20_e70` holds up on all three symbols

**What was tested.** The exact same sweep as immediately above (`rsi_m2`, `4h`, target width
5/10/15/20/30% at a fixed 70% partial exit, control arm with no take-profit), run against the
default three-symbol set instead of SOL-only. Same two config files
(`tools/examples/rsi_m2_4h_partial_tp_sweep.json`,
`tools/examples/rsi_m2_4h_partial_tp_startdate.json`), just without the `SWEEP_SYMBOLS` override.

### Full-history, all three symbols

| Symbol | Arm | Return | Closed | Win% | MaxDD |
|---|---|---|---|---|---|
| BTC/USD | control (no TP) | 968,952.41% | 879 | 42.32% | 27.04% |
| BTC/USD | **tp20_e70** | **1,498,194.58%** | 913 | 44.58% | **25.05%** |
| BTC/USD | tp30_e70 | 1,319,788.25% | 888 | 42.91% | 27.04% |
| ETH/USD | control (no TP) | 12,703,157.69% | 735 | 44.90% | 36.25% |
| ETH/USD | **tp20_e70** | **14,363,277.16%** | 791 | 48.93% | **29.35%** |
| ETH/USD | tp30_e70 | 13,982,677.24% | 756 | 46.43% | 29.92% |
| SOL/USD | control (no TP) | 135,437.78% | 311 | 49.52% | 27.63% |
| SOL/USD | **tp20_e70** | **165,282.50%** | 342 | 54.39% | **22.36%** |
| SOL/USD | tp30_e70 | 169,871.93% | 323 | 51.39% | 24.63% |

**`tp20_e70` beats the no-take-profit control on return, win rate, AND max drawdown, on all three
symbols at once.** Not a SOL-only artifact.

### Start-date sensitivity: `tp20_e70` wins in 9 of 9 cells

| Symbol | Start | control (no TP) | tp20_e70 | tp30_e70 |
|---|---|---|---|---|
| BTC/USD | 2018+ | 7,789.41% | **11,210.59%** | 8,579.40% |
| BTC/USD | 2020+ | 2,041.90% | **2,327.31%** | 2,228.03% |
| BTC/USD | 2022+ | 328.25% | **350.74%** | 328.25% (tied - never triggered) |
| ETH/USD | 2018+ | 38,544.99% | **78,543.13%** | 58,386.24% |
| ETH/USD | 2020+ | 11,384.59% | **15,085.86%** | 12,425.55% |
| ETH/USD | 2022+ | 519.49% | **554.86%** | 509.37% (tp30 loses here) |
| SOL/USD | 2018+/2020+ | 135,437.78% | **165,282.50%** | 169,871.93% |
| SOL/USD | 2022+ | 25,136.55% | **33,991.35%** | 29,847.93% |

**`tp20_e70` beats the no-take-profit control at every single one of the 9 symbol/start-date
cells.** `tp30_e70` is close behind but loses once (ETH 2022+, a small -2% relative miss) - `tp20`
is the more robust of the two widths tested.

### The honest nuance: drawdown protection is not uniform across windows

At the tighter, more recent **2022+** window specifically, BTC and ETH's max drawdown was
**identical** between control and both take-profit arms (BTC 24.93% vs 24.93%; ETH 26.88% vs
26.88%) - only return and win rate improved there, not drawdown. The drawdown reduction shows up
clearly in the **full-history** numbers (which include the 2018 and 2022 crashes) but not
necessarily in every shorter recent window. SOL is the exception - it improved drawdown even at
2022+ (27.63% -> 22.36%). Read "improves all three metrics" as a full-history-and-usually,
not an always-every-window, result.

**Per-year detail is also more mixed for ETH than for SOL/BTC** (see the raw sweep output,
`data/sweeps/rsi_m2_4h_partial_tp_sweep_all.json`) - `tp20_e70` loses to control in 2 of ETH's 4
individual years even though it wins on every multi-year and start-date cut. The multi-year
robustness is the finding; a single calendar year is too short a sample to expect a clean sweep.

### Outcome

**This is now a three-symbol, start-date-robust result**, not a SOL-only curiosity - the strongest
backtested case in this project's history for an engine-level protective mechanism improving
return, win rate, and (mostly) drawdown together rather than trading one for another. Live
take-profit enforcement was built later the same day (see the entry below on going live) - this
remained backtest-only at the time this section was written, and now has a live path.

---

## 2026-08-11 — Extending the partial-take-profit sweep to ADA/USD before considering it for live trading

**Why this run exists.** A request to run a live bot on ADA/USD surfaced that ADA had never been
backtested in this project at all - every result above (RSI-slope confirmation, the take-profit
sweep, the start-date checks) covers BTC/ETH/SOL only. Before treating `rsi_m2`/`4h` (with or
without take-profit) as validated for ADA, it needed the same treatment. Data source: Kraken's tick
archive has `ADAUSD.csv`, covering 2018-09-28 through 2025-12-31 - comparable span to ETH's.

**Setup:** identical commands and config files as the BTC/ETH/SOL sweep
(`tools/examples/rsi_m2_4h_partial_tp_sweep.json`, `tools/examples/rsi_m2_4h_partial_tp_startdate.json`),
just `SWEEP_SYMBOLS=ADA/USD`.

### Full-history

| Arm | Return | Closed | Win% | MaxDD |
|---|---|---|---|---|
| control (no TP) | 360,274.95% | 495 | 45.05% | 34.28% |
| tp5_e70 | 47,640.20% | 717 | 62.20% | 28.27% |
| tp10_e70 | 273,433.60% | 614 | 56.19% | 28.50% |
| tp15_e70 | 472,787.13% | 568 | 52.11% | 28.42% |
| **tp20_e70** | **541,176.10%** | 538 | 49.44% | **30.75%** |
| **tp30_e70** | **892,129.62%** | 516 | 47.29% | 34.28% (tied with control) |

Same narrow-vs-wide pattern as every other symbol: `tp5`-`tp15` trade return for a cleaner win-rate/
drawdown improvement; `tp20`/`tp30` recover (and exceed) the no-TP return while still improving win
rate.

### Start-date sensitivity: a more mixed picture than BTC/ETH/SOL

| Start | control | tp20_e70 | tp30_e70 |
|---|---|---|---|
| 2018+ | 360,274.95% | **541,176.10%** | **892,129.62%** |
| 2020+ | **127,119.60%** | 126,355.91% (loses, ~0.6% relative) | **212,985.10%** |
| 2022+ | 3,392.40% | **3,775.77%** | **4,693.83%** |

**`tp20_e70` is not the clean 9-of-9 winner it was on BTC/ETH/SOL - it loses narrowly to the no-TP
control at the 2020+ start on ADA** (essentially a wash, not a meaningful loss, but the first time
this specific config has lost anywhere in this project's start-date testing). `tp20_e70` does still
improve win rate and max drawdown at every ADA start date tested (see raw sweep output,
`data/sweeps/ada_4h_partial_tp_startdate.json`) - the return edge specifically is what's inconsistent
here, not the risk profile. **`tp30_e70` wins on return at all 3 ADA start dates**, more decisively
than `tp20_e70` does, but - unlike on BTC/ETH/SOL - its max drawdown is identical to the no-TP
control at every ADA start date (34.28% exactly, all three), meaning the wider 30% target rarely
fires within these windows on ADA; the return improvement is coming from what it does do, not from
risk reduction.

### Outcome

**ADA is not a clean repeat of the BTC/ETH/SOL finding, but the core `rsi_m2`/`4h` signal still
clearly beats buy-and-hold on ADA** (e.g. 2022+: control alone at +3,392% vs buy-and-hold's -74.57%).
Of the two take-profit widths tested, `tp30_e70` is the more consistent choice for ADA specifically
if a take-profit is used at all - wins on return at every start date - though without the drawdown
benefit seen elsewhere. `tp20_e70` remains a defensible choice (drawdown/win-rate improve
everywhere) if return isn't the only criterion. Neither width is invalidated, but neither is the
unambiguous win it was on the other three symbols either - this is exactly the kind of per-symbol
variation that's easy to miss by assuming a validated config on one asset transfers cleanly to
another, which is why this check was worth doing before any live capital went on ADA.

---

## 2026-08-11 (continued) — Evaluating the RSI scanner's 13 signals for live trading: 4 pass, 1 clean reject

**Why this run exists.** The RSI scanner (`scripts/rsi_scanner.py`) flagged 13 symbols as currently
bullish on `4h`. "Currently bullish" is a snapshot, not evidence of an edge - before considering
real money on any of them, each needed the same `rsi_m2`/`4h` control + start-date treatment ADA got.

**Feasibility first:** of the 13, `CAP`/`CC` have no historical data in the local archive at all
(can't backtest); `BNB`/`ENA`/`TAO` have only 8-18 months (too short for a start-date check to mean
anything). The remaining 8 - `CRV`, `DOGE`, `INJ`, `LINK`, `LTC`, `NEAR`, `SUI`, `TRX` - have 2.5-12
years of history and were swept: `tools/examples/scanner_candidates_rsi_m2.json` (control, 4h,
2022-2025+full) then `tools/examples/scanner_candidates_startdate.json` (2018+/2020+/2022+) on the
7 that showed any edge after the first pass.

### Full-history vs buy-and-hold, and per-year record

| Symbol | History | Full-history return | Buy&hold | Years beating B&H |
|---|---|---|---|---|
| DOGE | 6.0 yr | 1,614,453.85% | 5,483.75% | 3/4 |
| INJ | 4.5 yr | 15,255.09% | -51.38% | 3/4 |
| LINK | 6.3 yr | 46,588.36% | 541.13% | 3/4 |
| LTC | 12.2 yr | 390,330.60% | 2,457.67% | 3/4 |
| CRV | 5.3 yr | 41,573.86% | -76.52% | 2/4 |
| NEAR | 3.5 yr | 1,327.40% | -56.43% | 3/4 (2022 partial) |
| SUI | 2.7 yr | 5,413.70% | -12.36% | 3/3 (short history) |
| **TRX** | 5.9 yr | **754.40%** | **847.02%** | **0/4** |

**TRX is a clean reject** - the only symbol tested this session (including every one from earlier
entries) to lose to buy-and-hold on full-history *and* every individual year. Not dropped for being
merely weak; dropped for failing in every way this file measures a strategy.

### Start-date sensitivity on the 7 that passed the first bar

| Symbol | 2018+ | 2020+ | 2022+ | Distinct cuts? |
|---|---|---|---|---|
| DOGE | 1,614,453.85% (bh 5,483.75%) | 1,658,777.70% (bh 5,734.06%) | 4,373.01% (bh -31.13%) | 3 distinct, all win |
| INJ | 15,255.09% (bh -51.38%) | 15,255.09% (bh -51.38%) | 12,228.33% (bh -49.36%) | 2 distinct, both win |
| LINK | 46,588.36% (bh 541.13%) | 42,273.64% (bh 580.23%) | 1,674.86% (bh -37.58%) | 3 distinct, all win |
| LTC | 25,550.82% (bh -66.69%) | 2,695.38% (bh 86.46%) | 265.80% (bh -47.52%) | 3 distinct, all win (narrowest at 2020+) |
| CRV | 41,573.86% (bh -76.52%) | 41,573.86% (bh -76.52%) | 1,512.54% (bh -93.25%) | 2 distinct, both win |
| NEAR | 1,327.40% (bh -56.43%) | 1,327.40% | 1,327.40% | **0 distinct - data too short to test** |
| SUI | 5,413.70% (bh -12.36%) | 5,413.70% | 5,413.70% | **0 distinct - data too short to test** |

**DOGE, INJ, LINK, LTC beat buy-and-hold at every genuinely distinct start date, with 3/4 per-year
consistency and 4.5-12 years of history each** - the strongest evidence bar in this file, matching
or exceeding what qualified ADA. CRV is real but noisier (2/4 years, a coin-flip). NEAR and SUI are
positive but their "start-date check" is vacuous - too little history for the three cuts to actually
differ, so this isn't real robustness evidence, just one number repeated three times.

### Minimum-order feasibility

All 13 original signals clear Kraken's minimum order size comfortably against this account's actual
position sizing (~$17.91/trade on the live balance at the time, vs $3.46-$11.57 minimums) - sizing
was never the constraint for any of them; data availability was.

### Outcome

**Went live on `DOGE`, `INJ`, `LINK`, `LTC`** alongside the existing ADA bot - same `rsi_m2`/`4h`,
no take-profit (matching what was actually backtested here). `TRX` explicitly rejected. `CRV`/`NEAR`/
`SUI` not launched - real but thinner evidence than the other four; `CAP`/`CC`/`BNB`/`ENA`/`TAO` not
backtestable with current data. See `~/kraken-bot-state/RESTART.md` for the launch details and the
concurrency risk this specific launch surfaced (5 bots sharing one account balance, sized
independently per-process - documented there, not a backtest finding).
