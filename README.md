# QMAFIB

**Quantitative Multi-Asset Financial Intelligence & Backtesting Platform**

A unified research platform that collects a decade of daily market history across
three asset classes, computes quantitative indicators and risk metrics, measures
how cross-asset relationships shift over time, and backtests trading strategies
against a buy-and-hold benchmark with realistic execution costs.

> ⚠️ **Research tool, not investment advice.** Every figure in this project is
> computed from historical data. Backtested performance is not a prediction of
> future returns. See [Bias controls](#bias-controls).

---

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffold | ✅ Complete |
| 1 | Data pipeline | ✅ Complete |
| 2 | Analytics engine | ✅ Complete |
| 3 | Backtesting engine | ✅ Complete (123 tests) |
| 4 | Strategies | ⬜ Pending |
| 5 | Regime + robustness | ⬜ Pending |
| 6 | API + dashboard | ⬜ Pending |
| 7 | Tests, docs, demo | ⬜ Pending |

Full phase breakdown and decision log: [`PROJECT_PLAN.md`](PROJECT_PLAN.md).

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q
```

---

## What the engine finds

Buy-and-hold over the full history, using each asset's own annualisation factor:

| Asset | Total | CAGR | Volatility | Sharpe | Max DD | Longest DD |
|---|---|---|---|---|---|---|
| GOLD | 236.9% | 12.95% | 16.95% | 0.69 | −24.9% | 836 d |
| BTC | 13,236% | 63.07% | 66.81% | 1.04 | −83.4% | 1,079 d |
| NVDA | 14,130% | 64.41% | 50.05% | 1.20 | −66.3% | 373 d |

Daily-return correlation is low across all three pairs (GOLD~BTC 0.10,
GOLD~NVDA 0.04, BTC~NVDA 0.22) — but the *rolling* 90-day figure swings through
a range of 0.80 to 0.98 depending on the pair. Correlation is not a constant,
which is the entire reason the rolling view exists.

Regime attribution separates the assets sharply. NVDA compounds at 124% a year
in bull regimes and −60% in bear ones; BTC at 323% versus −57%. Reproduce any
of this with:

```bash
cd backend && ./.venv/Scripts/python.exe scripts/analytics_report.py
```

### Strategy vs benchmark

A 50/200 SMA crossover, charged 10 bps commission and 5 bps slippage per side,
against buy-and-hold paying the same entry cost:

| Asset | Run | Total | Sharpe | Max DD | Trades | Costs |
|---|---|---|---|---|---|---|
| GOLD | SMA 50/200 | 136.7% | 0.52 | −30.6% | 7 | $2,839 |
| GOLD | Buy & hold | 236.3% | 0.69 | −24.9% | — | $150 |
| BTC | SMA 50/200 | 4,433% | 0.94 | −69.3% | 9 | $72,423 |
| BTC | Buy & hold | 13,216% | 1.04 | −83.4% | — | $150 |
| NVDA | SMA 50/200 | 6,409% | 1.18 | −37.6% | 3 | $16,743 |
| NVDA | Buy & hold | 13,947% | 1.20 | −66.3% | — | $150 |

**The crossover loses to buy-and-hold on every asset.** That is the honest
result and we report it as-is: on assets that trended this hard for a decade,
sitting out of the market costs more than the crashes it avoids. What the
strategy does buy is a materially shallower drawdown — NVDA −37.6% against
−66.3%, BTC −69.3% against −83.4% — which is a different objective, not a
worse one. Gold is the exception: there the crossover is worse on *both* axes.

A platform that only surfaced strategies beating their benchmark would be
selection bias with a dashboard.

---

## How it works

The platform is a pipeline. Each stage consumes the stage above it and nothing
else, so any stage can be run, tested or replaced on its own. Stages marked
*pending* are not yet built; everything above them already runs end to end.

```
  ┌─ 1. INGEST ────────────────────────────────────────────── Phase 1 ✅
  │  sources.fetch_ohlcv(key)
  │  Yahoo chart API -> retry/backoff -> split & dividend adjustment
  │  applied across all four OHLC fields
  ▼
  ┌─ 2. VALIDATE ──────────────────────────────────────────── Phase 1 ✅
  │  validate.validate_ohlcv(df, key) -> (clean_df, quality_report)
  │  OHLC invariants repaired · null & non-positive closes dropped
  │  duplicates removed · index sorted · gaps counted
  ▼
  ┌─ 3. CACHE ─────────────────────────────────────────────── Phase 1 ✅
  │  store.load_asset(key)      -> one asset, committed CSV
  │  store.load_panel(keys)     -> many assets on a COMMON calendar
  │  Cold cache fetches; warm cache reads from disk. Runs offline.
  ▼
  ├─────────────────────────┬──────────────────────────────────────────┐
  ▼                         ▼                                          ▼
┌─ 4a. INDICATORS ──┐  ┌─ 4b. METRICS ────────┐  ┌─ 4c. CORRELATION ──────┐
│   Phase 2 ✅       │  │   Phase 2 ✅          │  │   Phase 2 ✅            │
│ compute_indicators │  │ summarise(returns,   │  │ correlation_matrix()   │
│ SMA EMA RSI MACD   │  │   ann_factor)        │  │ rolling_correlation()  │
│ Bollinger ATR ROC  │  │ Sharpe Sortino       │  │ covariance_matrix()    │
│ all causal         │  │ Calmar drawdown      │  │ returns, not prices    │
└─────────┬──────────┘  └──────────┬───────────┘  └────────────────────────┘
          │                        │
          ▼                        │
  ┌─ 5. SIGNALS ───────────────────┼───────────────────────── Phase 4 ⬜
  │  strategy.generate_signals(df, params) -> Series in {-1, 0, 1}
  │  SMA Crossover · EMA Trend · Momentum · Mean Reversion
  │  The target position at each bar's CLOSE.
  ▼                                │
  ┌─ 6. EXECUTE ───────────────────┼───────────────────────── Phase 3 ✅
  │  engine.run_backtest(df, signals, asset, config)
  │                                │
  │   signals.shift(1)  ◄── the bias guard: decide on t, act on t+1
  │   fill at open[t+1] ± slippage
  │   charge commission on notional, both sides
  │   size from equity × position_pct
  │   mark to market at every close
  │                                │
  │  -> BacktestResult: equity · returns · position · trade log
  │  engine.buy_and_hold(df, asset, config)  <- same engine, same costs
  ▼                                │
  ┌─ 7. ANALYSE ───────────────────┴───────────────────────── Phase 5 ⬜
  │  regime.regime_breakdown(key, returns)   <- Phase 2 ✅, wiring pending
  │      "when does this strategy actually work?"
  │  robustness.sweep(...)                   <- parameter grid -> Sharpe surface
  ▼
  ┌─ 8. SERVE ─────────────────────────────────────────────── Phase 6 ⬜
  │  FastAPI: /ohlcv /indicators /metrics /correlation
  │           /backtest /backtest/compare /backtest/robustness /regime
  ▼
  ┌─ 9. VISUALISE ─────────────────────────────────────────── Phase 6 ⬜
     React + Vite + TypeScript
     Overview · Risk · Correlation · Backtest · Research
```

### Running each stage

Every completed stage has a script that exercises it on real data and exits
non-zero if an invariant breaks — these are the phase gates, not just demos.

```bash
cd backend
./.venv/Scripts/python.exe scripts/bootstrap_data.py     # stages 1-3
./.venv/Scripts/python.exe scripts/analytics_report.py   # stages 4a-4c
./.venv/Scripts/python.exe scripts/backtest_report.py    # stages 6 + benchmark
./.venv/Scripts/python.exe -m pytest tests/ -q           # all 123 tests
```

### The one contract everything depends on

`position[t] == sign(signal[t-1])`, filled at `open[t]`.

A signal derived from bar *t*'s close cannot be acted on until bar *t+1* opens.
Every backtest number in the platform shifts if this changes, so it is pinned by
a dedicated test (`test_execution_lag_is_exactly_one_bar`) rather than left to
convention.

---

## Coverage

Assets span three distinct asset classes on purpose — the correlation and regime
analysis is only interesting because they behave differently.

| Asset | Ticker | Class | Rows | Range | Annualisation |
|---|---|---|---|---|---|
| Gold Futures | `GC=F` | Commodity | 2,514 | 2016-09-19 → 2026-09-18 | 252 |
| Bitcoin | `BTC-USD` | Crypto | 3,653 | 2016-09-19 → 2026-09-19 | 365 |
| NVIDIA | `NVDA` | Equity | 2,514 | 2016-09-19 → 2026-09-18 | 252 |

Aligned cross-asset panel: **2,511 common trading days.**

---

## Quick start

Requires Python 3.11+. No database, no Redis, no Docker.

```bash
cd backend && python -m venv .venv --system-site-packages && ./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

The market-data cache is committed to the repo, so the platform runs offline out
of the box. To verify the pipeline against the committed cache:

```bash
cd backend && ./.venv/Scripts/python.exe scripts/bootstrap_data.py
```

To re-fetch live data from Yahoo (overwrites the cache):

```bash
cd backend && ./.venv/Scripts/python.exe scripts/bootstrap_data.py --refresh
```

---

## Layout

```
backend/
  app/
    config.py            Asset registry + engine defaults
    data/
      sources.py         Yahoo chart API client (retry, split adjustment)
      validate.py        OHLC invariants, cleaning, quality report
      store.py           CSV cache + aligned multi-asset panel
    analytics/
      indicators.py      SMA, EMA, RSI, MACD, Bollinger, ATR, ROC
      metrics.py         Returns, volatility, Sharpe, Sortino, Calmar, drawdown
      correlation.py     Correlation matrix, covariance, rolling correlation
      regime.py          Bull/bear + volatility regime classification
    backtest/
      engine.py          Bar-by-bar execution, costs, trade log, benchmark
  data_cache/            Committed CSV market data
  tests/                 123 tests: hand-computed values, causality + lag proofs
  scripts/
    bootstrap_data.py    Fetch, validate, cache, self-check
    analytics_report.py  Real-data sweep with plausibility checks
    backtest_report.py   Engine run with invariant checks + cost sweep
docs/
  problem-statement.pdf
  PROJECT_PLAN_FIN_original.md
```

**Layering rule:** `data` does not import `analytics`; `analytics` does not
import `backtest`; nothing below the API layer imports FastAPI. The quant core
is importable and testable without a running server.

---

## Design notes

Four decisions that materially affect correctness.

**Per-asset annualisation.** Bitcoin trades 365 days a year; gold futures and
NVIDIA do not. The annualisation factor is a property of the asset, never a
hard-coded 252. Using 252 for crypto understates its volatility by roughly 20%.

**Calendar alignment by intersection.** Cross-asset correlation is computed on an
inner join of trading calendars, not a forward fill. Forward-filling equities
across weekends — where BTC keeps trading — injects bars that are flat by
construction and drags measured correlation toward zero.

**Expanding, not full-sample, regime thresholds.** Volatility terciles at bar
*t* are computed from history up to *t* only, so a 2016 bar is never labelled
using 2020 information. A visible consequence: regime shares are not an even
33/33/33 split. Gold sits in `high_vol` 52.7% of the time because its volatility
trended up over the decade, while BTC sits in `low_vol` 46.9% because its
trended down. Full-sample terciles would force an even split and erase exactly
that signal.

**Split adjustment across all OHLC fields.** The adjustment factor derived from
the adjusted close is applied to open, high and low as well. Adjusting only the
close would corrupt open-based fills at every split. NVIDIA correctly reads
$1.56 in 2016 — the 40×-split-adjusted value of its then-$62 price.

---

## Bias controls

The problem statement calls out four failure modes. Each gets a structural
defence rather than a disclaimer.

| Risk | Defence |
|---|---|
| **Look-ahead bias** | A signal computed on bar *t* is shifted one bar and filled at the **open of t+1**. Trading on a close you could not have known is structurally impossible, and a regression test asserts it. |
| **Data leakage** | Indicators use only rolling/ewm windows. Regime thresholds use *expanding* quantiles, so a 2016 bar is never labelled from 2020 information. |
| **Unrealistic execution** | Commission and slippage are charged on notional on both sides of every trade, with slippage always moving price against the trade. The benchmark pays the same entry cost. |
| **Over-optimisation** | Parameter sweeps report the entire Sharpe surface, so an isolated spike is visibly a spike rather than a headline number. |

---

## Data quality

Reported rather than silently smoothed:

- Gold has **82 flat bars** (3.3%) where open = high = low = close, all before
  2020-03-27 — thin front-month futures days. Genuine data. An open-based fill
  equals the close on those days, which is the conservative direction.
- Gold dropped **3 null-close rows** during validation.
- BTC retains 69% of its rows in the aligned panel; weekends are removed so
  cross-asset comparisons are like-for-like. Single-asset BTC analysis uses the
  full series.

---

## Dependencies

Deliberately minimal — six packages, no database, no cache server, no TA-Lib.

```
fastapi · uvicorn · pandas · numpy · requests · pytest
```

Market data comes from the Yahoo Finance chart API via `requests`. See decision
**D1** in [`PROJECT_PLAN.md`](PROJECT_PLAN.md#6-decision-log) for why `yfinance`
and `pyarrow` were dropped.
