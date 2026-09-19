"""REST API.

Ten endpoints, no more. Every response passes through ``serialise.clean`` so
``inf`` and ``nan`` leave as ``null`` rather than as tokens ``JSON.parse``
rejects.

Read endpoints are GETs with query parameters. Backtests are POSTs because they
carry a nested configuration object, not because they mutate anything — nothing
in this API has side effects beyond populating the on-disk cache.
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
from ..analytics.metrics import daily_returns, drawdown_series, rolling_volatility, summarise
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
)
from ..backtest.strategies import REGISTRY, list_strategies
from ..config import ASSETS, get_asset
from ..data.store import cache_status, load_asset, load_panel, quality_report
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

    def to_config(self) -> BacktestConfig:
        return BacktestConfig(**self.model_dump())


class BacktestIn(BaseModel):
    asset: str
    strategy: str
    params: dict = Field(default_factory=dict)
    config: ConfigIn = Field(default_factory=ConfigIn)


class CompareIn(BaseModel):
    asset: str
    strategies: list[str] = Field(default_factory=lambda: list(REGISTRY))
    config: ConfigIn = Field(default_factory=ConfigIn)


class RobustnessIn(BaseModel):
    asset: str
    strategy: str
    grid: dict[str, list] = Field(default_factory=dict)
    config: ConfigIn = Field(default_factory=ConfigIn)


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
    """Asset registry plus what is currently cached."""
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
            "cache": cache_status(),
        }
    )


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
def get_metrics(asset: str, vol_window: int = Query(30, ge=5, le=365)) -> dict:
    """Buy-and-hold risk/return for one asset, with the series the Risk view plots."""
    key = _asset_or_404(asset)
    asset_meta = get_asset(key)
    close = load_asset(key)["close"]
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
        }
    )


@router.get("/correlation")
def get_correlation(window: int = Query(90, ge=10, le=750)) -> dict:
    matrix = correlation_matrix()
    rolling = rolling_correlation_all(window)
    return clean(
        {
            "assets": list(matrix.columns),
            "observations": sample_size(),
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
def get_rolling_correlation(a: str, b: str, window: int = Query(90, ge=10, le=750)) -> dict:
    key_a, key_b = _asset_or_404(a), _asset_or_404(b)
    series = rolling_correlation(key_a, key_b, window)
    return clean(
        {"a": key_a, "b": key_b, "window": window, "series": series_to_pairs(series, "corr")}
    )


@router.get("/regime")
def get_regime(asset: str) -> dict:
    """Regime labels over time, for shading the price chart."""
    key = _asset_or_404(asset)
    reg = classify(key)
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
        res = run_strategy(key, body.strategy, body.params, cfg)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid parameters: {exc}") from None
    bench = buy_and_hold(load_asset(key), key, config=cfg)
    return clean(
        {
            "strategy": _result_payload(res),
            "benchmark": _result_payload(bench, include_trades=False),
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
    for name in body.strategies:
        try:
            res = run_strategy(key, name, None, cfg)
        except ValueError as exc:
            raise HTTPException(422, f"{name}: {exc}") from None
        runs.append(_result_payload(res, include_trades=False))

    bench = buy_and_hold(load_asset(key), key, config=cfg)
    return clean(
        {"asset": key, "runs": runs, "benchmark": _result_payload(bench, include_trades=False)}
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
        sweep = parameter_sweep(key, body.strategy, grid, config=cfg)
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
            "costs": frame_to_records(cost_sweep(key, body.strategy, config=cfg)),
            "periods": frame_to_records(period_sweep(key, body.strategy, config=cfg)),
        }
    )


@router.get("/backtest/regime-attribution")
def get_regime_attribution(asset: str, strategy: str) -> dict:
    """Where a strategy beats the benchmark, and at what exposure."""
    key = _asset_or_404(asset)
    _strategy_or_404(strategy)
    return clean({"asset": key, "strategy": strategy, "rows": regime_attribution(key, strategy)})


DEFAULT_GRIDS = {
    "sma_crossover": {"fast": [10, 20, 30, 50, 80], "slow": [100, 150, 200, 250]},
    "ema_trend": {"span": [20, 35, 50, 75, 100], "band": [0.0, 0.005, 0.01, 0.02, 0.03]},
    "momentum": {"window": [30, 60, 90, 120, 180], "band": [0.0, 0.025, 0.05, 0.10, 0.15]},
    "mean_reversion": {"window": [10, 15, 20, 30, 40], "entry_z": [1.0, 1.5, 2.0, 2.5, 3.0]},
}


def _default_grid(strategy: str) -> dict[str, list]:
    return DEFAULT_GRIDS[strategy]


@router.get("/panel")
def get_panel() -> dict:
    """Aligned multi-asset close panel, for the correlation view's context."""
    panel = load_panel()
    return clean({"assets": list(panel.columns), "rows": frame_to_records(panel, index_name="date")})
