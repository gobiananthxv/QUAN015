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
| [What you get](#what-you-get) | The five views and what each answers |
| [How it works](#how-it-works) | The pipeline, stage by stage |
| [What the platform found](#what-the-platform-found) | Real results, including the unflattering ones |
| [Why you can trust the numbers](#why-you-can-trust-the-numbers) | Bias controls and the decisions behind them |
| [Project layout](#project-layout) | Where everything lives |
| [Extending it](#extending-it) | Adding assets and strategies |
| [Reference](#reference) | Endpoints, dependencies, data quality, troubleshooting |
| [DEMO.md](DEMO.md) | A scripted three-minute walkthrough |
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | Phase plan and full decision log |

**Status:** all seven phases complete · **262 tests passing** · all 19
problem-statement requirements delivered.

---

## Quick start

**Requirements:** Python 3.11+ and Node 18+. No database, no Redis, no Docker.

Ten years of market data is committed to the repository, so nothing below needs
an internet connection.

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

Re-fetches from Yahoo and overwrites the committed cache:

```bash
cd backend && .venv/bin/python scripts/bootstrap_data.py --refresh
```

</details>

---

## What you get

Five views. Each answers one question.

### 1 · Overview — *what has this asset done?*

Log-scale price with SMA 50/200 overlaid, volume, and green bands marking the
periods a crossover strategy would have held a position.

Log scale matters: on a linear axis, a decade of NVIDIA compresses its first
eight years into a flat line against the last two.

### 2 · Risk — *how much pain did that involve?*

Sharpe, Sortino, Calmar, volatility, maximum drawdown and how long it lasted —
plus the cumulative return, the underwater drawdown curve, and rolling
volatility.

### 3 · Correlation — *do these assets actually diversify each other?*

A correlation matrix computed on **returns**, not price levels, plus rolling
correlation with a selectable window.

The rolling view is the point. A single correlation number hides that the same
pair swings from −0.47 to +0.62 over a decade.

### 4 · Backtest — *what would this strategy have done?*

Pick a strategy, edit its parameters, set your capital, commission and slippage,
and run. You get the equity curve against buy-and-hold, a full metric
comparison, and a complete trade log — entry, exit, size, gross P&L, costs, net.

Both the strategy and the benchmark pay the same costs.

### 5 · Research — *should I believe any of this?*

The part most backtesting tools skip:

- **Parameter surface** — a Sharpe heatmap across the whole parameter grid, not
  just the best cell, with a plain-English robustness verdict
- **Cost sensitivity** — how the result decays as friction rises
- **Period stability** — five consecutive windows, signals regenerated in each
- **Regime attribution** — where the strategy beats the benchmark, and at what
  exposure

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
| 5 | **Signals** | `strategy.generate_signals(df)` | Target position at each bar's **close**, in `{-1, 0, 1}` |
| 6 | **Execute** | `engine.run_backtest(...)`<br>`engine.buy_and_hold(...)` | Lags signals one bar, fills at the next open ± slippage, charges commission both sides, sizes from equity, marks to market every close |

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
| 9 | **Visualise** | `npm run dev --prefix frontend` | React + Vite + TypeScript, five views |

### The one contract everything depends on

```
position[t] == sign(signal[t-1]),  filled at open[t]
```

A signal derived from bar *t*'s close cannot be acted on until bar *t+1* opens.
Every backtest number shifts if this changes, so it is pinned by a dedicated
test (`test_execution_lag_is_exactly_one_bar`) rather than left to convention.

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
| BTC | 13,236% | 63.07% | 66.81% | 1.04 | −83.4% | 1,079 d |
| NVDA | 14,130% | 64.41% | 50.05% | 1.20 | −66.3% | 373 d |

### Correlation is not a constant

Full-sample daily-return correlation is low across every pair — GOLD~BTC 0.10,
GOLD~NVDA 0.04, BTC~NVDA 0.22. But the rolling 90-day figure swings from **−0.47
to +0.62**. Diversification that holds in calm markets can disappear exactly
when it is needed.

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

### Reading those tables honestly

**Buy-and-hold wins on return in two of three assets.** We report that as-is
rather than tuning until the strategies win. On assets that trended this hard
for a decade, sitting out of the market costs more than the crashes it avoids.

**Every strategy reduced drawdown on BTC and NVDA.** NVDA's SMA crossover gives
up half the return but cuts the worst drawdown from −66% to −38%. That is a
different objective, not a worse one.

**One genuine winner: Momentum on BTC** — 13,485% against the benchmark's
13,216%, with a higher Sharpe and a shallower drawdown, in 18 trades.

**Mean reversion lost money on BTC** (−50.8%). Buying dips works until the dip
keeps going. It loses at zero cost too (−42.1%), so this is the rule failing,
not friction.

### Does any of it survive scrutiny?

Sharpe across a wide parameter grid, summarised as `robustness` = median ÷ best.
Near 1.0 means the surface is flat and the parameter choice barely matters; near
0 means one cell carries the whole result.

| Strategy | GOLD | BTC | NVDA | Verdict |
|:--|--:|--:|--:|:--|
| SMA Crossover | 0.83 | 0.88 | 0.87 | robust — 100% of cells positive on all three |
| EMA Trend | 0.58 | 0.91 | 0.85 | robust on BTC/NVDA, moderate on gold |
| Momentum | 0.82 | 0.90 | 0.89 | robust across the board |
| Mean Reversion | **0.10** | **0.24** | 0.63 | **fragile — treat as over-fitted** |

**The tool flags our own weakest strategy.** Mean Reversion's headline numbers
come from a handful of grid cells, consistent with it losing money on BTC.

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
| **Data leakage** | Indicators use only rolling and ewm windows; regime thresholds use expanding quantiles. 14 causality tests confirm that appending future bars never changes a past value — 9 indicators, 4 strategies, and the regime labels. |
| **Unrealistic execution** | Commission and slippage charged on notional on both sides, with slippage always moving price against the trade. The benchmark pays the same entry cost. |
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

### Testing

**262 tests.** Values are hand-computed against known answers, not snapshotted
from the implementation — a snapshot test locks in whatever bug exists.

| Suite | Tests | Covers |
|:--|--:|:--|
| `test_indicators.py` | 31 | Hand-computed EMA recursion, Bollinger population std, Wilder ATR, plus 9 causality tests |
| `test_metrics.py` | 32 | Closed-form cases: compounding, CAGR doubling, Sharpe by formula, hand-built drawdown paths |
| `test_correlation_regime.py` | 27 | Panel alignment, matrix symmetry, regime label rules, regime causality |
| `test_engine.py` | 33 | Look-ahead, cost arithmetic to the cent, equity curve vs trade log agreement |
| `test_strategies.py` | 51 | Known-answer price paths, parameter validation, strategy causality |
| `test_robustness.py` | 35 | Plateau detection against constructed surfaces with known answers |
| `test_api.py` | 53 | Every endpoint parsed with a **strict** JSON parser that rejects `Infinity`/`NaN` |

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

Return the target position at each bar's **close** in `{-1, 0, 1}`. The engine
applies the execution lag — a strategy must never lag its own signals, or it
double-lags. The strategy dropdowns, comparison runs and robustness sweeps all
update automatically.

---

## Reference

### API endpoints

Interactive docs at `http://localhost:8000/docs`.

| Method | Path | Returns |
|:--|:--|:--|
| `GET` | `/health` | Liveness, asset list, disclaimer |
| `GET` | `/api/assets` | Asset registry and cache status |
| `GET` | `/api/strategies` | Strategy catalogue with defaults |
| `GET` | `/api/ohlcv?asset=` | Validated bars + quality report |
| `GET` | `/api/indicators?asset=` | All indicators, configurable periods |
| `GET` | `/api/metrics?asset=` | Risk summary + plot series |
| `GET` | `/api/correlation?window=` | Matrix + rolling correlation |
| `GET` | `/api/rolling-correlation?a=&b=` | One pair's rolling correlation |
| `GET` | `/api/regime?asset=` | Regime labels over time |
| `GET` | `/api/panel` | Aligned multi-asset close panel |
| `GET` | `/api/backtest/regime-attribution` | Strategy vs benchmark by regime |
| `POST` | `/api/backtest` | One strategy + benchmark + trade log |
| `POST` | `/api/backtest/compare` | Every strategy against one benchmark |
| `POST` | `/api/backtest/robustness` | Surface, plateau verdict, cost + period sweeps |

### Dependencies

Seven packages. No database, no cache server, no TA-Lib.

```
fastapi · uvicorn · pandas · numpy · requests · pytest · httpx
```

Market data comes from the Yahoo Finance chart API via `requests`. See decision
**D1** in [`PROJECT_PLAN.md`](PROJECT_PLAN.md#6-decision-log) for why `yfinance`
and `pyarrow` were dropped.

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
| Want to check everything still works | — | `./verify.sh` |

### Out of scope

Listed as *Future Scope* in the problem statement and correctly deferred:
portfolio optimisation, Monte Carlo simulation, Value at Risk, ML-based regime
detection, paper trading, real-time data, AI research assistance.
