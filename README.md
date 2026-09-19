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

---

## Status

| Phase | Scope | Status |
|:--|:--|:--|
| 0 | Scaffold | ✅ Complete |
| 1 | Data pipeline | ✅ Complete |
| 2 | Analytics engine | ✅ Complete |
| 3 | Backtesting engine | ✅ Complete |
| 4 | Strategies | ✅ Complete |
| 5 | Regime attribution + robustness | ⬜ Pending |
| 6 | REST API + dashboard | ⬜ Pending |
| 7 | Hardening + demo | ⬜ Pending |

**174 tests passing.** Full phase breakdown and decision log in
[`PROJECT_PLAN.md`](PROJECT_PLAN.md).

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

### Stages 7–9 · Not yet built

| # | Stage | Planned entry point |
|:--|:--|:--|
| 7 | **Analyse** | `regime.regime_breakdown(key, returns)` — built, wiring pending<br>`robustness.sweep(...)` — parameter grid → Sharpe surface |
| 8 | **Serve** | FastAPI: `/ohlcv` `/indicators` `/metrics` `/correlation` `/backtest` `/regime` |
| 9 | **Visualise** | React + Vite + TypeScript — Overview, Risk, Correlation, Backtest, Research |

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

**Re-fetch live data** (overwrites the committed cache):

```bash
cd backend && .venv/bin/python scripts/bootstrap_data.py --refresh
```

```bash
cd backend && ./.venv/Scripts/python.exe scripts/bootstrap_data.py --refresh
```

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
| **Data leakage** | Indicators use only rolling and ewm windows; regime thresholds use expanding quantiles. 15 causality tests confirm that appending future bars never changes a past value. |
| **Unrealistic execution** | Commission and slippage charged on notional on both sides, with slippage always moving price against the trade. The benchmark pays the same entry cost. |
| **Over-optimisation** | Parameter sweeps report the whole Sharpe surface, so an isolated spike is visibly a spike. *(Phase 5)* |

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
  tests/                   174 tests
  scripts/                 One runnable gate per phase
  data_cache/              Committed CSV market data
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
