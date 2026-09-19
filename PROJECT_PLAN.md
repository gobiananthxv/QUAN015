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
| 2 | SMA, EMA | 2 | ✅ Done |
| 3 | Daily & cumulative returns | 2 | ✅ Done |
| 4 | Historical & annualised volatility | 2 | ✅ Done |
| 5 | Sharpe ratio | 2 | ✅ Done |
| 6 | Maximum drawdown | 2 | ✅ Done |
| 7 | Rolling returns | 2 | ✅ Done |
| 8 | Correlation matrix + rolling correlation | 2 | ✅ Done |
| 9 | Strategy engine: SMA Crossover | 4 | ✅ Done |
| 10 | Strategy engine: EMA Trend | 4 | ✅ Done |
| 11 | Strategy engine: Momentum | 4 | ✅ Done |
| 12 | Strategy engine: Mean Reversion | 4 | ✅ Done |
| 13 | Realistic simulation: initial capital, position sizing, transaction costs, entry/exit prices, portfolio value, trade count | 3 | ✅ Done |
| 14 | Strategy vs Buy-and-Hold benchmark | 3 | ✅ Done |
| 15 | Robustness testing (parameter / cost / period sweeps) | 5 | ✅ Done |
| 16 | Market regime analysis (bull / bear / high-vol / low-vol) | 5 | ✅ Done |
| 17 | Dashboard: prices, SMA/EMA, returns & volatility, drawdowns, correlation heatmap, buy/sell signals, equity curves, strategy vs benchmark | 6 | ✅ Done |
| 18 | Bias minimisation: look-ahead, data leakage, unrealistic execution, over-optimisation | 3 + 5 | ✅ Done (4 of 4) |
| 19 | "Not a guarantee of future returns" disclaimer | 7 | ✅ Done |

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
| PostgreSQL + SQLAlchemy + Alembic | CSV files in `backend/data_snapshot/` | ~2.5k rows per asset; read cost is milliseconds |
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
              │  data_snapshot/*.csv       │
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

### Phase 2 — Analytics engine · 3 h · ✅ COMPLETE
- **Indicators** (`indicators.py`): SMA, EMA, RSI, MACD, Bollinger (+ z-score), ATR, ROC.
- **Metrics** (`metrics.py`): daily/cumulative/rolling returns, historical &
  annualised volatility, Sharpe, Sortino, Calmar, max drawdown, drawdown
  duration, underwater curve.
- **Correlation** (`correlation.py`): static matrix, covariance, rolling pairwise.
- **Regime** (`regime.py`): trend (200-SMA) and volatility (expanding terciles) labels.

**Verification gate — passed.** 90 tests, all green:
1. ✅ Indicators vs hand-computed values (EMA recursion, Bollinger population std, Wilder ATR, ROC).
2. ✅ Metrics vs closed-form cases (compounding, CAGR doubling, Sharpe by formula, hand-built drawdown path).
3. ✅ **Causality** — 10 parametrised tests confirm no indicator's past value changes when future bars are appended, plus the same test for regime labels.
4. ✅ Per-asset annualisation confirmed to scale by √(365/252).
5. ✅ Real-data sweep via `scripts/analytics_report.py`, exit 0.

Run with `pytest tests/ -q` and `python scripts/analytics_report.py`.

### Phase 3 — Backtesting engine · 3.5 h · ✅ COMPLETE
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
size, gross P&L, commission, slippage, net P&L, return %, bars held), and a
metric block including win rate, profit factor, exposure and total costs paid.

**Verification gate — passed.** 33 engine tests (123 total), all green:
1. ✅ **Look-ahead** — `position[t] == sign(signal[t-1])` pinned by a dedicated
   test; a signal on the final bar never trades; truncating the future leaves
   past equity byte-identical.
2. ✅ **Arithmetic hand-verified** — frictionless round trip, commission on both
   sides, slippage direction, and `net = gross − commission − slippage` to the cent.
3. ✅ **Two independent accounts agree** — final equity equals initial capital
   plus the summed net P&L of every trade, on real data.
4. ✅ **Costs behave** — returns fall monotonically as friction rises (0→100 bps);
   frequent trading costs more than patient trading.
5. ✅ **Benchmark is honest** — buy-and-hold pays an entry cost and underperforms
   its frictionless self.
6. ✅ Shorts ignored unless enabled; direction flips close and reopen correctly.

Performance: **5–9 ms** over a decade of daily bars, well inside the 5 s target.

An independent hand-check of gold's first trade: gross 82.4254 × (1267.20 −
1211.40) = 4,599; costs 204.3 commission + 102.2 slippage = 306; net 4,293 —
matching the engine exactly.

### Phase 4 — Strategies · 1.5 h · ✅ COMPLETE
Thin `Strategy` base class — `generate_signals(df) -> Series[-1,0,1]` — plus a
registry so the API and dashboard can enumerate strategies without hard-coding
them. Four implementations: SMA Crossover, EMA Trend (+ ROC confirmation),
Momentum (ROC threshold), Mean Reversion (Bollinger z-score, stateful).

**Verification gate — passed.** 51 strategy tests (174 total):
1. ✅ **Contract** — every strategy emits only `{-1, 0, 1}`, aligns to the input
   index, never emits NaN, and is flat during its warm-up.
2. ✅ **Causality** — 4 more tests confirm appending future bars changes no past
   signal, closing the loop: causal indicators → causal strategies → lagged engine.
3. ✅ **Known-answer paths** — each strategy checked against a constructed price
   path where the correct signal is known in advance (sustained uptrend, sustained
   downtrend, trend reversal, threshold boundary, dip-and-recover).
4. ✅ **Parameter validation** — impossible combinations raise rather than
   silently misbehave (`fast >= slow`, `entry_z <= 0`, unreachable `exit_z`).
5. ✅ **Typo'd parameters are discarded, not silently honoured** — a misspelled
   key must not look like it took effect.
6. ✅ **No degenerate strategies** — exposure strictly between 1% and 99%; a
   strategy always or never in the market is a bug or a benchmark.

Mean Reversion is deliberately stateful: being oversold is an *event*, not a
persistent condition, so it holds between entry and exit. A test proves it holds
through bars where the entry trigger is already inactive.

**Post-verification audit found a specification defect** (not an implementation
one — SMA Crossover was cross-checked against an independent reimplementation
and matched exactly). EMA Trend and Momentum tested strict inequalities against
noisy quantities and whipsawed: 50% of gold's EMA Trend trades lasted ≤2 bars,
and costs consumed 67% of its gross return. Both now use a confirmation band
(see **D13**).

### Phase 5 — Regime attribution & robustness · 2 h · ✅ COMPLETE
- Slice each strategy's returns by regime → "when does this strategy actually work?"
- Parameter grid sweep → Sharpe heatmap. A smooth plateau means robust; an
  isolated spike means overfit. This is the visual argument against over-optimisation.
- Cost sensitivity and sub-period sweeps.

### Phase 6 — API + dashboard · 5 h · ✅ COMPLETE
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

**Verification gate — passed.** 53 API tests (262 total) plus a live browser walkthrough:
1. ✅ Every endpoint's raw body parses with a **strict** JSON parser that rejects
   `Infinity`/`NaN` — Python's `json.loads` accepts both by default, so the
   permissive parser would have hidden the bug that breaks `JSON.parse`.
2. ✅ The `inf` case is proven reachable, so test 1 cannot pass vacuously.
3. ✅ 404 on unknown asset/strategy, 422 on invalid strategy params and configs.
4. ✅ Warm-up `NaN` arrives as `null`, not as zero.
5. ✅ All five views rendered and walked in a real browser; console clean.

The `inf`/`NaN` sanitiser flagged back in Phase 2 is `app/api/serialise.py`.
`inf` becomes `null` rather than a large sentinel: a sentinel would be plotted
as a real value and silently distort a chart. The dashboard confirms this
end-to-end — NVDA's crossover has no losing trades, so its profit factor is
`inf`, and the UI shows an em dash.

### Phase 7 — Harden & demo · 2.5 h · ✅ COMPLETE
Delivered: `run.sh` / `run.ps1` (one command, bootstraps deps if missing),
`verify.sh` (every gate in one run), [`DEMO.md`](DEMO.md) (scripted walkthrough
with anticipated questions and a failure-recovery table), final README pass.

The disclaimer appears in three places: a persistent banner on every dashboard
view, the `/health` response, and the OpenAPI description at `/docs`.

**Verification gate — passed.**
1. ✅ Dead-code audit: one genuinely unused function (`store.refresh_all`) found
   and removed; no unused imports, no TODO/FIXME left in the tree.
2. ✅ **Every numeric claim in `DEMO.md` checked against the live API.** Two were
   wrong and were corrected — see below.
3. ✅ The scripted demo path was walked in a real browser end to end.
4. ✅ Responsive check at 375 px: no horizontal overflow; wide tables scroll
   inside their own container.
5. ✅ `./verify.sh` → 262 tests plus all five scripts, green from a clean shell.

**The demo script contained two false claims, caught by checking rather than
assuming.** It said switching to Mean Reversion on NVDA would show the *fragile*
verdict — on NVDA that strategy actually scores 0.63 and reads *robust*. The
fragile verdict lives on GOLD (0.10) and BTC (0.24). The cost-cliff claim ("goes
negative at 25 bps") was also GOLD's, not NVDA's. The script now switches asset
to GOLD at that point, which is what the numbers support. Separately, the
causality-test count was stated as eleven; it is fourteen.

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

**D6 — Two correlation sample policies, deliberately (Phase 2).**
The correlation *matrix* uses the intersection of all assets' calendars, because
a matrix built from different per-pair samples is not internally consistent.
*Pairwise rolling* correlation uses just that pair's calendar, which yields more
observations and a better estimate. The two therefore rest on slightly different
samples (2,514 vs 2,511 rows for GOLD/NVDA). `sample_size()` reports the sample
actually used, so the difference is visible rather than silent.

**D7 — Float tolerance on every zero-division guard (Phase 2).**
A genuinely constant return series has a standard deviation of ~1e-18, not 0.0.
An `== 0` guard lets that through and divides by it. Guards now compare against
`ZERO_TOL = 1e-12`.

**D8 — Explicit bar loop instead of vectorised position × returns (Phase 3).**
The vectorised form is a few lines and roughly 50× faster, but it yields no
trade log — no entry price, no per-trade cost, no holding period — and the brief
asks for exactly those. At 5–9 ms per decade-long run the speed is irrelevant,
and the loop's arithmetic can be audited line by line against the equity curve.

**D9 — A position still open at the final bar is reported, not force-closed.**
Force-closing invents an exit the strategy never signalled and flatters or
punishes the result arbitrarily. Open trades are marked to market, included in
equity, and counted separately as `num_open_trades`, so `num_trades` means
*completed round trips*. Buy-and-hold therefore reports 0 trades and 1 open
position, which is literally what it does.

**D30 — The price chart zooms, and every figure follows the window (post-Phase 7).**
Buy/sell markers are useless at full extent: 2,315 bars compress four fills into
a few pixels. A Recharts brush plus trailing-window presets makes them legible.
The part that matters is that zooming is not cosmetic — the toolbar recomputes
the period return, fill counts and time invested for whatever is on screen, the
volume panel slices to the same range, and a fills table appears listing the
trades that opened *or closed* inside the window. Magnifying a picture answers
nothing; recomputing against it answers "what happened here?".

**D27 — Shorts pay a borrow fee (post-Phase 7).**
`allow_short` existed but holding a short cost nothing: a 300-bar short on a
flat price finished at exactly its starting equity. Real shorts pay borrow for
every day they are open. `borrow_bps_annual` (default 50 bps, a typical
easy-to-borrow rate) is charged per bar on the position's current notional and
de-annualised with the *asset's own* calendar, so a crypto short is not billed
an equity year's worth of days.

**D28 — The benchmark is always fully invested (post-Phase 7).**
Exposing `position_pct` in the UI surfaced a real bug: buy-and-hold inherited
it, so halving the strategy's size halved the benchmark too and the strategy
never looked any worse — the yardstick shrank with it. Buy-and-hold now pins
`position_pct` to 1.0 while still paying the caller's commission and slippage,
so the cost treatment stays like-for-like and the reference stays fixed.

**D29 — Both servers hot-reload (post-Phase 7).**
Three separate debugging detours traced back to the API serving stale code
while returning 200. The dashboard already hot-reloaded; the API now does too,
and the run scripts refuse to start on an occupied port. The two together make
"am I looking at my change?" answerable.

**D24 — Refresh reasons in days, because the data is daily (post-Phase 7).**
The provider publishes one bar per day, so re-downloading more often cannot
produce a different result — it spends a network round trip rewriting identical
rows. An asset fetched within 24 hours is skipped and *reported as skipped*
rather than folded into successes, so pressing Refresh twice says "already
current" instead of pretending to have worked. `force` overrides, which is what
you want after a provider outage or a bad partial write.

**D25 — A sub-period regenerates its signals rather than slicing a full run (post-Phase 7).**
The problem statement lists "backtesting periods" alongside parameters and costs
as something the user must be able to vary. Slicing a full-history signal series
would let indicator values at the window's start carry information from before
it — fine for a chart, wrong for an out-of-sample test. `window()` slices the
price frame *first*, so warm-up happens inside the window. The benchmark is
restricted to the same range; comparing a windowed strategy against a
full-history benchmark would silently compare two different periods.

**D26 — The run scripts refuse to start on an occupied port (post-Phase 7).**
Twice during development uvicorn failed to bind, exited quietly, and left an
older process serving stale code while both URLs still returned 200 — so edits
appeared to do nothing. The scripts now probe both IPv4 and IPv6 (uvicorn binds
the former, Vite the latter) and fail with an explicit message and a suggested
alternative port.

**D22 — `data_cache/` renamed `data_snapshot/`, because it was never a cache (Phase 7).**
A cache implies a TTL, expiry and invalidation. This has none: it never expires
and never re-checks. Calling it a cache invited the reasonable question "so is
the app not actually fetching data?" — the honest answer being that it reads
committed CSVs and only fetches on an explicit refresh. The directory, the
config constant (`SNAPSHOT_DIR`) and the docs now say what it is.

**D23 — Exactly one endpoint may touch the network (Phase 7).**
`POST /api/data/refresh` re-downloads and overwrites the snapshot. Every other
endpoint is satisfiable from disk, and a test proves it: it replaces the fetcher
with a function that raises, then exercises every read endpoint plus a backtest.
Refresh collects failures per asset rather than aborting, returns 502 only if
*every* asset failed, and a further test confirms a failed refresh leaves the
previous snapshot fully usable — a provider outage must not take the platform
down with it.

**D20 — Non-finite numbers cross the wire as `null`, never as a sentinel (Phase 6).**
`inf` (Sortino with no losing day, profit factor with no losing trade) and `NaN`
(indicator warm-up) are correct answers, not errors. Python writes them as bare
`Infinity`/`NaN` tokens that `JSON.parse` rejects outright. Substituting a large
number instead would be worse: charts would plot it as real data. `null` is
skipped by every charting library and reads honestly as "undefined here". The
API tests parse raw bytes with `parse_constant` set to raise, so a regression
fails loudly rather than only breaking the browser.

**D21 — Backtest parameters are passed explicitly, not read from state (Phase 6).**
The Backtest view's first run silently never fired: one effect set the strategy
defaults and another triggered the run, and the run read `params` from state
that had not updated yet. `runWith(params, config)` takes them as arguments, so
the initial render and the manual button share one code path with no race.

**D17 — Excess return is geometric, not arithmetic (Phase 5, post-audit fix).**
`strategy_total − benchmark_total` is meaningless once returns compound large.
NVDA's 2022-2024 window reads −639% that way, suggesting a catastrophic loss,
when the strategy in fact *gained* 177% against a benchmark that gained 816%.
`relative_return` = `(1+s)/(1+b) − 1` gives −69.8%: the strategy ended with 30%
of the benchmark's wealth. It is bounded below by −100%, converges on the
arithmetic figure for small returns, and always agrees with it on sign. Both are
carried in the output; the reports display the geometric one.

**D18 — An unprofitable surface is labelled unprofitable, not fragile (Phase 5, post-audit fix).**
`robustness` = median/best inverts on an all-negative grid — the more uniformly
bad the surface, the *higher* it scores. It previously clamped to 0.0 and
returned "fragile: over-fitted", giving a uniformly-losing strategy and a
single-lucky-cell strategy the same diagnosis. `robustness` is now `None` when
the best cell is unprofitable, the verdict says so explicitly, and a sign-
agnostic `spread` (best − worst) is reported alongside.

**D19 — No NaN in any API-bound payload (Phase 5, post-audit fix).**
`NaN` is not valid JSON, and `best_vs_neighbours` could previously be NaN when a
grid corner had no neighbours. Undefined values are `None` so FastAPI emits
`null`. A test asserts `json.dumps(report, allow_nan=False)` succeeds.

**D15 — Robustness is reported as a surface plus a verdict, never as a maximum (Phase 5).**
`plateau_report` deliberately returns median, worst, share-positive and a
neighbour comparison alongside the best cell. Quoting only the best parameter
set is how backtests mislead; the surface makes an isolated spike visible as a
spike. The verdict thresholds (robustness ≥ 0.6 and ≥ 80% positive for "robust")
are round and fixed in code, not tuned per strategy.

**D16 — Period sweeps regenerate signals inside each window (Phase 5).**
Slicing a full-history signal series into windows would leak: the indicator
values at the start of window 3 were computed with knowledge of windows 1–2's
prices, which is fine, but the *parameter choice* would still have been informed
by the whole sample. Regenerating per window makes each a genuine out-of-sample
run. This is a cheap stand-in for full walk-forward analysis, which stays out of
scope.

**D13 — Confirmation bands on EMA Trend and Momentum, chosen structurally (Phase 4).**
Both rules originally flipped on a strict inequality against a noisy quantity.
Diagnostics: 50% of gold's EMA Trend trades lasted ≤2 bars (Momentum 31-43%
across assets), and cost drag reached 67% of gold's frictionless CAGR against
2.5% for SMA Crossover. Each now enters above one threshold and exits below a
lower one, holding in between — which makes them stateful, so `band=0` is *not*
identical to the original stateless rule.

The defaults (1% and 5%) are round numbers, deliberately **not** fitted. The
band improves gold and NVDA but *reduces* EMA Trend's BTC return from 15,254% to
8,558% — so choosing it on results would mean optimising after seeing the
answers, exactly what the brief warns against. The justification is structural:
trading noise 40% of the time is a defect identifiable without reference to any
return figure.

**Phase 5 audited this claim and it held.** Across six asset/strategy pairs the
round defaults ranked best exactly once; they placed 3rd–5th of 5 candidate
bands in the other five. A fitted parameter would rank first everywhere. The
surfaces are also flat enough that the choice barely matters — EMA Trend scores
robustness 0.85–0.91 on BTC and NVDA.

**D14 — No test may sit on a numerical boundary (Phase 4).**
`test_momentum_hand_computed_threshold_boundary` passed only because
`110/100 - 1` evaluates to `0.10000000000000009` rather than `0.10`, placing it
on the wrong side of a `> 0.10` comparison by floating-point luck. Boundary
tests are now written clear of the threshold (+8% against a 5%/10% pair), so
they assert behaviour rather than float representation.

**D11 — Strategies never lag their own signals (Phase 4).**
A strategy reports the position it wants *as of the current bar's close*, and
the engine alone applies the one-bar execution lag. Splitting the responsibility
would let a carelessly written strategy double-lag (quietly pessimistic) or
forget to lag (look-ahead). One rule, enforced in one place.

**D12 — Unknown parameters are dropped, not passed through (Phase 4).**
`Strategy.__post_init__` keeps only keys present in `defaults`. A typo like
`{"windwo": 5}` would otherwise sit unused in the params dict while the strategy
silently ran on defaults, and the result would be reported as if the parameter
had taken effect.

**D10 — Gross P&L is measured at unslipped prices (Phase 3).**
Slippage is a cost, so it belongs in the cost line, not buried in a worse entry
price. Trades record both the fill price and the reference open, which makes
`net = gross − commission − slippage` hold exactly and lets the dashboard show
users what friction actually cost them.

---

## 7. Known data-quality notes

- **Gold has 82 flat bars** (3.3%) where open = high = low = close — thin
  front-month futures days, all before 2020-03-27. This is genuine data, not a
  pipeline fault. Consequence: an open-based fill equals the close on those days,
  which is the conservative direction. Left visible rather than silently smoothed.
- **BTC retains 69% of its rows** after calendar alignment. Expected — weekends
  are removed so cross-asset comparisons are like-for-like. Single-asset BTC
  analysis still uses the full 3,653-row series.
- **Volatility-regime shares are not 33/33/33, and should not be.** Gold spends
  52.7% of its labelled history in `high_vol` while BTC spends 46.9% in
  `low_vol`. This is the expanding-quantile design working as intended: gold's
  volatility trended *up* over the decade, so later bars exceed their own
  historical terciles, while BTC's trended *down*. Full-sample terciles would
  force an even split and destroy exactly this information.

---

## 8. Success criteria

Realistic targets for a 24-hour build, replacing the original plan's
production SLOs.

- ✅ 10 years of validated history for 3 assets across 3 asset classes
- ✅ All 7 required indicator/metric families computed and verified
- ✅ 4 strategies backtested with costs, sizing and a like-for-like benchmark
- ✅ Look-ahead bias structurally prevented **and** proven by a regression test
- ✅ Regime attribution and robustness surfaces computed and visualised
- ✅ Dashboard covering all 8 required visualisations
- ✅ Core maths covered by tests that verify values, not just absence of crashes
- ✅ Runs end-to-end offline from the committed cache
