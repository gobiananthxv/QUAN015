# Demo script

Three minutes, five views, one argument. Written to be read aloud.

**Before you start:** run `./run.sh` (or `.\run.ps1`), wait for both servers, open
`http://localhost:5173`, and leave the asset on **NVDA**. The market-data snapshot
is committed, so none of this needs the venue wifi.

---

## The one-line pitch

> "Most backtesting tools tell you what a strategy returned. This one tells you
> whether you should believe the number."

---

## 0:00 — The problem (20s)

*Stay on the Overview tab.*

> "Analysing one asset across data collection, indicators, risk metrics,
> backtesting and regime analysis normally means five or six separate tools. This
> is all of it in one place, over ten years of daily data for three different
> asset classes — gold, Bitcoin and NVIDIA."

Point at the price chart.

> "Log scale, because on a linear axis a decade of NVIDIA compresses the first
> eight years into a flat line. The green bands are when a 50/200 crossover would
> actually have been invested."

---

## 0:20 — Risk (25s)

*Click **Risk**.*

> "Standard quant metrics — Sharpe, Sortino, Calmar, maximum drawdown, and how
> long the drawdown lasted. NVIDIA: 64% a year, but a 66% peak-to-trough loss
> that took 373 days to recover."

Point at the annualisation note.

> "One detail that matters: the annualisation factor is a property of the asset.
> Bitcoin trades 365 days a year, equities 252. Using 252 for crypto understates
> its volatility by about 20%, and most tools get that wrong."

---

## 0:45 — Correlation (25s)

*Click **Correlation**.*

> "Correlation matrix on returns, not prices — two unrelated assets that both go
> up correlate near 1 in price levels, which tells you nothing."

Scroll to the rolling chart.

> "And this is why a single correlation number is misleading. The same pairs swing
> from **−0.47 to +0.62** over the decade. Diversification that works in calm
> markets can vanish exactly when you need it."

---

## 1:10 — Backtest (40s)

*Click **Backtest**.*

> "Five strategies, real execution. Signals are computed on a bar's close and
> filled at the **next bar's open** — so it's structurally impossible to trade on
> a price you couldn't have known. Commission and slippage on both sides."

Point at the two stat blocks.

> "And here's the part I want to be honest about: the crossover returns 6,400%,
> buy-and-hold returns 13,900%. **The strategy loses.**"

Pause.

> "We didn't tune until it won. On an asset that trended this hard, sitting out
> costs more than the crashes you avoid. What the strategy *does* buy you is
> drawdown: 38% instead of 66%. That's a different objective, not a worse one."

Scroll to the trade log.

> "Every trade: entry, exit, size, gross P&L, costs, net. Net equals gross minus
> costs to the cent, and the final equity equals your starting capital plus the
> sum of this column. Two independent accounts that have to agree."

---

## 1:50 — Research (60s) — **the differentiator**

*Click **Research**.*

> "This is the part most backtesting demos don't have. The brief specifically
> warns about over-optimisation, so here's the defence."

Point at the heatmap.

> "Instead of reporting the best parameters, we run the entire grid — every
> combination of fast and slow moving average — and show you the whole surface.
> This one is green almost everywhere: 100% of parameter combinations are
> profitable, median Sharpe 1.07 against a best of 1.23."

Point at the green badge.

> "Robustness 0.88. That's median divided by best. Near 1 means the surface is
> flat and the parameter choice barely matters — the result isn't an artefact of
> tuning."

*Scroll to the regime table — still on NVDA / SMA Crossover.*

> "And *where* it works. Look at the exposure column, not the returns: **16%**
> invested in bear regimes, **97%** in bull. The strategy's value isn't a higher
> return anywhere — it's being absent when the market falls. That's what a trend
> filter is for, now measured instead of asserted."

*Scroll back up. Switch the asset to **GOLD**, then the strategy to
**Mean Reversion**.* Wait ~2s for it to load.

> "Now the same tool on our own weakest strategy."

Point at the red badge.

> "Robustness collapses from 0.88 to **0.10**. Only 56% of parameter combinations
> are even profitable. The tool labels our own strategy **fragile — treat as
> over-fitted**, and we shipped that verdict rather than quietly dropping the
> strategy."

Scroll down to cost sensitivity.

> "Same story here — this one crosses into negative territory at 25 basis points
> per side. An edge that only exists at zero cost isn't an edge."

Point at period stability.

> "And the harshest test: five consecutive windows, signals regenerated in each.
> Most strategies beat buy-and-hold in only one or two of five. A single ten-year
> backtest hides that completely."

---

## 2:50 — Close (15s)

> "496 tests, **fifteen of them causality tests** — nine indicators, five
> strategies and the regime labels, each computed on a truncated series and on
> the full one, asserting the overlap is identical. If appending future data
> changed a past value, the thing leaks the future. Look-ahead bias ruled out
> structurally, not promised. Seven dependencies, no database, no Docker. Runs
> offline."

> "It's a research tool. It won't tell you what to buy. It'll tell you whether
> the backtest you're looking at means anything."

---

## Likely questions

**"Why does buy-and-hold win?"**
Because these three assets trended hard for a decade and the strategies are
long-only, so time out of the market is pure opportunity cost. Momentum *does*
beat the benchmark on Bitcoin — 13,485% against 13,216%, with a shallower
drawdown. The honest summary is that trend-following bought risk reduction here,
not excess return.

**"How do you know there's no look-ahead bias?"**
`test_execution_lag_is_exactly_one_bar` pins `position[t] == sign(signal[t-1])`
across a 12-bar pattern. Fourteen more tests compute each indicator (9), each
strategy (4) and the regime labels on a truncated series and on the full series,
asserting the overlap is byte-identical — if appending future bars changed a past
value, the thing leaks the future. A separate test does the same for the engine's
whole equity curve.

**"Where did the confirmation-band defaults come from?"**
Round numbers, and the Research tab proves it. Across six asset/strategy pairs
the defaults ranked best exactly once — 3rd to 5th of 5 in the other five cases.
A fitted parameter ranks first everywhere. They were chosen because 40% of trades
lasting two bars or fewer is noise trading, which you can identify without
looking at a single return figure.

**"Why not yfinance / Postgres / Docker?"**
We call the Yahoo chart API directly with `requests` — fewer dependencies, no
wrapper-version churn, and failures raise loudly instead of silently caching an
empty frame. ~2,500 rows per asset doesn't need a database. Seven packages total.

**"Can it handle more assets or strategies?"**
Add one entry to `ASSETS` in `config.py`. A strategy is a subclass with one
method and a registry entry — the API, the dashboard dropdowns and the sweeps all
pick it up with no other changes.

**"Profit factor is blank — is that a bug?"**
No, it's `infinity` — that run had no losing trades, so there's nothing to divide
by. It's sent as `null` rather than a made-up large number, because a sentinel
would get plotted as real data.

---

## If something breaks

| Symptom | Cause | Fix |
|:--|:--|:--|
| "Cannot reach the API" | Backend not running | Start it: `cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000` |
| Research tab spins | Normal — it runs ~25 backtests (~300 ms) plus cost and period sweeps | Wait ~2s |
| Blank charts after switching asset | Stale render | Switch tabs and back |
| Fallback | Everything also runs headless | `./verify.sh` prints every result to the terminal |
