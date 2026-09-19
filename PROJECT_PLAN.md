# QMAFIB — Implementation Plan

**Quantitative Multi-Asset Financial Intelligence & Backtesting Platform**
Hackathon build · 24 hours · target: HackHere FinTech track

> This is the **active** plan. The original 16-week / 5–6-person enterprise plan is
> preserved unchanged at [`docs/PROJECT_PLAN_FIN_original.md`](docs/PROJECT_PLAN_FIN_original.md)
> for reference. Where the two disagree, **this document wins.**

---

## 1. What we are building

A single platform that ingests 10 years of daily history for three assets across
three asset classes, computes quantitative indicators and risk metrics, measures
cross-asset correlation, backtests four trading strategies against a
buy-and-hold benchmark with realistic costs, attributes performance to market
regimes, and presents all of it in an interactive dashboard.

**Assets:** Gold (`GC=F`, commodity) · Bitcoin (`BTC-USD`, crypto) · NVIDIA (`NVDA`, equity)

---

## 2. Requirement coverage

Every requirement from the problem statement, mapped to where it is delivered.

| # | Problem-statement requirement | Phase | Status |
|---|---|---|---|
| 1 | Multi-asset data collection & normalisation | 1 | ✅ Done |
| 2 | SMA, EMA | 2 | 🔨 Drafted |
| 3 | Daily & cumulative returns | 2 | 🔨 Drafted |
| 4 | Historical & annualised volatility | 2 | 🔨 Drafted |
| 5 | Sharpe ratio | 2 | 🔨 Drafted |
| 6 | Maximum drawdown | 2 | 🔨 Drafted |
| 7 | Rolling returns | 2 | 🔨 Drafted |
| 8 | Correlation matrix + rolling correlation | 2 | 🔨 Drafted |
| 9 | Strategy engine: SMA Crossover | 4 | ⬜ Pending |
| 10 | Strategy engine: EMA Trend | 4 | ⬜ Pending |
| 11 | Strategy engine: Momentum | 4 | ⬜ Pending |
| 12 | Strategy engine: Mean Reversion | 4 | ⬜ Pending |
| 13 | Realistic simulation: initial capital, position sizing, transaction costs, entry/exit prices, portfolio value, trade count | 3 | ⬜ Pending |
| 14 | Strategy vs Buy-and-Hold benchmark | 3 | ⬜ Pending |
| 15 | Robustness testing (parameter / cost / period sweeps) | 5 | ⬜ Pending |
| 16 | Market regime analysis (bull / bear / high-vol / low-vol) | 5 | 🔨 Drafted |
| 17 | Dashboard: prices, SMA/EMA, returns & volatility, drawdowns, correlation heatmap, buy/sell signals, equity curves, strategy vs benchmark | 6 | ⬜ Pending |
| 18 | Bias minimisation: look-ahead, data leakage, unrealistic execution, over-optimisation | 3 + 7 | ⬜ Pending |
| 19 | "Not a guarantee of future returns" disclaimer | 7 | ⬜ Pending |

**Explicitly out of scope** (listed as *Future Scope* in the problem statement,
and correctly deferred): portfolio optimisation, Monte Carlo, VaR, ML-based
regime detection, paper trading, real-time data, AI research assistant.

---

## 3. Scope decisions — what we deliberately did NOT build

The original plan specified a production system. This is a 24-hour build, so the
following were cut. Each cut is a considered trade-off, not an oversight.

| Cut | Replaced with | Why |
|---|---|---|
| 5 microservices (ports 8000–8003) | One FastAPI process, service boundaries as Python modules | Same separation of concerns, no orchestration cost |
| PostgreSQL + SQLAlchemy + Alembic | CSV files in `backend/data_cache/` | ~2.5k rows per asset; read cost is milliseconds |
| Redis + Celery workers | `functools.lru_cache` | Backtests run in ~10 ms; a cache server adds latency and a process |
| Docker / Kubernetes / CI-CD | `run` scripts | Nothing is deployed to a cluster at a demo table |
| Prometheus / Grafana / ELK | stdout logging | No production traffic to observe |
| TA-Lib | Direct pandas/NumPy implementations | C build on Windows is a known time sink; ~150 lines replaces it |
| `yfinance` | Direct Yahoo chart API via `requests` | See §6 — this one was forced on us |
| Auth, rate limiting, security testing | — | No users, no threat model |
| 170+ tests, >80% coverage | ~20 targeted tests on the maths that must be right | Correctness where it counts, not coverage theatre |
| ADX, Stochastic, OBV, CMF, Kelly Criterion | — | Not in the problem statement |

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────────┐
│  React + Vite + TypeScript dashboard                     │
│  Overview · Risk · Correlation · Backtest · Research     │
└───────────────────────────┬──────────────────────────────┘
                            │ REST (JSON)
