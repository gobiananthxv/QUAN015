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
cross-asset correlation, backtests five trading strategies against a
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
and correctly deferred): portfolio optimisation, Monte Carlo, VaR, paper
trading, real-time data.

**Two of the deferred items were built anyway**, and honesty is better than a
stale list:

- **ML-based regime detection** — `backend/models`, `backend/regime`,
  `backend/features`, `backend/strategy` and `backend/backtest/walk_forward.py`
  hold HMM and GMM regime models with walk-forward evaluation. This is a
  separate tree; the FastAPI app never imports it, and none of the dashboard's
  figures come from it.
- **AI research assistant** — the dashboard's chatbot (`app/chat.py`) and the
  News Sentiment tab (`app/news_sentiment_backend.py`). Both are read-only
  narrators over state the platform already computed: the assistant has no
  tools, and no number on any chart originates from a model.

That second point is the constraint that keeps them inside the brief's spirit.
Neither can influence a backtest, and a reader who distrusts both can ignore
every panel they feed without losing a single quantitative result.

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
| `yfinance` in the data pipeline | Direct Yahoo chart API via `requests` | See §6 — this one was forced on us. It later returned as a dependency of the ML tree, which loads its own data |
| Auth, RBAC, TLS | A capability boundary over 5 endpoints (Phase 9) | Reversed. The original reasoning — "no users, no threat model" — was right about *users* and wrong about *threat model*: the mail endpoint would send the contents of `backend/output` to any address a caller named. Guarding four dangerous things is not the same as building a login |
| 170+ tests, >80% coverage | Targeted tests on the maths, the boundary, and the ML tree | Correctness where it counts, not coverage theatre. The count grew to 519 on its own, by adding tests where something could be wrong rather than to a target |
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
│  app/security.py   capability boundary (5 endpoints)     │
├──────────────────────────────────────────────────────────┤
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

  models/ · regime/ · features/ · strategy/ · backtest/walk_forward.py
  ML regime tree — parallel to the above, imported by neither
