"""REST API.

Fourteen endpoints here, plus ``/health`` on the app itself. Every response passes through ``serialise.clean`` so ``inf``
and ``nan`` leave as ``null`` rather than as tokens ``JSON.parse`` rejects.

Read endpoints are GETs with query parameters. Backtests are POSTs because they
carry a nested configuration object, not because they mutate anything.

Exactly one endpoint has side effects and exactly one touches the network:
``POST /data/refresh``, which re-downloads market data and overwrites the
committed snapshot. Everything else reads that snapshot from disk, which is what
keeps a backtest reproducible between runs.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..analytics.correlation import (
    correlation_matrix,
    rolling_correlation,
    rolling_correlation_all,
    sample_size,
)
from ..analytics.indicators import compute_indicators
from ..analytics.metrics import (
    daily_returns,
    drawdown_series,
    rolling_returns,
    rolling_volatility,
    summarise,
)
from ..analytics.regime import classify
from ..backtest.engine import BacktestConfig, buy_and_hold
from ..backtest.robustness import (
    cost_sweep,
    parameter_sweep,
    period_sweep,
    plateau_report,
    regime_attribution,
    run_strategy,
    sharpe_surface,
    window,
)
from ..backtest.strategies import REGISTRY, list_strategies
from ..config import ASSETS, get_asset
from ..data.store import load_asset, load_panel, quality_report, refresh, snapshot_status
from .serialise import clean, frame_to_records, series_to_pairs

router = APIRouter()


# ---------------------------------------------------------------- models


class ConfigIn(BaseModel):
    """Execution assumptions, all user-adjustable from the dashboard."""

    initial_capital: float = Field(100_000.0, gt=0, le=1e12)
    commission_bps: float = Field(10.0, ge=0, le=1000)
    slippage_bps: float = Field(5.0, ge=0, le=1000)
    position_pct: float = Field(1.0, gt=0, le=1)
    allow_short: bool = False
    borrow_bps_annual: float = Field(50.0, ge=0, le=5000)
    # Cost of borrowing cash, charged whenever exposure exceeds 100%. Retail
    # margin is often 8-12%, so this is worth moving before believing a levered
    # result.
    financing_bps_annual: float = Field(500.0, ge=0, le=5000)
    # Minimum change in target exposure, relative to the exposure held, before
    # the engine trades. Only continuously-sized strategies ever hit it.
    no_trade_band: float = Field(0.0, ge=0, le=1)

    def to_config(self) -> BacktestConfig:
        return BacktestConfig(**self.model_dump())


class BacktestIn(BaseModel):
    asset: str
    strategy: str
    params: dict = Field(default_factory=dict)
    config: ConfigIn = Field(default_factory=ConfigIn)
    # ISO dates. Omitted means the full history. Signals are regenerated inside
    # the window, so a sub-period is a genuine out-of-sample run.
    start: str | None = None
    end: str | None = None


class CompareIn(BaseModel):
    asset: str
    strategies: list[str] = Field(default_factory=lambda: list(REGISTRY))
    config: ConfigIn = Field(default_factory=ConfigIn)
    start: str | None = None
    end: str | None = None


class RefreshIn(BaseModel):
    """Which assets to re-download. Empty means all of them.

    ``force`` re-downloads even if the snapshot is less than a day old. The data
    is daily, so the default skips that as a wasted round trip.
    """

    assets: list[str] = Field(default_factory=list)
    force: bool = False


class RobustnessIn(BaseModel):
    asset: str
    strategy: str
    grid: dict[str, list] = Field(default_factory=dict)
    config: ConfigIn = Field(default_factory=ConfigIn)
    start: str | None = None
    end: str | None = None


# ---------------------------------------------------------------- helpers


def _asset_or_404(key: str) -> str:
    try:
        return get_asset(key).key
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None


def _strategy_or_404(name: str) -> str:
    if name not in REGISTRY:
        raise HTTPException(404, f"Unknown strategy '{name}'. Known: {', '.join(REGISTRY)}")
    return name


# ---------------------------------------------------------------- catalogue


@router.get("/assets")
def get_assets() -> dict:
    """Asset registry plus the state of the committed data snapshot."""
    return clean(
        {
            "assets": [
                {
                    "key": a.key,
                    "name": a.name,
                    "ticker": a.ticker,
                    "asset_class": a.asset_class,
                    "ann_factor": a.ann_factor,
                }
                for a in ASSETS.values()
            ],
            "snapshot": snapshot_status(),
        }
    )


@router.post("/data/refresh")
def post_refresh(body: RefreshIn | None = None) -> dict:
    """Re-download market data from the provider and overwrite the snapshot.

    The one endpoint that reaches the network. Everything else reads the
    committed snapshot, so results stay reproducible between runs; this is how
    you deliberately move that baseline forward.

    Market data here is daily, so an asset fetched within the last 24 hours is
    skipped rather than re-downloaded — a second fetch would rewrite identical
    rows. Pass ``force`` to override.

    Returns 502 only if *every* requested asset failed — a partial success, or a
    run where everything was simply already current, still returns 200 with the
    detail listed, so the caller can see exactly what happened rather than being
    told the whole thing broke.
    """
    keys = [_asset_or_404(k) for k in (body.assets if body else [])]
    result = refresh(keys or None, force=bool(body and body.force))
    if result["failed"] and not result["updated"] and not result["skipped"]:
        raise HTTPException(
            502, f"provider unreachable: {result['failed'][0]['error']}"
        )
    return clean(result)


@router.get("/strategies")
def get_strategies() -> dict:
    """Strategy catalogue for the configuration panel."""
    return clean({"strategies": list_strategies()})


# ---------------------------------------------------------------- data


@router.get("/ohlcv")
def get_ohlcv(
    asset: str,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    key = _asset_or_404(asset)
    df = load_asset(key).loc[start:end]
    if df.empty:
        raise HTTPException(400, f"{key}: no bars in the requested range")
    return clean(
        {
            "asset": key,
            "rows": len(df),
            "quality": quality_report(key),
            "bars": frame_to_records(df, index_name="date"),
        }
    )


@router.get("/indicators")
def get_indicators(
    asset: str,
    sma_fast: int = Query(20, ge=2, le=500),
    sma_slow: int = Query(50, ge=3, le=500),
    ema_fast: int = Query(12, ge=2, le=500),
    ema_slow: int = Query(26, ge=3, le=500),
    start: str | None = None,
    end: str | None = None,
) -> dict:
    key = _asset_or_404(asset)
    df = compute_indicators(
        load_asset(key), sma_fast=sma_fast, sma_slow=sma_slow,
        ema_fast=ema_fast, ema_slow=ema_slow,
    ).loc[start:end]
    return clean(
        {
            "asset": key,
            "columns": [c for c in df.columns if c not in ("open", "high", "low", "close", "volume")],
            "rows": frame_to_records(df, index_name="date"),
        }
    )


@router.get("/metrics")
def get_metrics(
    asset: str,
    vol_window: int = Query(30, ge=5, le=365),
    return_window: int = Query(252, ge=5, le=1260),
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Buy-and-hold risk/return for one asset, with the series the Risk view plots.

    ``start``/``end`` restrict every figure to that window. The dashboard uses
    this when you zoom the price chart, so the Sharpe, drawdown and volatility
    on screen describe the period you are actually looking at.

    The window is applied to *prices* before returns are taken, so the first
    bar of the window has no return — which is correct. Slicing the return
    series instead would carry in one return computed against a close from
    outside the window.
    """
    key = _asset_or_404(asset)
    asset_meta = get_asset(key)
    close = load_asset(key)["close"]
    if start or end:
        try:
            close = window(close.to_frame("close"), start, end)["close"]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    returns = daily_returns(close)
    return clean(
        {
            "asset": key,
            "ann_factor": asset_meta.ann_factor,
            "summary": summarise(returns, asset_meta.ann_factor),
            "returns": series_to_pairs(returns, "ret"),
            "cumulative": series_to_pairs((1 + returns).cumprod() - 1, "cum"),
            "drawdown": series_to_pairs(drawdown_series(returns), "dd"),
            "rolling_vol": series_to_pairs(
                rolling_volatility(returns, vol_window, asset_meta.ann_factor).dropna(), "vol"
            ),
            # Trailing N-bar return at each point: "if you had bought here and
            # held for a year, what would you have made?" A single total return
            # hides how wildly that answer varies with entry date.
            "rolling_returns": series_to_pairs(
                rolling_returns(close, return_window).dropna(), "ret"
            ),
            "return_window": return_window,
            "bars": int(len(close)),
            "period": {
                "start": str(close.index.min().date()) if len(close) else None,
                "end": str(close.index.max().date()) if len(close) else None,
            },
        }
    )