┌───────────────────────────▼──────────────────────────────┐
│  FastAPI  (single process)                               │
├──────────────────────────────────────────────────────────┤
│  app/backtest/   engine · strategies · robustness        │
│  app/analytics/  indicators · metrics · correlation      │
│                  · regime                                │
│  app/data/       sources · validate · store              │
└───────────────────────────┬──────────────────────────────┘
                            │
              ┌─────────────┴──────────────┐
              │  data_cache/*.csv          │
              │  (committed to the repo)   │
              └─────────────┬──────────────┘
                            │ cold cache only
                   Yahoo Finance chart API
```

**Layering rule:** `data` knows nothing of `analytics`; `analytics` knows nothing
of `backtest`; nothing below the API layer imports FastAPI. This keeps the quant
core importable and testable without a running server.

---

## 5. Phase plan

Times are estimates against a 24-hour budget, ~22 h planned, ~2 h buffer.

### Phase 0 — Scaffold · 45 min · ✅ COMPLETE
Repo layout, dependency set, virtualenv, `.gitignore`.

### Phase 1 — Data pipeline · 2 h · ✅ COMPLETE
Fetch → validate → cache → align.

- `app/data/sources.py` — Yahoo chart API client with retry/backoff; split &
  dividend adjustment applied to all four OHLC fields, not just close.
- `app/data/validate.py` — OHLC invariant repair, null/non-positive drops,
  dedupe, sort, negative-volume zeroing, gap detection. Returns a quality report.
- `app/data/store.py` — CSV cache + the aligned multi-asset panel.
- `scripts/bootstrap_data.py` — one-shot fetch with self-checks.

**Delivered:** GOLD 2,514 rows · BTC 3,653 · NVDA 2,514, all 2016-09-19 → 2026-09-18/19.
Aligned panel: 2,511 common trading days.

### Phase 2 — Analytics engine · 3 h · 🔨 CODE DRAFTED, NOT VERIFIED
- **Indicators** (`indicators.py`): SMA, EMA, RSI, MACD, Bollinger (+ z-score), ATR, ROC.
- **Metrics** (`metrics.py`): daily/cumulative/rolling returns, historical &
  annualised volatility, Sharpe, Sortino, Calmar, max drawdown, drawdown
  duration, underwater curve.
- **Correlation** (`correlation.py`): static matrix, covariance, rolling pairwise.
- **Regime** (`regime.py`): trend (200-SMA) and volatility (expanding terciles) labels.

**Verification gate:**
1. Indicators vs hand-computed values on a known series.
2. Metrics vs closed-form cases (constant-return Sharpe, hand-built drawdown path, CAGR round-trip).
3. **Causality test** — appending future bars must not change any past indicator value. The backtester's correctness depends on this.
4. Per-asset annualisation actually differs (BTC 365 vs NVDA 252).
5. Full sweep over all three real assets; metric table reviewed for sanity.

### Phase 3 — Backtesting engine · 3.5 h · ⬜ PENDING
The core of the project. Explicit bar-by-bar loop, not vectorised — slower, but
it produces a real auditable trade log.

Design rules (these answer the problem statement's *Financial Considerations*):

| Risk named in the brief | Structural defence |
|---|---|
| Look-ahead bias | Signal computed on bar *t* is **shifted one bar** and filled at the **open of t+1**. Enforced by a regression test. |
| Data leakage | All indicators are causal (rolling/ewm only); regime thresholds are *expanding*, never full-sample. |
| Unrealistic execution | Commission (bps) + slippage (bps) charged on notional, both sides. Slippage always moves price against the trade. |
| Over-optimisation | Parameter sweep surfaces the whole Sharpe surface (Phase 5), so a lone spike is visible as a spike. |

Also: benchmark runs through the *same* engine and pays the *same* entry cost,
so the comparison is like-for-like.

Outputs: equity curve, per-bar position, trade log (entry/exit date & price,
size, gross P&L, costs, net P&L, return %, bars held), and a metric block
including win rate, profit factor, exposure and total costs paid.

### Phase 4 — Strategies · 1.5 h · ⬜ PENDING
Thin `Strategy` base class — `generate_signals(df, params) -> Series[-1,0,1]`.
Four implementations, ~25 lines each: SMA Crossover, EMA Trend (+ ROC
confirmation), Momentum (ROC threshold), Mean Reversion (Bollinger z-score).

### Phase 5 — Regime attribution & robustness · 2 h · ⬜ PENDING
- Slice each strategy's returns by regime → "when does this strategy actually work?"
- Parameter grid sweep → Sharpe heatmap. A smooth plateau means robust; an
  isolated spike means overfit. This is the visual argument against over-optimisation.
- Cost sensitivity and sub-period sweeps.

### Phase 6 — API + dashboard · 5 h · ⬜ PENDING
Nine endpoints, no more:

```
GET  /assets                    GET  /correlation
GET  /ohlcv                     GET  /rolling-correlation
GET  /indicators                POST /backtest
GET  /metrics                   POST /backtest/compare
GET  /regime                    POST /backtest/robustness
```

Five dashboard views: **Overview** (price + SMA/EMA + volume + signal markers) ·
**Risk** (returns, rolling vol, underwater drawdown) · **Correlation** (heatmap +
rolling) · **Backtest** (config → equity vs benchmark, metrics, trade log) ·
**Research** (regime table + robustness heatmap).

*Known task:* `Sortino` and `profit_factor` can legitimately be `inf`, which is
not JSON-serialisable. A sanitiser is required at the API boundary.

### Phase 7 — Harden & demo · 2.5 h · ⬜ PENDING
~20 pytest cases on the maths that must be correct, including the look-ahead
regression test. README, architecture diagram, persistent research-use
disclaimer in the UI, rehearsed 3-minute demo.

---

## 6. Decision log

Recorded so the reasoning survives the hackathon.

**D1 — Dropped `yfinance` and `pyarrow` (Phase 1).**
PyPI was throttled to the point that neither package installed after ~12 minutes,
while Yahoo's API itself responded in under a second. Rather than wait, we call
the chart endpoint directly with `requests` and cache as CSV. Upside: fewer
dependencies, no wrapper-version churn, explicit control of retries and timeouts,
and fetch failures raise loudly instead of silently writing an empty frame.

**D2 — Virtualenv created with `--system-site-packages`.**
pandas, numpy, fastapi, uvicorn, pydantic and requests were already present
system-wide. Inheriting them avoided re-downloading ~60 MB over a slow link.

**D3 — Inner join, not forward-fill, for the multi-asset panel.**
BTC trades 365 days a year; gold futures and NVDA do not. Forward-filling the
equities across weekends injects bars that are flat by construction, which drags
measured correlation toward zero. We intersect the calendars instead — every row
is a day on which *all* selected assets actually traded. Verified: the two
approaches produce measurably different correlations.

**D4 — Adjusted close scaled across all OHLC fields.**
Using an adjusted close alongside raw open/high/low would corrupt open-based
fills at every split. We derive the adjustment factor and apply it to all four
price fields. Verified: NVDA reads $1.56 in 2016, the correct 40×-split-adjusted
value of its then-$62 price.

**D5 — CSV cache committed to the repository.**
The demo must not depend on venue wifi or on Yahoo being reachable.

---

## 7. Known data-quality notes

- **Gold has 82 flat bars** (3.3%) where open = high = low = close — thin
  front-month futures days, all before 2020-03-27. This is genuine data, not a
  pipeline fault. Consequence: an open-based fill equals the close on those days,
  which is the conservative direction. Left visible rather than silently smoothed.
- **BTC retains 69% of its rows** after calendar alignment. Expected — weekends
  are removed so cross-asset comparisons are like-for-like. Single-asset BTC
  analysis still uses the full 3,653-row series.

---

## 8. Success criteria

Realistic targets for a 24-hour build, replacing the original plan's
production SLOs.

- ✅ 10 years of validated history for 3 assets across 3 asset classes
- ⬜ All 7 required indicator/metric families computed and displayed
- ⬜ 4 strategies backtested with costs, sizing and a like-for-like benchmark
- ⬜ Look-ahead bias structurally prevented **and** proven by a regression test
- ⬜ Regime attribution and a robustness surface, both visualised
- ⬜ Dashboard covering all 8 required visualisations
- ⬜ Core maths covered by tests that verify values, not just absence of crashes
- ⬜ Runs end-to-end offline from the committed cache
