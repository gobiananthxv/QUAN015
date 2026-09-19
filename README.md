# QMAFIB

**Quantitative Multi-Asset Financial Intelligence & Backtesting Platform**

A unified research platform that collects a decade of daily market history across
three asset classes, computes quantitative indicators and risk metrics, measures
how cross-asset relationships shift over time, and backtests trading strategies
against a buy-and-hold benchmark with realistic execution costs.

> ⚠️ **Research tool, not investment advice.** Every figure here is computed from
> historical data. Backtested performance is not a prediction of future returns.

---

## Contents

- [Status](#status) — what is built
- [How it works](#how-it-works) — the pipeline, stage by stage
- [Quick start](#quick-start) — install and run
- [Results](#results) — what the engine actually finds
- [Design decisions](#design-decisions) — the choices that affect correctness
- [Bias controls](#bias-controls) — how the four named failure modes are prevented
- [Project layout](#project-layout)
- [Data quality](#data-quality)
- [Demo walkthrough](DEMO.md) — a scripted three-minute tour

---

## Status

| Phase | Scope | Status |
|:--|:--|:--|
| 0 | Scaffold | ✅ Complete |
| 1 | Data pipeline | ✅ Complete |
| 2 | Analytics engine | ✅ Complete |
| 3 | Backtesting engine | ✅ Complete |
| 4 | Strategies | ✅ Complete |
| 5 | Regime attribution + robustness | ✅ Complete |
| 6 | REST API + dashboard | ✅ Complete |
| 7 | Hardening + demo | ✅ Complete |

**262 tests passing**, all seven phase gates green. Full breakdown and decision
log in [`PROJECT_PLAN.md`](PROJECT_PLAN.md); the walkthrough is in
[`DEMO.md`](DEMO.md).

---

## How it works

The platform is a pipeline of nine stages. Each stage reads only from the stage
above it, so any stage can be run, tested or replaced on its own.

### Stages 1–3 · Data

| # | Stage | Entry point | What happens |
|:--|:--|:--|:--|
| 1 | **Ingest** | `sources.fetch_ohlcv(key)` | Yahoo chart API with retry and backoff. Split and dividend adjustment applied across all four OHLC fields. |
| 2 | **Validate** | `validate.validate_ohlcv(df, key)` | OHLC invariants repaired, null and non-positive closes dropped, duplicates removed, index sorted, gaps counted. Returns a quality report. |
| 3 | **Cache** | `store.load_asset(key)`<br>`store.load_panel(keys)` | Committed CSV cache — the platform runs offline. `load_panel` aligns assets onto a common trading calendar. |

### Stage 4 · Analytics

These three run independently off the cache and never touch each other.

| Stage | Entry point | Produces |
|:--|:--|:--|
| **4a Indicators** | `compute_indicators(df)` | SMA, EMA, RSI, MACD, Bollinger (+ z-score), ATR, ROC |
| **4b Metrics** | `summarise(returns, ann_factor)` | Returns, volatility, Sharpe, Sortino, Calmar, max drawdown + duration |
| **4c Correlation** | `correlation_matrix()`<br>`rolling_correlation(a, b)` | Static matrix, covariance, rolling pairwise correlation |

### Stages 5–6 · Backtesting

| # | Stage | Entry point | What happens |
|:--|:--|:--|:--|
| 5 | **Signals** | `strategy.generate_signals(df)` | Returns the target position at each bar's **close**, in `{-1, 0, 1}`. Four strategies available. |
| 6 | **Execute** | `engine.run_backtest(df, signals, asset, config)`<br>`engine.buy_and_hold(df, asset, config)` | Lags signals one bar, fills at the next open ± slippage, charges commission on both sides, sizes from equity, marks to market every close. |

Stage 6 returns a `BacktestResult` carrying the equity curve, per-bar position,
and a full trade log. The benchmark runs through the **same** engine with the
**same** costs.

### Stage 7 · Robustness and attribution

| Stage | Entry point | Answers |
|:--|:--|:--|
| **7a Parameter sweep** | `parameter_sweep(asset, strategy, grid)`<br>`plateau_report(sweep, params)` | Does this survive changing the parameters, or is it one lucky cell? |
| **7b Cost sweep** | `cost_sweep(asset, strategy)` | Does the edge survive realistic friction? |
| **7c Period sweep** | `period_sweep(asset, strategy, n_windows)` | Is this an edge, or one good episode? |
| **7d Regime attribution** | `regime_attribution(asset, strategy)` | *Where* does it beat the benchmark — and at what exposure? |

### Stages 8–9 · API and dashboard

| # | Stage | Entry point | What happens |
|:--|:--|:--|:--|
| 8 | **Serve** | `uvicorn app.main:app` | Eleven endpoints. Every response passes through `serialise.clean`, so `inf` and `NaN` leave as `null`. |
| 9 | **Visualise** | `npm run dev --prefix frontend` | React + Vite + TypeScript, five views, Recharts. |

**Endpoints** — `GET /health` `/api/assets` `/api/strategies` `/api/ohlcv`
`/api/indicators` `/api/metrics` `/api/correlation` `/api/rolling-correlation`
`/api/regime` `/api/panel` `/api/backtest/regime-attribution`, and
`POST /api/backtest` `/api/backtest/compare` `/api/backtest/robustness`.
Interactive docs at `http://localhost:8000/docs`.

**Views** — **Overview** (log-scale price, SMA 50/200, volume, shaded in-market
bands) · **Risk** (metric tiles, cumulative return, underwater drawdown, rolling
volatility) · **Correlation** (matrix heatmap, rolling correlation with a
selectable window) · **Backtest** (live parameter and cost controls, equity curve
vs benchmark, full trade log) · **Research** (Sharpe surface heatmap with the
best cell marked, plateau verdict, cost decay, period stability, regime
attribution).

### The one contract everything depends on

```
position[t] == sign(signal[t-1]),  filled at open[t]
```

A signal derived from bar *t*'s close cannot be acted on until bar *t+1* opens.
Every backtest number shifts if this changes, so it is pinned by a dedicated
test (`test_execution_lag_is_exactly_one_bar`) rather than left to convention.

---

## Quick start

Requires Python 3.11+. No database, no Redis, no Docker.

> **Interpreter path differs by platform.** The venv puts Python at
> `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` on macOS and
> Linux. Both sets of commands are given below — use the ones for your OS.
> Activating the venv first (`source .venv/bin/activate` or
> `.venv\Scripts\Activate.ps1`) lets you type plain `python` instead.

### One command

```bash
./run.sh
```

```powershell
.un.ps1
```

Creates the virtualenv and installs dependencies if they are missing, then
starts the API on `:8000` and the dashboard on `:5173`. Ctrl-C stops both.

To run every phase gate — the full test suite plus all five verification
scripts — in one go:

```bash
./verify.sh
```

<details>
<summary>Manual setup, if you prefer to run the pieces yourself</summary>

### Install

**macOS / Linux**

```bash
cd backend && python3 -m venv .venv --system-site-packages && .venv/bin/python -m pip install -r requirements.txt
```

**Windows (PowerShell or Git Bash)**

```bash
cd backend && python -m venv .venv --system-site-packages && ./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

`--system-site-packages` reuses any pandas/numpy already installed system-wide.
Drop the flag for a fully isolated environment; it just downloads more.

### Run

The market-data cache is committed, so everything below runs offline.

**Run the test suite:**

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q
```

**Run each pipeline stage.** Each script exits non-zero if an invariant breaks —
these are the phase gates, not just demos. On Windows, substitute
`./.venv/Scripts/python.exe` for `.venv/bin/python` in each command.

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

### Run the pieces separately

Two processes. Start the API first:

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Then the dashboard, in a second terminal:

```bash
npm install --prefix frontend && npm run dev --prefix frontend
```

The dashboard opens at `http://localhost:5173`; the API's interactive docs are at
`http://localhost:8000/docs`. Point the dashboard elsewhere with
`VITE_API_URL=http://host:port`.

**Re-fetch live data** (overwrites the committed cache):

```bash
cd backend && .venv/bin/python scripts/bootstrap_data.py --refresh
```

```bash
cd backend && ./.venv/Scripts/python.exe scripts/bootstrap_data.py --refresh
```

</details>

---

## Results

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
| BTC | 13,236% | 63.07% | 66.81% | 1.04 | −83.4% | 1,079 d |
| NVDA | 14,130% | 64.41% | 50.05% | 1.20 | −66.3% | 373 d |

### Correlation is not a constant

Full-sample daily-return correlation is low across every pair — GOLD~BTC 0.10,
GOLD~NVDA 0.04, BTC~NVDA 0.22. But the rolling 90-day figure swings through a
range of 0.80 to 0.98 depending on the pair. A single correlation number hides
the thing worth knowing, which is why the rolling view exists.

### Strategy vs benchmark

All four strategies, 10 bps commission and 5 bps slippage per side, against
buy-and-hold paying the same entry cost.

**GOLD**

| Strategy | Total | Sharpe | Max DD | Trades | Exposure |
|:--|--:|--:|--:|--:|--:|
| SMA Crossover | 136.7% | 0.52 | −30.6% | 7 | 70% |
| EMA Trend | 104.7% | 0.44 | −27.9% | 33 | 61% |
| Momentum | 202.6% | 0.69 | **−21.0%** | 6 | 70% |
| Mean Reversion | 18.2% | −0.00 | −10.6% | 38 | 20% |
| **Buy & Hold** | **236.3%** | 0.69 | −24.9% | — | 100% |

**BTC**

| Strategy | Total | Sharpe | Max DD | Trades | Exposure |
|:--|--:|--:|--:|--:|--:|
| SMA Crossover | 4,433% | 0.94 | −69.3% | 9 | 53% |
| EMA Trend | 8,558% | 1.13 | **−61.2%** | 61 | 53% |
| **Momentum** | **13,485%** | **1.16** | −64.3% | 18 | 57% |
| Mean Reversion | −50.8% | −0.03 | −81.0% | 54 | 23% |
| Buy & Hold | 13,216% | 1.04 | −83.4% | — | 100% |

**NVDA**

| Strategy | Total | Sharpe | Max DD | Trades | Exposure |
|:--|--:|--:|--:|--:|--:|
| SMA Crossover | 6,409% | 1.18 | **−37.6%** | 3 | 74% |
| EMA Trend | 1,306% | 0.85 | −45.9% | 52 | 66% |
| Momentum | 5,296% | 1.16 | −39.7% | 14 | 76% |
| Mean Reversion | 248.4% | 0.53 | −55.4% | 42 | 18% |
| **Buy & Hold** | **13,947%** | **1.20** | −66.3% | — | 100% |

### What the results actually say

**Buy-and-hold wins on return in 2 of 3 assets.** We report that as-is rather
than tuning until the strategies win. On assets that trended this hard for a
decade, sitting out of the market costs more than the crashes it avoids.

**Every strategy reduced drawdown on BTC and NVDA.** NVDA's SMA crossover gives
up half the return but cuts the worst drawdown from −66% to −38%. That is a
different objective, not a worse one.

**One genuine winner: Momentum on BTC** — 13,485% against the benchmark's
13,216%, with a higher Sharpe (1.16 vs 1.04) and a shallower drawdown (−64% vs
−83%), in 18 trades. EMA Trend beats the benchmark's Sharpe on BTC too (1.13)
while giving up return.

**Mean reversion lost money on BTC** (−50.8%). Buying dips works until the dip
keeps going; its −81% drawdown says the rest. Note it loses at zero cost too
(−42.1%), so this is the rule failing, not friction.

A platform that only surfaced strategies beating their benchmark would be
selection bias with a dashboard.

### Why EMA Trend and Momentum use a confirmation band

Both rules originally tested a strict inequality against a noisy quantity, and
both whipsawed badly: **50% of gold's EMA Trend trades lasted two bars or
fewer**, and transaction costs consumed **67% of its gross return**. That is
noise trading, and it is identifiable as a defect without looking at a single
return figure.

Both now use a confirmation band — enter above one level, exit below a lower
one, hold in between — which makes them stateful:

| Asset | Strategy | Trades before → after | ≤2-bar trades before → after |
|:--|:--|:--|:--|
| GOLD | EMA Trend | 129 → 33 | 50% → 6% |
| GOLD | Momentum | 35 → 6 | 31% → 0% |
| BTC | Momentum | 63 → 18 | 43% → 0% |
| NVDA | EMA Trend | 116 → 52 | 37% → 2% |

The defaults (1% and 5%) are round numbers chosen for being round, **not tuned
against results** — the band improves gold and NVDA but *reduced* EMA Trend's
BTC return from 15,254% to 8,558%. Picking a band because it flattered the
average would be exactly the over-optimisation the brief warns against, applied
after seeing the answers. Phase 5's robustness sweep decides whether these
defaults sit on a stable plateau or a lucky spike.

### Robustness: does any of this survive scrutiny?

Sharpe across a wide parameter grid, summarised as `robustness` = median ÷ best.
Near 1.0 means the surface is flat and the parameter choice barely matters; near
0 means one cell carries the whole result.

| Strategy | GOLD | BTC | NVDA | Verdict |
|:--|--:|--:|--:|:--|
| SMA Crossover | 0.83 | 0.88 | 0.87 | robust — 100% of cells positive on all three |
| EMA Trend | 0.58 | 0.91 | 0.85 | robust on BTC/NVDA, moderate on gold |
| Momentum | 0.82 | 0.90 | 0.89 | robust across the board |
| Mean Reversion | **0.10** | **0.24** | 0.63 | **fragile — treat as over-fitted** |

The tool flags our own weakest strategy. Mean Reversion's headline numbers come
from a handful of grid cells, which is consistent with it losing money on BTC.

**Period stability is the harshest test, and most strategies fail it.** Split
into 5 consecutive windows with signals regenerated per window, strategies beat
buy-and-hold in only 1–2 windows out of 5. NVDA's SMA crossover ends the
2022–2024 window with **30% of the wealth** buy-and-hold produced — being out of
the market during the AI run was ruinous. One decade-long backtest hides that
completely.

Excess is reported **geometrically** — `(1+strategy)/(1+benchmark) − 1` — not as
a difference of total returns. Subtracting two compounded returns is unreadable
once they are large: that same window's arithmetic excess is −639%, which reads
as losing six times your money when the strategy actually *gained* 177%. The
geometric figure is bounded below by −100% and means what it says.

**Cost sensitivity finds a real cliff.** Mean Reversion on gold turns negative
by 25 bps per side, and EMA Trend on gold by 100 bps. Momentum on gold survives
at 157% even at 100 bps. An edge that only exists at zero cost is not an edge.

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
94% in bull. The strategy's value is not a higher return, it is being absent
when the market falls — which is exactly what a trend filter is for, now
measured rather than asserted.

---

## Design decisions

Four choices that materially affect whether the numbers are right.

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

---

## Bias controls

The problem statement names four failure modes. Each gets a structural defence,
not a disclaimer.

| Risk | Defence |
|:--|:--|
| **Look-ahead bias** | Signals are shifted one bar and filled at the next open. Trading on a close you could not have observed is impossible by construction. Pinned by a dedicated test. |
| **Data leakage** | Indicators use only rolling and ewm windows; regime thresholds use expanding quantiles. 14 causality tests confirm that appending future bars never changes a past value — 9 indicators, 4 strategies, and the regime labels. |
| **Unrealistic execution** | Commission and slippage charged on notional on both sides, with slippage always moving price against the trade. The benchmark pays the same entry cost. |
| **Over-optimisation** | Parameter sweeps report the whole Sharpe surface plus median, worst, share-positive and a neighbour comparison — never just the maximum. `plateau_report` returns an explicit verdict, and it labels our own Mean Reversion strategy *fragile*. |

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
      strategies.py        Four strategies behind a common base class
      robustness.py        Parameter/cost/period sweeps, regime attribution
    api/
      routes.py            REST endpoints
      serialise.py         inf/NaN -> null, numpy -> native
    main.py                FastAPI app, CORS, /health
  tests/                   262 tests
  scripts/                 One runnable gate per phase
  data_cache/              Committed CSV market data
frontend/
  src/
    api.ts                 Typed client; every numeric field is `number | null`
    format.ts              Display formatting; null renders as an em dash
    App.tsx                Shell, tabs, asset picker, disclaimer
    views/                 Overview · Risk · Correlation · Backtest · Research
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

---

## Data quality

Reported rather than silently smoothed.

- **Gold has 82 flat bars** (3.3%) where open = high = low = close, all before
  2020-03-27 — thin front-month futures days. Genuine data. An open-based fill
  equals the close on those days, which is the conservative direction.
- **Gold dropped 3 null-close rows** during validation.
- **BTC retains 69% of its rows** in the aligned panel. Weekends are removed so
  cross-asset comparisons are like-for-like; single-asset BTC analysis still
  uses the full 3,653-row series.

---

## Dependencies

Six packages. No database, no cache server, no TA-Lib.

```
fastapi · uvicorn · pandas · numpy · requests · pytest
```

Market data comes from the Yahoo Finance chart API via `requests`. See decision
**D1** in [`PROJECT_PLAN.md`](PROJECT_PLAN.md#6-decision-log) for why `yfinance`
and `pyarrow` were dropped.
