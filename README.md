# QMAFIB

**Quantitative Multi-Asset Financial Intelligence & Backtesting Platform**

Most backtesting tools tell you what a strategy returned. This one tells you
whether you should believe the number.

QMAFIB collects ten years of daily market history across three asset classes,
computes the standard quantitative indicators and risk metrics, measures how
cross-asset relationships shift over time, and backtests trading strategies
against a buy-and-hold benchmark with realistic execution costs — then stress-tests
every result for the four ways backtests normally lie.

> ⚠️ **Research tool, not investment advice.** Every figure here is computed from
> historical data. Backtested performance is not a prediction of future returns.

---

## Contents

| | |
|:--|:--|
| [Quick start](#quick-start) | Get it running in one command |
| [What you get](#what-you-get) | The seven views and what each answers |
| [How it works](#how-it-works) | The pipeline, stage by stage |
| [The execution engine](#the-execution-engine-and-what-changed-in-it) | What the engine does, and how it changed in Phase 8 |
| [Where the data comes from](#where-the-data-comes-from) | Why it reads a snapshot, not a live feed |
| [What the platform found](#what-the-platform-found) | Real results, including the unflattering ones |
| [Why you can trust the numbers](#why-you-can-trust-the-numbers) | Bias controls and the decisions behind them |
| [The capability boundary](#the-capability-boundary) | Which five endpoints are fenced, and why only those |
| [Project layout](#project-layout) | Where everything lives |
| [Extending it](#extending-it) | Adding assets and strategies |
| [Reference](#reference) | Endpoints, dependencies, data quality, troubleshooting |
| [DEMO.md](DEMO.md) | A scripted three-minute walkthrough |
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | Phase plan and full decision log |

**Status:** all nine phases complete · **496 tests passing** · all 19
problem-statement requirements delivered.

---

## Quick start

**Requirements:** Python 3.11+ and Node 18+. No database, no Redis, no Docker.

Ten years of market data is committed to the repository, so nothing below needs
an internet connection. See [Where the data comes from](#where-the-data-comes-from).

### One command

**macOS / Linux / Git Bash / WSL**

```bash
./run.sh
```

**Windows PowerShell**

```powershell
.\run.ps1
```

On first run this creates the virtualenv, installs both sets of dependencies
(~30s), and then starts:

| | |
|:--|:--|
| **Dashboard** | **http://localhost:5173** ← open this |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

Press **Ctrl-C** to stop both servers.

> **Use `localhost`, not `127.0.0.1`.** Vite's dev server binds to IPv6, so
> `http://127.0.0.1:5173` will refuse the connection while `http://localhost:5173`
> works.

### Optional: lock down the endpoints that spend money

Nothing below is needed to run the platform, and the defaults are safe on a
machine serving only itself. If you demo on a network, set a token first — see
[the capability boundary](#the-capability-boundary) for what it does and does
not protect.

```bash
cp .env.example .env
```

Then set `QMAFIB_TOKEN` and `VITE_QMAFIB_TOKEN` in `.env` to the same value:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

`GET /health` reports whether the guard is active. It never reports the token.

### Verify everything works

Runs the full test suite plus all five phase-gate scripts, and exits non-zero if
anything fails:

```bash
./verify.sh
```

<details>
<summary><strong>Manual setup</strong> — if you'd rather run the pieces yourself</summary>

#### 1 · Install backend dependencies

**macOS / Linux**

```bash
cd backend && python3 -m venv .venv --system-site-packages && .venv/bin/python -m pip install -r requirements.txt
```

**Windows**

```bash
cd backend && python -m venv .venv --system-site-packages && ./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

`--system-site-packages` reuses any pandas/numpy already installed system-wide.
Drop the flag for full isolation; it just downloads more.

#### 2 · Start the API

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

#### 3 · Start the dashboard, in a second terminal

```bash
npm install --prefix frontend && npm run dev --prefix frontend
```

Point the dashboard at a different API with `VITE_API_URL=http://host:port`.
If you change the dashboard's port, add the new origin to the CORS list in
`backend/app/main.py`.

#### Run the backend on its own

The quant layer never imports FastAPI, so every calculation works headless.
Each script exits non-zero if an invariant breaks — these are the phase gates,
not demos. Substitute `./.venv/Scripts/python.exe` on Windows.

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

```bash
cd backend && .venv/bin/python scripts/bootstrap_data.py
```

```bash
cd backend && .venv/bin/python scripts/analytics_report.py
```

```bash
cd backend && .venv/bin/python scripts/backtest_report.py
```

```bash
cd backend && .venv/bin/python scripts/strategy_report.py
```

```bash
cd backend && .venv/bin/python scripts/robustness_report.py
```

#### Refresh the market data

Re-fetches from Yahoo and overwrites the committed snapshot. The dashboard's
**↻ Refresh data** button and `POST /api/data/refresh` do the same thing.

```bash
cd backend && .venv/bin/python scripts/bootstrap_data.py --refresh
```

</details>

---

## What you get

Seven views. Each answers one question.

### 1 · Overview — *what has this asset done?*

Log-scale price with SMA 50/200 and EMA 50 overlaid, volume, green bands marking
the periods a crossover strategy held a position, and green/red triangles at its
**actual buy and sell fills** — taken from the trade log, not re-derived.

**The chart sets the platform period.** Drag left-to-right directly across it,
and every tab follows. Three things then happen here:

1. **Every metric recomputes for that window** — return, CAGR, volatility,
   Sharpe, Sortino, Calmar, drawdown and its duration, best and worst day. These
   come from the **backend**, not the browser: the quant layer stays the single
   source of truth, so the panel cannot drift from the Risk or Backtest tabs.
2. **Signal periods scale to the window.** A 50/200 crossover yields four fills
   in a decade and none at all in a quarter. Periods track the window
   (50/200 → 20/100 → 10/50 → 5/20 → 3/10 → 2/6), so there are always markers to
   inspect — verified non-empty at every window size from 2,300 bars down to the
   floor, on all three assets. The toolbar states which pair is in use. This is a
   display choice for the chart; parameters are chosen and judged on the Backtest
   and Research tabs.
3. **Markers and shading come from that window's own backtest** — real fills for
   the parameters shown, with a trade table beneath.

Zoom into 2022 on NVIDIA and the panel reads −51.4% return, Sharpe −0.87,
−61.6% drawdown. Zoom to the last six months and it reads +29.0%, Sharpe 1.43.
Same tool, same code, entirely different story.

**Zooming has a floor.** Selections narrower than 20 bars are ignored, and
windows under 60 bars carry an explicit caution. Below about a trading month the
signal warm-up leaves no markers and annualising a handful of daily returns
produces figures that look spectacular and mean nothing — a five-bar window
reports a Sharpe of 23. Refusing the zoom is more honest than rendering that.

Log scale matters: on a linear axis, a decade of NVIDIA compresses its first
eight years into a flat line against the last two.

### 2 · Risk — *how much pain did that involve?*

Sharpe, Sortino, Calmar, volatility, maximum drawdown and how long it lasted —
plus the cumulative return, the underwater drawdown curve, **rolling 1-year
returns** and rolling volatility.

The rolling-return panel is the one that changes minds: buying NVIDIA and
holding a year returned **+305%** at the best entry date and **−55%** at the
worst. A single total-return figure hides that entirely.

### 3 · Correlation — *do these assets actually diversify each other?*

A correlation matrix computed on **returns**, not price levels, plus rolling
correlation with a selectable window.

The rolling view is the point. A single correlation number hides that the same
pair swings from −0.47 to +0.62 over a decade.

### 4 · Backtest — *what would this strategy have done?*

Pick a strategy, edit its parameters, set your capital, commission and slippage,
and run. The **period comes from the Period bar** rather than a control of its
own — the brief's "backtesting periods" *is* the platform period, so there is
one place to set it. Signals are regenerated inside the window, so a sub-period
is a genuine out-of-sample run rather than a trimmed full-history one, and the
benchmark is restricted to the same window. You get the equity curve against buy-and-hold, a full metric
comparison, and a complete trade log — entry, exit, size, gross P&L, costs, net.

Controls cover every item the brief lists under *Realistic Trading Simulation*:
initial capital, **position sizing**, commission, slippage, and — when shorts are
enabled — a borrow fee charged for every bar the short is held.

Picking a strategy that sizes continuously (Volatility Target) reveals two more
controls, because they only mean anything for that kind of strategy:

- **financing bps/yr** — interest on borrowed cash, charged for every bar
  exposure sits above 100%. Institutions fund near 5%; retail margin is often
  8–12%. Raise it until the strategy stops winning: that number tells you what
  rate the result actually depends on, which is the honest way to read any
  levered backtest.
- **no-trade band %** — the smallest change in target size worth trading, as a
  share of the position already held. Without one, a continuously-varying target
  rebalances every single bar and pays commission for the privilege. At 10% on
  NVDA it removes 85% of the rebalances and slightly *improves* the return.

Both the strategy and the benchmark pay the same costs. The benchmark is
**always fully invested**, whatever position size or band the strategy uses: a
yardstick that shrank with your settings would not be a reference point.

### 5 · Compare — *which strategy is best on this asset, in this period?*

All five strategies and the benchmark on one chart, switchable between equity
curve and drawdown, with a ranked table underneath. Every run shares the same
capital, costs and window, so the comparison is like-for-like.

### 6 · Research — *should I believe any of this?*

The part most backtesting tools skip:

- **Parameter surface** — a Sharpe heatmap across the whole parameter grid, not
  just the best cell, with a plain-English robustness verdict
- **Cost sensitivity** — how the result decays as friction rises
- **Period stability** — five consecutive windows, signals regenerated in each
- **Regime attribution** — where the strategy beats the benchmark, and at what
  exposure

---

## Where the data comes from

**The platform reads a committed snapshot, not a live request.** Loading an
asset opens a CSV in `backend/data_snapshot/` — it does not contact Yahoo. The
network is touched in exactly two situations: the file is missing, or someone
explicitly asks for a refresh.

That is a deliberate trade, and the reasons are in priority order:

| Why | Detail |
|:--|:--|
| **Reproducibility** | A backtest must give the same answer today and next week. If the underlying prices moved between runs, every reported figure would drift and the tests asserting exact values would fail daily. |
| **Availability** | The platform works with no internet connection at all. |
| **Speed** | ~14 ms from disk against ~500 ms over the network — and the Research tab runs dozens of backtests per click. |
| **Test integrity** | 496 tests run offline in about a minute instead of hammering a provider. |

It is a *snapshot*, not a cache: there is no TTL, nothing expires, and nothing
refreshes on a timer. To move the baseline forward, either press **↻ Refresh
data** in the dashboard or call `POST /api/data/refresh`; the CLI equivalent is
`scripts/bootstrap_data.py --refresh`. The dashboard always shows the snapshot's
date in the bar under the tabs, so you can see how current it is.

---

## How it works

Nine stages. Each reads only from the stage above it, so any stage can be run,
tested or replaced on its own.

### Data

| # | Stage | Entry point | What happens |
|:--|:--|:--|:--|
| 1 | **Ingest** | `sources.fetch_ohlcv(key)` | Yahoo chart API with retry and backoff. Split and dividend adjustment applied across all four OHLC fields. |
| 2 | **Validate** | `validate.validate_ohlcv(df, key)` | OHLC invariants repaired, null and non-positive closes dropped, duplicates removed, index sorted, gaps counted. Returns a quality report. |
| 3 | **Cache** | `store.load_asset(key)`<br>`store.load_panel(keys)` | Committed CSV cache — the platform runs offline. `load_panel` aligns assets onto a common trading calendar. |

### Analytics

These three run independently off the cache and never touch each other.

| # | Stage | Entry point | Produces |
|:--|:--|:--|:--|
| 4a | **Indicators** | `compute_indicators(df)` | SMA, EMA, RSI, MACD, Bollinger (+ z-score), ATR, ROC |
| 4b | **Metrics** | `summarise(returns, ann_factor)` | Returns, volatility, Sharpe, Sortino, Calmar, max drawdown + duration |
| 4c | **Correlation** | `correlation_matrix()`<br>`rolling_correlation(a, b)` | Static matrix, covariance, rolling pairwise correlation |

### Backtesting

| # | Stage | Entry point | What happens |
|:--|:--|:--|:--|
| 5 | **Signals** | `strategy.generate_signals(df)` | Target *exposure* at each bar's **close**: `1.0` fully invested, `0.5` half, `1.5` half again borrowed, `0` flat, negative short |
| 6 | **Execute** | `engine.run_backtest(...)`<br>`engine.buy_and_hold(...)` | Lags signals one bar, fills at the next open ± slippage, charges commission both sides, sizes to the target from current equity, charges borrow on shorts and interest on borrowed cash, marks to market every close |

Stage 6 returns a `BacktestResult` carrying the equity curve, per-bar position
and a full trade log.

### Research, API, dashboard

| # | Stage | Entry point | Answers |
|:--|:--|:--|:--|
| 7a | **Parameter sweep** | `parameter_sweep(...)`<br>`plateau_report(...)` | Does this survive changing the parameters, or is it one lucky cell? |
| 7b | **Cost sweep** | `cost_sweep(...)` | Does the edge survive realistic friction? |
| 7c | **Period sweep** | `period_sweep(...)` | Is this an edge, or one good episode? |
| 7d | **Regime attribution** | `regime_attribution(...)` | *Where* does it beat the benchmark — and at what exposure? |
| 8 | **Serve** | `uvicorn app.main:app` | 14 endpoints; `inf`/`NaN` leave as `null` |
| 9 | **Visualise** | `npm run dev --prefix frontend` | React + Vite + TypeScript, seven views |

### The one contract everything depends on

```
position[t] == signal[t-1],  filled at open[t]
```

A signal derived from bar *t*'s close cannot be acted on until bar *t+1* opens.
Every backtest number shifts if this changes, so it is pinned by a dedicated
test (`test_execution_lag_is_exactly_one_bar`) rather than left to convention.

The signal is a **target exposure**, not a direction, so the engine sizes to it
literally rather than taking its sign. The four directional strategies only ever
emit `-1`, `0` or `1`, which is the special case; Volatility Target emits
anything between `0` and its cap.

### The execution engine, and what changed in it

The engine was rewritten in Phase 8 to size positions continuously. This is the
single largest change to the core of the platform, so it is worth setting out
what moved, what did not, and why it was worth doing.

#### Before: a switch

The old engine took the **sign** of a signal and traded a fixed fraction of
equity on it:

```python
tgt = np.sign(target)              # -1, 0 or +1 — nothing else survives
budget = cash * cfg.position_pct   # one number, fixed for the whole run
size = budget / (fill * (1 + comm_rate))
```

Two consequences followed from those three lines:

1. **A strategy could only be all-in or all-out.** `sign()` discards magnitude,
   so a strategy asking for 60% exposure and one asking for 200% were executed
   identically.
2. **Position size was an account setting, not a decision.** `position_pct` was
   chosen once, in the config, and never varied. A strategy could not reduce
   size going into a turbulent month and restore it afterwards, because it had
   no way to say so.

#### After: a dial

A signal is now a **target exposure** — a signed real number the engine sizes to
literally, from equity marked at the current bar's open:

```python
tgt = target.to_numpy() * cfg.position_pct   # magnitude preserved
equity_now = cash + pos * ref                # sized from equity, not cash
want = desired * equity_now / (fill * (1 + comm_rate))
qty  = want - pos                            # trade the difference, not the whole position
```

| | Old engine | New engine |
|:--|:--|:--|
| Signal alphabet | `{-1, 0, 1}` | any real number |
| Position size | `position_pct`, fixed for the run | decided per bar by the strategy |
| Changing size | close and reopen | trade the difference |
| Leverage | not expressible | exposure > 1.0, financed per bar |
| A "trade" | one entry, one exit | a span from leaving 0 to returning, with rebalances inside it |
| Cost model | commission, slippage, short borrow | + interest on borrowed cash |
| Turnover control | none | `no_trade_band` |

#### Why it was worth doing

Because **every technique that actually manages risk is a sizing technique.**
Volatility targeting, risk parity, Kelly sizing, drawdown control — none of them
are about *whether* to be in the market, all of them are about *how much*. Four
strategies answering "am I in or out?" is a timing platform. The brief asks for a
quantitative one, and an engine that cannot vary size cannot express the
quantitative part.

The evidence that this was a real gap rather than a theoretical one: the first
strategy built on it, [Volatility Target](#does-any-of-it-survive-scrutiny),
scores the **highest robustness in the project** — 0.94 on NVDA, 0.92 on BTC,
0.83 on GOLD. It holds three assets whose natural volatilities are 50%, 17% and
67% at a common 25–31%, which is the whole point of it. None of that was
expressible a phase earlier.

#### How a bar is processed now

Every bar runs the same six steps, in this order:

| Step | What happens | Why it is there |
|:--|:--|:--|
| 1 | Read the target the strategy set on the **previous** bar | The look-ahead guard, unchanged |
| 2 | Decide whether it is worth trading (`no_trade_band`) | A continuous target would otherwise rebalance every bar and pay commission for it |
| 3 | Close out fully if going flat or flipping sign | Exits and flips are decisions, never suppressed by the band |
| 4 | Size to the target and trade the **difference** | Where the old engine closed and reopened |
| 5 | Charge carry: borrow on shorts, interest on negative cash | A levered position that paid nothing to be levered would be fiction |
| 6 | Mark to market at the close | Unchanged |

Step 4 hides one subtlety worth naming. The fill price depends on which way you
trade, and how far you trade depends on the fill — a circular dependency. The
engine resolves it by computing the target against *both* the buy fill and the
sell fill and keeping whichever is self-consistent. Guessing the direction first
is what the original implementation did, and it was wrong on 1 leg in 59 (GOLD),
64 (BTC) and 106 (NVDA) — and on **zero** legs once a 10% no-trade band was
switched on, because the band removes exactly the small adjustments where the
commission term can flip the sign. A banded run alone would never have exposed
it. See [the bug it caused](#the-identity-that-keeps-it-honest).

#### What deliberately did not change

`{-1, 0, 1}` is a subset of the reals, so the four directional strategies take
the identical path through the new code. This was the safety argument for
attempting the rewrite at all, and it is checked rather than assumed:

> **All 318 pre-existing tests passed unchanged after the rewrite** — including
> the hand-computed trade arithmetic, the execution-lag test and the fourteen
> causality tests. Not one assertion was relaxed to accommodate the new engine.

A separate test asserts the property directly: run a constant `1.0` signal over
real data and every bar's position must be in `{0, 1}` with zero rebalances.

#### What it costs

Honest ledger, because the change was not free:

- **"Trade" means something wider now.** A vol-targeted position may never close;
  it is one open trade with 362 rebalances. Trade-count, win-rate and
  profit-factor are computed over *closed* trades and so read `0`, `—`, `—` for
  such a strategy. The dashboard shows rebalances, average size and peak size
  instead, rather than presenting a 0% win rate that means "nothing has closed
  yet" as though it meant "it lost every trade".
- **Two more knobs to defend.** `financing_bps_annual` and `no_trade_band` are
  both live inputs on the Backtest tab, because a levered result is only as good
  as the rate you can borrow at, and a continuous strategy's turnover is only as
  good as the band that controls it.
- **Entry-price arithmetic no longer describes a trade.** Buy 100 at 100, add 100
  at 50, sell 200 at 80 — no pair of entry and exit prices produces the right
  answer. Each trade therefore carries a shadow cash account kept at unslipped
  reference prices, which *is* the gross P&L once the position is flat.

#### The identity that keeps it honest

```
final_equity == initial_capital + Σ net_pnl,  exactly
```

Every leg of every trade must reconcile: commission and slippage recorded on the
trade have to equal the cash the engine actually moved. This is checked on live
data by `strategy_report.py` and by a regression test, and **it caught a real bug
the unit tests missed** — the fill-direction error described above, which
credited slippage to the trade instead of charging it. It showed up as equity
drifting from the trade log by 0.001% over a decade: far too small to notice by
eye, impossible to hide from an exact identity.

That is the argument for keeping the loop explicit rather than vectorising it.
A `position × returns` shortcut produces an equity curve nobody can audit; this
one produces a trade log whose every line has to add up, and when it does not,
something says so.

---

## What the platform found

### Coverage

Three asset classes on purpose — the correlation and regime analysis is only
interesting because they behave differently.

| Asset | Ticker | Class | Rows | Range | Annualisation |
|:--|:--|:--|--:|:--|--:|
| Gold Futures | `GC=F` | Commodity | 2,514 | 2016-09-19 → 2026-09-18 | 252 |
| Bitcoin | `BTC-USD` | Crypto | 3,653 | 2016-09-19 → 2026-09-19 | 365 |
| NVIDIA | `NVDA` | Equity | 2,514 | 2016-09-19 → 2026-09-18 | 252 |

Aligned cross-asset panel: **2,511 common trading days.**

### Buy-and-hold risk and return

| Asset | Total | CAGR | Volatility | Sharpe | Max DD | Longest DD |
|:--|--:|--:|--:|--:|--:|--:|
| GOLD | 236.9% | 12.95% | 16.95% | 0.69 | −24.9% | 836 d |
| BTC | 13,333% | 63.17% | 66.81% | 1.04 | −83.4% | 1,079 d |
| NVDA | 14,130% | 64.37% | 50.04% | 1.20 | −66.3% | 373 d |

### Correlation is not a constant

Full-sample daily-return correlation is low across every pair — GOLD~BTC 0.10,
GOLD~NVDA 0.04, BTC~NVDA 0.22. But the rolling 90-day figure swings from **−0.47
to +0.62**. Diversification that holds in calm markets can disappear exactly
when it is needed.

### Strategy vs benchmark

All five strategies, 10 bps commission and 5 bps slippage per side, against
buy-and-hold paying the same entry cost, with a 10% no-trade band.

The **Actions** column counts round-trip trades for the four directional
strategies. Volatility Target is marked `*` because it never closes a position —
it only resizes one — so the comparable figure is its rebalance count. Zero
trades and 552 rebalances is not a quiet row; it is a different kind of
strategy.

**GOLD**

| Strategy | Total | Sharpe | Max DD | Trades | Exposure |
|:--|--:|--:|--:|--:|--:|
| SMA Crossover | 136.7% | 0.52 | −30.6% | 7 | 70% |
| EMA Trend | 104.6% | 0.44 | −27.9% | 33 | 61% |
| Momentum | 202.6% | 0.69 | **−21.0%** | 6 | 70% |
| Mean Reversion | 18.2% | −0.00 | −10.6% | 38 | 20% |
| Volatility Target | 325.0% | 0.63 | −41.9% | 209* | 99% |
| **Buy & Hold** | 236.3% | **0.69** | −24.9% | — | 100% |

**BTC**

| Strategy | Total | Sharpe | Max DD | Trades | Exposure |
|:--|--:|--:|--:|--:|--:|
| SMA Crossover | 4,466% | 0.94 | −69.3% | 9 | 53% |
| EMA Trend | 8,621% | 1.13 | −61.2% | 61 | 53% |
| **Momentum** | **13,584%** | **1.16** | −64.3% | 18 | 57% |
| Mean Reversion | −50.8% | −0.03 | −81.0% | 54 | 23% |
| Volatility Target | 1,731% | 1.02 | **−48.8%** | 552* | 99% |
| Buy & Hold | 13,312% | 1.04 | −83.4% | — | 100% |

**NVDA**

| Strategy | Total | Sharpe | Max DD | Trades | Exposure |
|:--|--:|--:|--:|--:|--:|
| SMA Crossover | 6,409% | 1.18 | −37.6% | 3 | 74% |
| EMA Trend | 1,306% | 0.85 | −45.9% | 52 | 66% |
| Momentum | 5,296% | 1.16 | −39.7% | 14 | 76% |
| Mean Reversion | 248.4% | 0.53 | −55.4% | 42 | 18% |
| Volatility Target | 2,985% | **1.24** | **−36.6%** | 362* | 99% |
| **Buy & Hold** | **13,947%** | 1.20 | −66.3% | — | 100% |

### Reading those tables honestly

**Buy-and-hold wins on return in two of three assets.** We report that as-is
rather than tuning until the strategies win. On assets that trended this hard
for a decade, sitting out of the market costs more than the crashes it avoids.

**Every strategy reduced drawdown on BTC and NVDA.** NVDA's SMA crossover gives
up half the return but cuts the worst drawdown from −66% to −38%. That is a
different objective, not a worse one.

**One genuine winner: Momentum on BTC** — 13,584% against the benchmark's
13,312%, with a higher Sharpe and a shallower drawdown, in 18 trades.

**Volatility Target is not trying to win the return column.** Read the
volatility instead: buy-and-hold runs at 50% / 17% / 67% on NVDA, GOLD and BTC,
and vol targeting brings all three to 25–31%. That is the output — three assets
with utterly different temperaments held at one risk level. It costs return on
NVDA and BTC, buys the best Sharpe on the board on NVDA (1.24 vs 1.20), and on
gold it does the opposite of what the name suggests: gold is *quieter* than the
25% target, so the strategy levers up to an average of 1.67× and takes a −41.9%
drawdown for a worse Sharpe than simply owning the metal. A risk tool pointed at
a low-risk asset becomes a risk *amplifier*, which is worth seeing once.

**Mean reversion lost money on BTC** (−50.8%). Buying dips works until the dip
keeps going. It loses at zero cost too (−42.1%), so this is the rule failing,
not friction.

### Does any of it survive scrutiny?

Sharpe across a wide parameter grid, summarised as `robustness` = median ÷ best.
Near 1.0 means the surface is flat and the parameter choice barely matters; near
0 means one cell carries the whole result.

| Strategy | GOLD | BTC | NVDA | Verdict |
|:--|--:|--:|--:|:--|
| SMA Crossover | 0.84 | 0.88 | 0.88 | robust — 100% of cells positive on all three |
| EMA Trend | 0.58 | 0.91 | 0.85 | robust on BTC/NVDA, moderate on gold |
| Momentum | 0.82 | 0.90 | 0.89 | robust across the board |
| Mean Reversion | **0.10** | **0.24** | 0.63 | **fragile — treat as over-fitted** |
| Volatility Target | 0.83 | **0.92** | **0.94** | the flattest surface in the project |

**The tool flags our own weakest strategy.** Mean Reversion's headline numbers
come from a handful of grid cells, consistent with it losing money on BTC.

**Volatility Target scores highest, and the reason is structural rather than
lucky.** Sweeping `target_vol` across a 4× range moves Sharpe by less than 0.06
on NVDA while return and drawdown move enormously. A flat surface like that is
what a real risk-scaling relationship looks like — and it also means the
parameter cannot be optimised in any useful sense. You are choosing how much
risk you want, not finding a better setting.

**Period stability is the harshest test, and most strategies fail it.** Across
five consecutive windows with signals regenerated in each, strategies beat
buy-and-hold in only 1–2 windows of 5. NVDA's SMA crossover ends the 2022–2024
window with **30% of the wealth** buy-and-hold produced — being out of the market
during the AI run was ruinous. One decade-long backtest hides that completely.

Excess is reported **geometrically** — `(1+strategy)/(1+benchmark) − 1` — not as
a difference of total returns. That same window's arithmetic excess reads −639%,
which sounds like losing six times your money when the strategy actually *gained*
177%. The geometric figure is bounded below by −100% and means what it says.

**Cost sensitivity finds a real cliff.** Mean Reversion on gold turns negative by
25 bps per side. Momentum on gold survives at 157% even at 100 bps. An edge that
only exists at zero cost is not an edge.

### Where strategies actually earn their keep

Regime attribution puts the benchmark alongside the strategy for the same
regime, with exposure. NVDA / Momentum:

| Regime | Days | Exposure | Strategy | Benchmark | Beat? |
|:--|--:|--:|--:|--:|:--|
| bear | 476 | **18%** | −63.4% | −82.0% | ✅ |
| bull | 1,839 | 94% | 13,448% | 35,789% | ❌ |
| high vol | 923 | 55% | 328.7% | 322.3% | ✅ |
| low vol | 767 | 97% | 381.8% | 353.2% | ✅ |
| normal vol | 705 | 90% | 194.1% | 379.1% | ❌ |

The **exposure** column is the real story: 18% invested in bear regimes against
94% in bull. The strategy's value is not a higher return, it is being absent when
the market falls — which is exactly what a trend filter is for, now measured
rather than asserted.

---

## Why you can trust the numbers

### The four failure modes, each with a structural defence

The problem statement names four ways backtests lie. Each gets a mechanism, not
a disclaimer.

| Risk | Defence |
|:--|:--|
| **Look-ahead bias** | Signals are shifted one bar and filled at the next open. Trading on a close you could not have observed is impossible by construction. Pinned by a dedicated test. |
| **Data leakage** | Indicators use only rolling and ewm windows; regime thresholds use expanding quantiles. 15 causality tests confirm that appending future bars never changes a past value — 9 indicators, 5 strategies, and the regime labels. |
| **Unrealistic execution** | Commission and slippage charged on notional on both sides, with slippage always moving price against the trade. Shorts pay a borrow fee per bar; leveraged positions pay interest on the borrowed cash. The benchmark pays the same entry cost. |
| **Over-optimisation** | Parameter sweeps report the whole Sharpe surface plus median, worst, share-positive and a neighbour comparison — never just the maximum. The verdict labels our own Mean Reversion strategy *fragile*. |

### Four decisions that change whether the numbers are right

**Per-asset annualisation.** Bitcoin trades 365 days a year; gold futures and
NVIDIA do not. The annualisation factor is a property of the asset, never a
hard-coded 252. Using 252 for crypto understates its volatility by roughly 20%.

**Calendar alignment by intersection.** Cross-asset correlation uses an inner
join of trading calendars, not a forward fill. Forward-filling equities across
weekends — where BTC keeps trading — injects bars that are flat by construction
and drags measured correlation toward zero.

**Expanding, not full-sample, regime thresholds.** Volatility terciles at bar *t*
use history up to *t* only, so a 2016 bar is never labelled using 2020
information. A visible consequence: regime shares are *not* an even 33/33/33
split. Gold sits in `high_vol` 52.7% of the time because its volatility trended
up over the decade; BTC sits in `low_vol` 46.9% because its trended down.
Full-sample terciles would force an even split and erase exactly that signal.

**Split adjustment across all OHLC fields.** The factor derived from the adjusted
close is applied to open, high and low too. Adjusting only the close would
corrupt open-based fills at every split. NVIDIA correctly reads $1.56 in 2016 —
the 40×-split-adjusted value of its then-$62 price.

The full reasoning for all 21 decisions is in
[`PROJECT_PLAN.md`](PROJECT_PLAN.md#6-decision-log).

### What the simulation does *not* model

Stated plainly, because an unstated simplification is a claim.

| Simplification | Direction | Why it is left alone |
|:--|:--|:--|
| **Idle cash earns no interest** | *Conservative* — understates strategies that sit out | Real cash earns T-bills. Adding that would flatter every trend strategy, so the omission errs against our own results. |
| **Fractional units** | Slightly optimistic | $10,000 buys 6,319.969 NVDA shares. Fine for crypto and modern brokers; a lot-size system would add real complexity for marginal realism. |
| **No liquidity or market-impact limits** | Optimistic at size | Daily bars on three of the most liquid instruments in the world. A $100k order moves none of them. |
| **No stop-losses or intraday exits** | Neutral | Not in the brief; every strategy is close-to-close by construction. |

What *is* modelled: commission and slippage on both sides, short borrow cost per
bar, interest on borrowed cash whenever exposure exceeds 100%, split and dividend
adjustment, per-asset annualisation, and next-open execution.

### Reading the charts

| Interaction | What it does |
|:--|:--|
| **Period bar presets / dates** | Set the window for every tab at once |
| **Drag across the price chart** | Same thing, done visually; a highlight follows the pointer |
| **✕ full history** | Back to the whole series |
| Hover any chart | Crosshair tooltip with every series at that date |
| Zoom in on Overview | All metrics, signal periods, markers, volume and the trade table follow |

### Testing

**496 tests.** Values are hand-computed against known answers, not snapshotted
from the implementation — a snapshot test locks in whatever bug exists.

| Suite | Tests | Covers |
|:--|--:|:--|
| `test_indicators.py` | 31 | Hand-computed EMA recursion, Bollinger population std, Wilder ATR, plus 9 causality tests |
| `test_metrics.py` | 32 | Closed-form cases: compounding, CAGR doubling, Sharpe by formula, hand-built drawdown paths |
| `test_correlation_regime.py` | 27 | Panel alignment, matrix symmetry, regime label rules, regime causality |
| `test_engine.py` | 63 | Look-ahead, cost arithmetic to the cent, equity curve vs trade log agreement, fractional sizing and financing |
| `test_strategies.py` | 68 | Known-answer price paths, parameter validation, strategy causality |
| `test_robustness.py` | 35 | Plateau detection against constructed surfaces with known answers |
| `test_api.py` | 99 | Every endpoint parsed with a **strict** JSON parser that rejects `Infinity`/`NaN` |
| `test_security.py` | 71 | Token guard, token-bucket arithmetic against injected time, grid cap, recipient allowlist — and that the other thirteen endpoints stay open |
| `test_email_report.py` | 17 | Address validation, archive assembly, SMTP dispatch with the transport mocked |
| `test_chat.py`, `test_news_sentiment.py` | 26 | Provider contracts and error mapping, with every network call monkeypatched |

---

## The capability boundary

Most security work on a project like this goes into the wrong place, because
the wrong place is the place that *sounds* dangerous. This platform has a
chatbot, so the reflex is to filter it for prompt injection. It has a REST API,
so the reflex is to put a login in front of it.

Neither reflex survives looking at what the endpoints can actually do.

### What the threat model actually is

Eighteen of the twenty-two endpoints read a committed CSV snapshot, do
arithmetic, and return numbers. They hold no secrets, write nothing, and reach
nothing. The worst an attacker gets from all eighteen combined is some of your
CPU. Four are different, and the difference is not subtle:

| | What it can do that the others cannot |
|:--|:--|
| `POST /api/report/send-email` | Package everything under `backend/output` and mail it, through an authenticated account, to an address the caller chooses |
| `POST /api/data/refresh` | Overwrite the snapshot every published figure in this README is computed from |
| `POST /api/chat` | Spend a metered AI provider key, once per request |
| `POST /api/news-sentiment/analyze-{text,image}` | The same, on a second provider |

That table is the whole security design. A control that does not sit in front
of one of those rows is not protecting anything.

### The chatbot is the wrong thing to worry about

Worth stating plainly, because the intuition is so strong the other way. The
assistant in [`chat.py`](backend/app/chat.py) has **no tools**. It receives
`page_json` and a question, returns markdown, and can reach nothing else — no
file access, no function calling, no ability to start a backtest or move a
position. A completely successful prompt injection against it yields a rude
paragraph.

What that endpoint *can* do is spend somebody's money, once per request,
without being asked who is calling. So it is guarded — for cost, not for
content. Filtering its inputs for jailbreak strings would have been effort
spent on the failure mode that does not exist, in front of the one that does.

### The email endpoint was the real hole

`POST /api/report/send-email` took an arbitrary recipient, zipped the entire
contents of `backend/output`, and sent it through the configured Gmail account.
Unauthenticated, unlimited, and writing an `.eml` copy to disk on every call.
That is three separate things at once:

- an **exfiltration primitive** — name your own address, receive the archive
- an **open relay** signed with the sender's own reputation
- an **unbounded disk write**

None of it required a clever attack. The feature worked exactly as designed;
the design simply never said who was allowed to receive the output. It is now
the most restricted endpoint in the platform, and its allowlist fails closed:
unconfigured, the only permitted recipient is the mailbox the report is sent
*from*. You can mail the archive to yourself, and to nobody else, without
setting anything.

### What was built

One module — [`security.py`](backend/app/security.py) — and five route
decorations. Deliberately not a framework.

| Control | Applies to | Default with no configuration |
|:--|:--|:--|
| Shared-secret header | the 5 effectful endpoints | **Off.** Documented, and reported by `/health` |
| Token bucket, per route and per client | the 5, plus robustness | **On.** Needs no configuration to be useful |
| Recipient allowlist | send-email | **On, fails closed** — the SMTP sender only |
| Grid cell cap (400) | robustness | **On.** A `100×100` grid is 10,000 backtests in one request |
| Concurrent sweep bound (2) | robustness | **On.** Otherwise a sweep can starve `/health` |
| Body size ceiling | every POST | **On.** 1 MiB for JSON, 17 MiB on the image upload |

That last row closes a gap the rate limit cannot. A budget bounds how *many*
requests arrive, not how large each one is — and the assistant forwards its
payload to a metered provider, so twenty permitted requests carrying 100 MB
each walk straight through a 20-per-minute limit. Starlette imposes no ceiling
of its own.

A body must also **declare its length**, or it gets `411 Length Required`.
Every client that matters already does. The alternative was counting bytes
mid-stream and failing partway, which works but has no clean answer: the client
is still uploading when the server wants to reply, so the response races the
upload, h11 raises `LocalProtocolError`, and the caller sees a dropped
connection instead of a 413 while the log fills with tracebacks a hostile
caller can produce on demand. Requiring the declaration turns the whole thing
into arithmetic on a header, decided before a byte of body is read.

The asymmetry in that last column is the only interesting design decision here.
Rate limits and the allowlist are always on, because the things they prevent —
a drained provider balance, a suspended mail account — are exactly the things
nobody remembers to configure against. The token is off by default, because a
fresh `git clone` that refuses to run teaches people to disable security rather
than configure it, and because the server binds `127.0.0.1`.

That binding is now written explicitly in `run.sh` and `run.ps1` even though it
is uvicorn's default. An assumption that lives in a default is one nobody reads
before overriding it, and `--host 0.0.0.0` on conference wifi is a one-word
change that silently invalidates the entire paragraph above it.

### What this is not

**It is not authentication.** The token reaches the browser as a Vite variable,
which means it is baked into the bundle and readable in devtools by anyone
sitting at the dashboard. It raises the cost of drive-by and scripted abuse
against a tool bound to loopback. It does not defend against someone with
access to the machine, and the module's own docstring says so rather than
leaving the reader to discover it.

**There is no login, no JWT, no RBAC, no TLS.** This is a single-user local
research tool. Those would be visible effort spent on a threat model that does
not apply, and each one is a component that can be wrong. The honest security
posture is a small fence around four dangerous things and a clear statement of
what is outside it.

**`/health` publishes the state of the guards, never the secret.** A deployment
that believes it is protected and is not is worse off than one that knows it is
open:

```json
"security": {
  "token_required": false,
  "token_header": "X-QMAFIB-Token",
  "rate_limits": {"refresh": "3/300s", "email": "3/3600s", "chat": "20/60s",
                  "sentiment": "10/60s", "robustness": "30/60s"},
  "max_body_bytes": 1048576,
  "max_upload_bytes": 17825792,
  "max_grid_cells": 400,
  "report_recipients_configured": 1
}
```

### Two refusals, two status codes

One endpoint can refuse for two unrelated reasons, and they call for completely
different advice. A **401** is always a credential problem — no token, or the
wrong one. A **403** is always the recipient policy: you are who you say, and
that address still is not approved. The dashboard branches on the code, so it
can say which instead of showing the API's own text, which names environment
variables at a reader who does not run the server.

The rate limit is also listed *before* the token check on every guarded route.
That looks backwards and is not: dependencies resolve in order and the first to
raise wins, so checking the token first would hand out unlimited failed attempts
for free. This way a guesser runs out of requests.

### The tests that matter most are the negative ones

Of the 71 tests in [`test_security.py`](backend/tests/test_security.py), the
ones worth reading first assert what is **not** guarded: that `/api/assets`,
`/api/metrics`, `/api/ohlcv`, `/api/strategies` and `/api/panel` return 200
with the strictest configuration active, and that sixty consecutive reads are
never rate-limited.

A security layer that quietly puts the read-only dashboard behind a token has
broken the product in order to protect the parts that were never at risk. That
failure is much easier to ship than the one it replaces, because everything
still works on the machine where the token is configured. Those tests exist to
catch the fence spreading.

---

## Project layout

```
backend/
  app/
    config.py              Asset registry, engine defaults
    data/
      sources.py           Yahoo chart API client
      validate.py          OHLC invariants, cleaning, quality report
      store.py             CSV cache, aligned multi-asset panel
    analytics/
      indicators.py        SMA, EMA, RSI, MACD, Bollinger, ATR, ROC
      metrics.py           Returns, volatility, Sharpe, Sortino, drawdown
      correlation.py       Matrix, covariance, rolling correlation
      regime.py            Bull/bear + volatility regime classification
    backtest/
      engine.py            Bar-by-bar execution, costs, trade log, benchmark
      strategies.py        Five strategies behind a common base class
      robustness.py        Parameter/cost/period sweeps, regime attribution
    api/
      routes.py            REST endpoints
      chat_routes.py       Assistant proxy
      news_sentiment_routes.py
      serialise.py         inf/NaN -> null, numpy -> native
    chat.py                Featherless client
    email_service.py       Report archive + SMTP dispatch
    security.py            Capability boundary: token, rate limits, allowlist
    main.py                FastAPI app, CORS, /health
  tests/                   496 tests
  scripts/                 One runnable gate per phase
  data_snapshot/           Committed CSV market data
frontend/
  src/
    api.ts                 Typed client; every numeric field is `number | null`
    format.ts              Display formatting; null renders as an em dash
    App.tsx                Shell, tabs, asset picker, disclaimer
    views/                 Overview · Risk · Correlation · Backtest · Compare · Research · News Sentiment
run.sh · run.ps1           Start API + dashboard
verify.sh                  Run every phase gate
DEMO.md                    Scripted three-minute walkthrough
docs/
  problem-statement.pdf
  PROJECT_PLAN_FIN_original.md
```

**Layering rule:** `data` does not import `analytics`; `analytics` does not
import `backtest`; nothing below the API layer imports FastAPI. The quant core
is importable and testable without a running server.

`security.py` sits *beside* the API rather than under it — it is the only
non-`api/` module that imports FastAPI, because dependencies and `HTTPException`
are what it exists to produce. Nothing in `data`, `analytics` or `backtest`
imports it, so the rule above still holds where it matters.

---

## Extending it

### Add an asset

One entry in `backend/app/config.py`:

```python
ASSETS = {
    ...
    "SPY": Asset("SPY", "S&P 500 ETF", "SPY", "equity", 252),
}
```

Then `python scripts/bootstrap_data.py --refresh`. The API, the dashboard's asset
picker, the correlation matrix and every sweep pick it up with no other changes.

### Add a strategy

Subclass `Strategy`, implement one method, add it to the registry:

```python
@dataclass
class RsiReversal(Strategy):
    name: ClassVar[str] = "rsi_reversal"
    label: ClassVar[str] = "RSI Reversal"
    description: ClassVar[str] = "Long when RSI leaves oversold territory."
    defaults: ClassVar[dict] = {"window": 14, "oversold": 30}

    def generate_signals(self, df):
        r = rsi(df["close"], self.params["window"])
        return self._hold(r > self.params["oversold"], r < 20, df.index)
```

Return the target **exposure** at each bar's close: `1.0` fully invested, `0`
flat, `-1.0` fully short, and anything in between or beyond if the strategy
sizes continuously. The engine applies the execution lag — a strategy must never
lag its own signals, or it double-lags. The strategy dropdowns, comparison runs
and robustness sweeps all update automatically.

Two things to register if the strategy sizes rather than times:

1. Add a default sweep grid in `DEFAULT_GRIDS` (`app/api/routes.py`), or the
   Research tab has no two axes to plot.
2. If it needs the asset's trading calendar, name the parameter in
   `CALENDAR_PARAMS` and the registry fills it per asset — 365 bars a year for
   crypto, 252 for equities. A shared constant would understate BTC volatility
   by about 20%.

---

## Reference

### API endpoints

Interactive docs at `http://localhost:8000/docs`.

🔒 marks the five endpoints behind the
[capability boundary](#the-capability-boundary) — they need `X-QMAFIB-Token`
when one is configured, and are rate-limited whether or not it is. Everything
else is open by design.

| Method | Path | Returns |
|:--|:--|:--|
| `GET` | `/health` | Liveness, asset list, disclaimer, and which guards are active |
| `GET` | `/api/assets` | Asset registry and snapshot state |
| `GET` | `/api/strategies` | Strategy catalogue with defaults |
| `GET` | `/api/ohlcv?asset=` | Validated bars + quality report |
| `GET` | `/api/indicators?asset=` | All indicators, configurable periods |
| `GET` | `/api/metrics?asset=` | Risk summary, rolling returns/volatility, drawdown; optional `start`/`end` |
| `GET` | `/api/correlation?window=` | Matrix + rolling correlation |
| `GET` | `/api/rolling-correlation?a=&b=` | One pair's rolling correlation |
| `GET` | `/api/regime?asset=` | Regime labels over time |
| `GET` | `/api/panel` | Aligned multi-asset close panel |
| `GET` | `/api/backtest/regime-attribution` | Strategy vs benchmark by regime |
| `POST` | 🔒 `/api/data/refresh` | **The only endpoint that touches the market-data provider.** Re-downloads the snapshot; skips assets fetched within the last day unless `force` |
| `POST` | `/api/backtest` | One strategy + benchmark + trade log; optional `start`/`end` |
| `POST` | `/api/backtest/compare` | Every strategy against one benchmark; optional `start`/`end` |
| `POST` | `/api/backtest/robustness` | Surface, plateau verdict, cost + period sweeps. Rate-limited and grid-capped, but needs no token: it spends CPU, not money |
| `POST` | 🔒 `/api/report/send-email` | Mails the contents of `backend/output`. Recipient must be on the allowlist, which defaults to the SMTP sender |
| `POST` | 🔒 `/api/chat` | Dashboard assistant, proxied to Featherless |
| `GET` | `/api/news-sentiment/health` | Liveness + whether a live analysis is configured |
| `POST` | 🔒 `/api/news-sentiment/analyze-text` | Live Gemini analysis of a pasted news article |
| `POST` | 🔒 `/api/news-sentiment/analyze-image` | Live Gemini OCR + analysis of a news screenshot |
| `POST` | `/api/news-sentiment/chart-data` | Recent price history for dependency charts, from the snapshot |
| `GET` | `/api/news-sentiment/sentiment-history` | Articles analysed in this process (in-memory) |

### Dependencies

Seven packages. No database, no cache server, no TA-Lib.

```
fastapi · uvicorn · pandas · numpy · requests · pytest · httpx · google-genai · python-dotenv
```

Market data comes from the Yahoo Finance chart API via `requests`. See decision
**D1** in [`PROJECT_PLAN.md`](PROJECT_PLAN.md#6-decision-log) for why `yfinance`
and `pyarrow` were dropped. The News Sentiment tab adds two optional-with-a-key
dependencies: `google-genai` for the live Gemini analysis and `python-dotenv`
to read `GEMINI_API_KEY` from a `backend/.env` file. Without a key the analyzing
endpoints return 503 with an explanatory message; the rest of the platform is
unaffected.

Frontend: React 19, Vite, TypeScript, Recharts.

### Data quality

Reported rather than silently smoothed.

- **Gold has 82 flat bars** (3.3%) where open = high = low = close, all before
  2020-03-27 — thin front-month futures days. Genuine data. An open-based fill
  equals the close on those days, which is the conservative direction.
- **Gold dropped 3 null-close rows** during validation.
- **BTC retains 69% of its rows** in the aligned panel. Weekends are removed so
  cross-asset comparisons are like-for-like; single-asset BTC analysis still
  uses the full 3,653-row series.

### Troubleshooting

| Symptom | Cause | Fix |
|:--|:--|:--|
| Dashboard won't load at `127.0.0.1:5173` | Vite binds IPv6 | Use `http://localhost:5173` |
| "Cannot reach the API" | Backend not running | Start it, or run `./run.sh` which starts both |
| CORS error in the console | Dashboard on a non-default port | Add the origin to the list in `backend/app/main.py` |
| Research tab spins for a second | Expected — it runs ~25 backtests plus cost and period sweeps | Wait ~2s |
| `./run.sh: Permission denied` | Not executable | `chmod +x run.sh verify.sh` |
| `python3: command not found` on Windows | Use the PowerShell script | `.\run.ps1` |
| `port 8000 is already in use` | An earlier run is still alive | Stop it, or `API_PORT=8001 UI_PORT=5174 ./run.sh`. The scripts refuse to start rather than leave a stale server answering with old code. |
| Refresh says "already current" | Bars are daily, so a second fetch inside 24h would rewrite identical rows | Expected. `POST /api/data/refresh` with `{"force": true}` to override. |
| Want to check everything still works | — | `./verify.sh` |

### Out of scope

Listed as *Future Scope* in the problem statement and correctly deferred:
portfolio optimisation, Monte Carlo simulation, Value at Risk, ML-based regime
detection, paper trading, real-time data, AI research assistance.