@router.get("/correlation")
def get_correlation(
    window: int = Query(90, ge=10, le=750),
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Correlation over the whole history, or over ``start``/``end``.

    Worth restricting: GOLD~NVDA correlates 0.044 across the decade but 0.245
    through 2020. A single figure averages regimes that never coexisted.
    """
    try:
        matrix = correlation_matrix(start=start, end=end)
        rolling = rolling_correlation_all(window, start=start, end=end)
        observations = sample_size(start=start, end=end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return clean(
        {
            "assets": list(matrix.columns),
            "observations": observations,
            "period": {"start": start, "end": end},
            "matrix": [
                {"a": a, "b": b, "value": matrix.loc[a, b]}
                for a in matrix.index
                for b in matrix.columns
            ],
            "window": window,
            "rolling": frame_to_records(rolling, index_name="date"),
        }
    )


@router.get("/rolling-correlation")
def get_rolling_correlation(
    a: str,
    b: str,
    window: int = Query(90, ge=10, le=750),
    start: str | None = None,
    end: str | None = None,
) -> dict:
    key_a, key_b = _asset_or_404(a), _asset_or_404(b)
    try:
        series = rolling_correlation(key_a, key_b, window, start=start, end=end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return clean(
        {"a": key_a, "b": key_b, "window": window, "series": series_to_pairs(series, "corr")}
    )


@router.get("/regime")
def get_regime(asset: str, start: str | None = None, end: str | None = None) -> dict:
    """Regime labels over time, for shading the price chart.

    Labels are always computed on the full history and then sliced. Their
    thresholds are expanding — what counts as "high volatility" at a given bar
    depends on everything before it — so recomputing from a window's own start
    would relabel bars according to a history that did not happen.
    """
    key = _asset_or_404(asset)
    reg = classify(key)
    if start or end:
        reg = reg.loc[start:end]
        if reg.empty:
            raise HTTPException(422, f"no bars between {start or 'start'} and {end or 'end'}")
    return clean(
        {
            "asset": key,
            "rows": frame_to_records(
                reg[["trend_regime", "vol_regime", "rolling_vol"]], index_name="date"
            ),
        }
    )


# ---------------------------------------------------------------- backtesting


def _result_payload(res, include_trades: bool = True) -> dict:
    payload = {
        "asset": res.asset,
        "strategy": res.strategy,
        "params": res.params,
        "config": res.config.as_dict(),
        "stats": res.stats(),
        "curves": res.curves(),
    }
    if include_trades:
        payload["trades"] = res.trade_log()
    return payload


@router.post("/backtest")
def post_backtest(body: BacktestIn) -> dict:
    key = _asset_or_404(body.asset)
    _strategy_or_404(body.strategy)
    cfg = body.config.to_config()
    try:
        res = run_strategy(key, body.strategy, body.params, cfg, start=body.start, end=body.end)
        # The benchmark must cover the same window, or the comparison is
        # between two different periods and means nothing.
        bench_frame = window(load_asset(key), body.start, body.end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    bench = buy_and_hold(bench_frame, key, config=cfg)
    return clean(
        {
            "strategy": _result_payload(res),
            "benchmark": _result_payload(bench, include_trades=False),
            "period": {"start": body.start, "end": body.end},
        }
    )


@router.post("/backtest/compare")
def post_compare(body: CompareIn) -> dict:
    """Every requested strategy on one asset, against the same benchmark."""
    key = _asset_or_404(body.asset)
    for name in body.strategies:
        _strategy_or_404(name)
    cfg = body.config.to_config()

    runs = []
    try:
        for name in body.strategies:
            res = run_strategy(key, name, None, cfg, start=body.start, end=body.end)
            runs.append(_result_payload(res, include_trades=False))
        bench_frame = window(load_asset(key), body.start, body.end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    bench = buy_and_hold(bench_frame, key, config=cfg)
    return clean(
        {
            "asset": key,
            "runs": runs,
            "benchmark": _result_payload(bench, include_trades=False),
            "period": {"start": body.start, "end": body.end},
        }
    )


@router.post("/backtest/robustness")
def post_robustness(body: RobustnessIn) -> dict:
    """Parameter surface, plateau verdict, cost decay and period stability.

    The heaviest endpoint by far — a 25-cell grid runs ~25 backtests and takes
    roughly 300 ms. The dashboard shows a loading state for this one.
    """
    key = _asset_or_404(body.asset)
    _strategy_or_404(body.strategy)
    cfg = body.config.to_config()

    grid = body.grid or _default_grid(body.strategy)
    axes = list(grid)
    if len(axes) != 2:
        raise HTTPException(422, "grid must contain exactly two parameters")

    try:
        sweep = parameter_sweep(key, body.strategy, grid, config=cfg, start=body.start, end=body.end)
        costs = cost_sweep(key, body.strategy, config=cfg, start=body.start, end=body.end)
        periods = period_sweep(key, body.strategy, config=cfg, start=body.start, end=body.end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    surface = sharpe_surface(sweep, axes[0], axes[1])
    return clean(
        {
            "asset": key,
            "strategy": body.strategy,
            "axes": {"x": axes[0], "y": axes[1]},
            "surface": [
                {"x": col, "y": idx, "sharpe": surface.loc[idx, col]}
                for idx in surface.index
                for col in surface.columns
            ],
            "sweep": frame_to_records(sweep),
            "plateau": plateau_report(sweep, axes),
            "costs": frame_to_records(costs),
            "periods": frame_to_records(periods),
            "period": {"start": body.start, "end": body.end},
        }
    )


@router.get("/backtest/regime-attribution")
def get_regime_attribution(
    asset: str, strategy: str, start: str | None = None, end: str | None = None
) -> dict:
    """Where a strategy beats the benchmark, and at what exposure."""
    key = _asset_or_404(asset)
    _strategy_or_404(strategy)
    try:
        rows = regime_attribution(key, strategy, start=start, end=end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return clean(
        {"asset": key, "strategy": strategy, "rows": rows, "period": {"start": start, "end": end}}
    )


DEFAULT_GRIDS = {
    "sma_crossover": {"fast": [10, 20, 30, 50, 80], "slow": [100, 150, 200, 250]},
    "ema_trend": {"span": [20, 35, 50, 75, 100], "band": [0.0, 0.005, 0.01, 0.02, 0.03]},
    "momentum": {"window": [30, 60, 90, 120, 180], "band": [0.0, 0.025, 0.05, 0.10, 0.15]},
    "mean_reversion": {"window": [10, 15, 20, 30, 40], "entry_z": [1.0, 1.5, 2.0, 2.5, 3.0]},
    # target_vol is a risk *choice* rather than a parameter to fit, so the axis
    # spans settings a user might genuinely want rather than clustering around
    # one. Sweeping it shows whether Sharpe is flat across the range, which is
    # what a real risk-scaling relationship looks like.
    "vol_target": {"vol_window": [10, 20, 30, 40, 60], "target_vol": [0.15, 0.20, 0.25, 0.30, 0.40]},
}


def _default_grid(strategy: str) -> dict[str, list]:
    try:
        return DEFAULT_GRIDS[strategy]
    except KeyError:
        raise HTTPException(
            422,
            f"No default sweep grid for '{strategy}'. Send an explicit two-axis grid.",
        ) from None


@router.get("/panel")
def get_panel() -> dict:
    """Aligned multi-asset close panel, for the correlation view's context."""
    panel = load_panel()
    return clean({"assets": list(panel.columns), "rows": frame_to_records(panel, index_name="date")})


# ---------------------------------------------------------------- report email


class SendReportIn(BaseModel):
    email: str


@router.post("/report/send-email")
def post_send_report(body: SendReportIn) -> dict:
    """Send all files and folders in backend/output to the specified email address."""
    from ..email_service import send_report_email

    try:
        result = send_report_email(body.email)
        return clean(result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from None
    except Exception as exc:
        raise HTTPException(500, f"Failed to send report: {exc}") from None