```

**Layering rule:** `data` knows nothing of `analytics`; `analytics` knows nothing
of `backtest`; nothing below the API layer imports FastAPI. This keeps the quant
core importable and testable without a running server.

`app/security.py` is the one exception, and sits *beside* the API rather than
under it: producing FastAPI dependencies and `HTTPException` is its entire job.
Nothing in `data`, `analytics` or `backtest` imports it, so the rule holds where
it matters.

---

## 5. Phase plan

Times are estimates against a 24-hour budget, ~22 h planned, ~2 h buffer.
Phases 8 and 9 were added after the original eight were complete, from the
remaining buffer.

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

### Phase 8 — Continuous position sizing · 1.5 h · ✅ COMPLETE
Delivered: the engine now treats a signal as a **target exposure** rather than a
direction, a financing charge on borrowed cash, a no-trade band, and a fifth
strategy (`vol_target`) that sizes inversely to recent volatility.

The gap this closes: every technique that actually manages risk — volatility
targeting, risk parity, drawdown control — is a *sizing* technique, and an
engine that can only be all-in or all-out cannot express any of them. Four
strategies answering "am I in or out?" is a timing platform, not a quantitative
one.

**Verification gate — passed.**
1. ✅ All 318 pre-existing tests passed **unchanged** after the engine rewrite.
   `{-1, 0, 1}` is a subset of the reals, so the discrete strategies take the
   same code path they always did; this was the safety argument for the change
   and it held.
2. ✅ 37 new tests (355 total), including hand-computed leverage arithmetic, the
   exact single-bar financing charge, band suppression, and a resized-position
   P&L case that entry-price arithmetic cannot express.
3. ✅ Endpoints re-checked against a **live server**, not just TestClient:
   fractional positions in `curves`, `ann_factor` correctly 365 for BTC and 252
   for NVDA, financing accrued, rebalances counted.
4. ✅ Robustness sweep run on all three assets before any claim was written down.
5. ✅ `./verify.sh` green — and it earned its keep. `strategy_report.py`'s
   invariant checks caught **two real bugs in the new engine code that the test
   suite missed**, which is the whole reason those checks run against live data
   rather than toy frames.

**The two bugs, both mine, both found by the report script.**

*Slippage occasionally paid the trade instead of charging it.* Sizing divides by
`(1 + commission)`, which can push the target below the units already held even
when exposure is being increased — so a leg predicted to be a buy turned out to
be a sell, while still using the buy-side fill. The engine now derives the fill
and the size together and keeps whichever pair is self-consistent. The symptom
was equity drifting from the trade log by 0.001% over a decade: invisible to any
eyeball, caught by an exact identity.

*The position series reported a stale label.* When a rebalance was skipped
because the units held already matched the target, the bar kept the *previous*
target as its label, misreporting what was held by up to 6% on 1.6% of bars.
Cash and equity were always right; the reported exposure was not, and it feeds
the dashboard's leverage statistics. Both bugs now have regression tests.

**What the numbers actually say.** At the default 25% target, vol targeting is a
*risk* tool, not a return tool:

| Asset | | Return | Vol | Sharpe | Max DD |
|---|---|--:|--:|--:|--:|
| NVDA | buy & hold | 13,947% | 50.0% | 1.20 | −66.3% |
| NVDA | vol target | 2,985% | 29.5% | **1.24** | **−36.6%** |
| GOLD | buy & hold | 236% | 16.9% | **0.69** | **−24.9%** |
| GOLD | vol target | 325% | 25.0% | 0.63 | −41.9% |
| BTC | buy & hold | 13,312% | 66.8% | **1.04** | −83.4% |
| BTC | vol target | 1,731% | 31.3% | 1.02 | **−48.8%** |

Read the volatility column, not the return column: 50% / 17% / 67% becomes
29% / 25% / 31%. The strategy's actual output is **risk equalisation across
assets**, which is what it is for. It does not beat buy-and-hold on return at
this setting on any asset, and the plan says so rather than choosing a target
that flatters it.

**The honest correction.** A vectorised prototype run before implementation
suggested this configuration returned 15,109% on NVDA and beat buy-and-hold on
every axis. It does not. The prototype was wrong; the audited engine is the
number that counts, and the prototype's figure is recorded here only so nobody
resurrects it from the conversation history.


### Phase 9 — Capability boundary · 1 h · ✅ COMPLETE
Delivered: [`app/security.py`](backend/app/security.py) — a shared-secret
dependency, a per-route token-bucket rate limiter, a robustness grid cap and
concurrency bound, and a fail-closed recipient allowlist on the report mailer —
applied to exactly the five endpoints that have effects outside this process.

**The gap this closes.** Eighteen of the twenty-two endpoints read a committed
CSV and do arithmetic; abusing them costs CPU. Four reach outside with the
operator's own credentials, and one of those — `POST /api/report/send-email` —
took an arbitrary recipient, zipped the whole of `backend/output`, and mailed
it through an authenticated Gmail account with no rate limit. That is an
exfiltration primitive, an open relay, and an unbounded disk write in a single
unauthenticated endpoint.

**What was deliberately rejected.** A login screen, JWTs, RBAC and TLS, all of
which are visible effort against a threat model that does not apply to a
single-user tool bound to loopback. Prompt-injection filtering on the assistant
was rejected for a sharper reason: the assistant has no tools, so a successful
injection yields a rude paragraph. The endpoint needed guarding for **cost**,
not content, and the controls are sized to that.

**Verification gate — passed.**
1. ✅ 519 tests pass, of which 71 are new in `test_security.py`. Seven
   pre-existing tests failed on first run — five refresh tests sharing a rate
   budget, two email tests meeting the allowlist — and all seven were genuine
   consequences of the guards, fixed in the tests and in one case in the route.
2. ✅ All six `verify.sh` script gates pass, including the new
   `security_report.py`; TypeScript clean; frontend builds. `verify.sh` is green
   end to end for the first time: `hmmlearn` and `yfinance` were listed in
   `requirements.txt` but installed nowhere, so `test_models.py` and
   `test_walk_forward.py` failed at **collection** and took the whole run down
   before anything executed. Installed; all 23 of those tests pass unchanged.
3. ✅ Checked against a **live server**, not only TestClient: `/health` reports
   `token_required: true`, a guarded endpoint answers 401 both without the
   header and with a wrong one, an unguarded read answers 200, and the preflight
   returns `access-control-allow-headers: x-qmafib-token`.
4. ✅ The rate limiter was confirmed live: the 21st call inside the window
   returned 429 with a `Retry-After` header, the first twenty did not.

**A bug the change surfaced.** The frontend's `request` helper spread `...init`
*after* its headers, so `analyzeImage` disabled the JSON content type by passing
`headers: undefined` — which worked only because of that ordering. Adding the
token header required merging headers instead of replacing them, which would
have silently broken every image upload. The fix moves the decision into the
helper: a `FormData` body drops the JSON content type on its own, so a caller
cannot forget and no caller has to know.

A second one came from the same change. `ApiError` was already exported at the
bottom of `api.ts`, so adding `export` to the class produced a duplicate export:
`tsc --noEmit` accepted it and the browser bundle did not. It was caught by
loading the page, which is the argument for opening the dashboard rather than
trusting a green typecheck.

**Where the tests were wrong rather than the code.** Two suites were writing
real artifacts. `test_email_report` and later `test_security` both drove the
mailer far enough to package every file under `backend/output` and write a ~5 MB
`.eml` audit copy back into it — the suite growing the repository it tested, and
making the next run slower. Both now redirect the output directory at a
temporary path. Total suite time roughly halved. Three of those `.eml` files are
committed and could be dropped with `git rm --cached`; `backend/output/emails/`
is now in `.gitignore`.

**What is honestly not covered.** The token reaches the browser as a Vite
variable and is readable in devtools. It raises the cost of scripted abuse; it
is not authentication, and `security.py` says so in its own docstring rather
than leaving a reader to find out. The rate limiter is per-process and
in-memory, so a multi-worker deployment would multiply every budget by the
worker count — correct for the single-process server this ships as, and wrong
the moment that changes.

---


## 6. Decision log

Recorded so the reasoning survives the hackathon.

**D40 — Guard capabilities, not endpoints (Phase 9).**
Every endpoint was classified as pure (reads the snapshot, computes, returns) or
effectful (spends a metered key, sends mail, overwrites the snapshot, or burns
unbounded CPU). Only the effectful five are fenced. The rejected alternative —
a blanket auth middleware — is the easier thing to build and the worse thing to
ship: it puts the read-only dashboard behind configuration to protect endpoints
that hold nothing, and it fails invisibly, because everything still works on the
machine where the token is set. `test_security.py` therefore asserts the
*absence* of the guard on six read endpoints as explicitly as its presence on
the five, so a future change that spreads the fence fails the suite.

**D41 — The controls are asymmetric on purpose (Phase 9).**
Rate limits and the recipient allowlist are always on; the shared secret is off
until configured. The reasoning is about what an unconfigured install should do.
A fresh clone that refuses to run teaches people to disable security rather than
configure it, and the server binds loopback, so an inert token guard exposes
nothing. A drained provider balance or a suspended mail account, by contrast, is
precisely what nobody remembers to configure against — so those controls cannot
be left to a variable somebody forgets. The allowlist goes further and fails
closed: unset, it permits only the SMTP sender, which keeps the feature working
for "mail me the run output" while removing the exfiltration path entirely.

**D42 — The assistant is guarded for cost, not for content (Phase 9).**
The obvious "AI security" work here is prompt-injection filtering, and it was
rejected. `chat.py` has no tools: it takes `page_json` and a question, returns
markdown, and can reach nothing — no files, no function calls, no ability to
start a backtest. A fully successful injection produces a rude paragraph. What
the endpoint can actually do is spend a metered key once per request without
asking who is calling, so it gets a token and a budget. Building an input filter
would have been effort spent in front of the failure mode that does not exist,
while the one that does stayed open.

**D43 — X-Forwarded-For is ignored by the rate limiter (Phase 9).**
Honouring it is the conventional thing to do and is wrong without a trusted
proxy in front of the server: any caller could set their own value and mint a
fresh budget per request, which is an opt-out disguised as a feature. There is
no proxy here, so `client_key` reads `request.client.host` only. A regression
test rotates the header across the budget and asserts the 429 still arrives.

**D44 — The loopback binding is written down even though it is the default
(Phase 9).**
`run.sh` and `run.ps1` now pass `--host 127.0.0.1` explicitly. It changes no
behaviour. The reason is that `security.py` assumes loopback in its own
reasoning, and an assumption that lives in a framework default is one nobody
reads before overriding it — `--host 0.0.0.0` to demo on conference wifi is a
one-word change that silently invalidates the entire threat model.

**D45 — 401 for a bad credential, 403 only for the recipient policy (Phase 9).**
Both refusals originally answered 403, which made them indistinguishable to the
dashboard — and "your token is wrong" and "that address is not approved" call
for completely different advice. A wrong token is a credential that would
succeed if corrected, which is what 401 means, so the token guard now answers
401 in both its failure cases and 403 belongs exclusively to the mail
allowlist. The report modal branches on the code to say which, instead of
showing the API's own text, which names environment variables at a reader who
does not run the server.

**D46 — Bodies are capped, and must declare their length (Phase 9).**
A rate limit bounds how many requests arrive, not how large each is, and the
assistant forwards its payload to a metered provider — so twenty permitted
requests carrying 100 MB each pass a 20-per-minute budget untouched. Starlette
imposes no ceiling, so one was added: 1 MiB for JSON, 17 MiB on the image
upload, which sits just above that endpoint's own 16 MiB cap so the transport
limit never fires first and reports the wrong reason.

Requiring `Content-Length` (411 otherwise) was the part worth thinking about.
Counting bytes mid-stream also works, and was tried: it fails partway through
an upload, at which point there is no clean way to answer. The client is still
writing when the server wants to reply, h11 raises `LocalProtocolError:
... state=MUST_CLOSE`, the caller sees a connection reset rather than a 413,
and the server logs a traceback on demand for anyone hostile. Every real client
declares a length, so requiring it makes the check arithmetic on a header,
decided before a byte of body is read. The streaming count is kept as a
backstop against a lying or rewritten header and is tested directly rather than
through a client — provoking it through one is what produced the mess above.

**D47 — The phase gate checks classification, not behaviour (Phase 9).**
`security_report.py` could have re-asserted what the 71 unit tests already
assert. It asks a different question instead: is every POST endpoint still
classified as effectful, metered or pure? It reads the guards off the live
application — `require_token` by identity, the budget from a tag added to the
closure for exactly this — so it is inspecting the app rather than its own copy
of the answer. An endpoint added without that decision fails the gate, which is
the one failure a green suite cannot catch, because nobody writes a test for an
endpoint they have not thought about yet. Verified by adding a throwaway route
and confirming exit 1.

**D36 — A signal is a target exposure, not a direction (Phase 8).**
`generate_signals` returns any real number: `1.0` fully invested, `0.5` half,
`1.5` half again borrowed, negative short. The engine sizes to it literally
instead of taking its sign. The four directional strategies emit `{-1, 0, 1}`,
which is a subset, so they take the identical code path — verified by all 318
pre-existing tests passing unchanged after the rewrite. The alternative,
bolting sizing on as a separate config field, is what `position_pct` already
was: a single number fixed for the whole run, which no risk technique can use.

**D37 — Leverage is charged for, per bar, at an adjustable rate (Phase 8).**
Holding more than 100% exposure means a negative cash balance, and the engine
accrues `financing_bps_annual` on it every bar, de-annualised by the asset's own
calendar. This mirrors the short borrow fee already charged. The rate is a
visible dashboard input, defaulting to 5%, because the honest answer to "does
leverage help?" is "at what funding rate?" — institutions fund near 5% and
retail margin is often 8–12%, which is frequently the difference between a
levered strategy winning and losing. A levered backtest that ignored its own
funding cost would be fiction.

**D38 — The no-trade band is a strategy setting, so the benchmark ignores it
(Phase 8).**
A continuously-varying target would rebalance every single bar and pay
commission for each one. The band suppresses a resize smaller than a given
fraction of the position already held. Measured effect on NVDA: rebalances fall
from 2,440 to 362 — a 7× reduction — while return *improves* slightly, and at
100 bps per side the banded run returns 1,583% against the unbanded 1,139%.

Entering, exiting and flipping are never suppressed however wide the band is.
Trimming a position is an optimisation; getting out of one is a decision, and
silently ignoring an exit signal to save commission would be a bug wearing the
costume of a feature.

`buy_and_hold` pins the band to zero for the same reason it pins `position_pct`
to 1.0 (D28): a benchmark that moved when you changed a strategy setting is not
a reference point.

**D39 — `target_vol` is a risk dial, not a parameter to be fitted (Phase 8).**
Sweeping it across a 4× range barely moves Sharpe — NVDA 1.23→1.29, BTC
1.00→1.03 — while return and drawdown move enormously. That flatness is the
signature of a real risk-scaling relationship rather than a fitted edge, and it
is why the robustness sweep scores this strategy 0.94 / 0.83 / 0.92, the highest
in the project.

It also means the parameter cannot be "optimised" in any meaningful sense: you
are choosing how much risk you want, not discovering a better setting. The
default stays at a round 25% for all three assets *because* that is the point —
it equalises risk across instruments whose natural volatilities are 50%, 17% and
67%. Tuning it per asset to maximise return would invert the strategy's purpose
and manufacture exactly the over-fitting the Research tab exists to detect.

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

**D35 — One platform-wide period, not per-chart zoom (post-Phase 7).**
Per-chart zoom is the obvious generalisation of the Overview control and the
wrong one. Half the charts are path-anchored — cumulative return, equity curves
and drawdown are all indexed from the series start — so naive zoom shows a
segment of a curve anchored outside the window: technically correct, and
misleading, because the eye reads shape rather than absolute level. Making them
meaningful requires *re-anchoring*, which is a recompute, not a zoom. And eight
independently zoomed charts cannot be compared with one another at all.

A single period in a bar under the tabs solves both: every view recomputes from
the backend for the same window, so every figure on screen describes the same
stretch of history. It also removed a duplicate control — the Backtest tab's own
date range *was* this period, and two similar-looking controls meaning slightly
different things is worse than one.

Made the quant layer window-aware throughout to support it: `correlation_matrix`,
`rolling_correlation`, `parameter_sweep`, `cost_sweep`, `period_sweep` and
`regime_attribution` all take `start`/`end`, and every endpoint returns 422 on an
empty window rather than an empty chart.

One thing stays deliberately un-windowed: regime *labels* are computed on the
full history and then sliced. Their thresholds are expanding — what counts as
"high volatility" at a bar depends on everything before it — so recomputing from
a window's own start would relabel bars according to a history that did not
happen.

**D34 — Zooming has a floor, and thin windows say so (post-Phase 7).**
Testing the zoom at every scale found two failures below ~20 bars: the
crossover's warm-up consumed the window so no markers survived, and annualised
statistics became nonsense — a five-bar window reported a Sharpe of 23.69 and a
three-bar window 35.92. The arithmetic was right; the inference was garbage, and
rendering it would have contradicted everything else in this project. Drag
selections under 20 bars are now ignored (not clamped — silently widening what
the user dragged is worse than doing nothing), and windows under 60 bars carry a
caution naming which figures remain exact (return, best and worst day) and which
do not. A 2/6 tier was added so the 20-60 bar range still produces markers:
measured across all three assets, 3/10 found 2 trades at 20 bars where 2/6 finds 7.

**D31 — Window metrics are computed by the backend, never in the browser (post-Phase 7).**
Recomputing Sharpe and drawdown in TypeScript for the zoomed window would have
been instant and offline. It would also have created a second implementation of
the maths the test suite covers, free to drift from it. `/api/metrics` takes
`start`/`end` instead and the dashboard debounces a request per zoom. The window
is applied to *prices* before returns are taken, so the first bar of a window has
no return — slicing the return series would carry in one return computed against
a close from outside the window.

**D32 — Signal periods scale with the zoom (post-Phase 7).**
A 50/200 crossover produces four fills in a decade and none in a quarter, so
zooming in showed an empty chart. Periods now track the window
(50/200 → 20/100 → 10/50 → 5/20 → 3/10) and the toolbar names the pair in use.
This is explicitly a *display* choice so the chart always has something to show;
parameter selection and judgement stay on the Backtest and Research tabs, where
they are swept and scored.

**D33 — Stale-response guard keys on the window, not a counter (post-Phase 7).**
The first implementation used a monotonic request id and compared it at resolve
time. React StrictMode double-invokes effects in development, so the accepted
response was routinely rejected by a later duplicate and the panel silently kept
showing the previous window's numbers. Keying on `asset|start|end` accepts a
response iff it still describes the window the user is looking at, regardless of
how many times the effect fires.

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
- ✅ 5 strategies backtested with costs, sizing and a like-for-like benchmark
- ✅ Continuous position sizing, with leverage charged at an adjustable rate
- ✅ Look-ahead bias structurally prevented **and** proven by a regression test
- ✅ Regime attribution and robustness surfaces computed and visualised
- ✅ Dashboard covering all 8 required visualisations
- ✅ Core maths covered by tests that verify values, not just absence of crashes
- ✅ Runs end-to-end offline from the committed cache
- ✅ Every endpoint with effects outside the process is rate-limited, and gated
     on a shared secret when one is configured — with the read-only dashboard
     deliberately left open, and tests asserting it stays that way
