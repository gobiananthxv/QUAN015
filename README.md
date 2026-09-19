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
| 2 | Analytics engine | 🔨 Drafted, verification pending |
| 3 | Backtesting engine | ⬜ Pending |
| 4 | Strategies | ⬜ Pending |
| 5 | Regime + robustness | ⬜ Pending |
| 6 | API + dashboard | ⬜ Pending |
| 7 | Tests, docs, demo | ⬜ Pending |

Full phase breakdown and decision log: [`PROJECT_PLAN.md`](PROJECT_PLAN.md).

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
  data_cache/            Committed CSV market data
  scripts/
    bootstrap_data.py    Fetch, validate, cache, self-check
docs/
  problem-statement.pdf
  PROJECT_PLAN_FIN_original.md
```

**Layering rule:** `data` does not import `analytics`; `analytics` does not
import `backtest`; nothing below the API layer imports FastAPI. The quant core
is importable and testable without a running server.

---

## Design notes

Three decisions that materially affect correctness.

**Per-asset annualisation.** Bitcoin trades 365 days a year; gold futures and
NVIDIA do not. The annualisation factor is a property of the asset, never a
hard-coded 252. Using 252 for crypto understates its volatility by roughly 20%.

**Calendar alignment by intersection.** Cross-asset correlation is computed on an
inner join of trading calendars, not a forward fill. Forward-filling equities
across weekends — where BTC keeps trading — injects bars that are flat by
construction and drags measured correlation toward zero.

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
