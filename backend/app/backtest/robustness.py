"""Robustness testing and regime attribution.

Two questions this module exists to answer, both named in the problem statement:

**"Does this strategy still work if I change the parameters?"**
A single backtest number is nearly meaningless — any rule can be tuned until it
looks good on one history. :func:`parameter_sweep` runs the whole grid and
:func:`plateau_report` quantifies whether the best cell sits on a broad plateau
(robust) or an isolated spike (over-fitted). Reporting the surface rather than
its maximum is the structural defence against over-optimisation.

**"When does this strategy actually work?"**
:func:`regime_attribution` slices a strategy's returns by market regime and puts
the benchmark's returns for the same regime alongside them, so "it beat
buy-and-hold" can be resolved into *where* it did.
"""
from __future__ import annotations

import itertools
from dataclasses import replace

import numpy as np
import pandas as pd

from ..analytics.metrics import summarise
from ..analytics.regime import classify
from ..config import get_asset
from ..data.store import load_asset
from .engine import BacktestConfig, BacktestResult, buy_and_hold, run_backtest
from .strategies import get_strategy

# Metrics carried through every sweep row.
SWEEP_METRICS = (
    "total_return",
    "cagr",
    "volatility",
    "sharpe",
    "sortino",
    "max_drawdown",
    "num_trades",
    "exposure",
    "total_costs",
)


def window(df: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Slice a price frame to a date range.

    Signals are always generated *from the sliced frame*, never sliced after the
    fact. Generating on the full history and then trimming would let indicator
    values at the start of the window carry information from before it — which
    is fine for a chart but wrong for an out-of-sample test, and this is exactly
    the control the problem statement means by "backtesting periods".
    """
    out = df.loc[start:end]
    if out.empty:
        raise ValueError(
            f"no bars between {start or 'start'} and {end or 'end'}"
        )
    return out


def run_strategy(
    asset: str,
    strategy_name: str,
    params: dict | None = None,
    config: BacktestConfig | None = None,
    df: pd.DataFrame | None = None,
    start: str | None = None,
    end: str | None = None,
) -> BacktestResult:
    """Backtest one strategy on one asset. The single entry point everything else uses."""
    asset = get_asset(asset).key
    frame = load_asset(asset) if df is None else df
    if start or end:
        frame = window(frame, start, end)
    strat = get_strategy(strategy_name, params, asset=asset)
    signals = strat.generate_signals(frame)
    return run_backtest(
        frame, signals, asset, strategy=strategy_name, params=strat.params, config=config
    )


# ===========================================================================
# Parameter sweeps
# ===========================================================================


def parameter_sweep(
    asset: str,
    strategy_name: str,
    grid: dict[str, list],
    config: BacktestConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Backtest every combination in ``grid``.

    Parameter combinations the strategy rejects (``fast >= slow``, and similar)
    are skipped rather than crashing the sweep — a grid is allowed to contain
    invalid corners, and silently dropping them keeps the surface honest about
    what was actually testable.
    """
    asset = get_asset(asset).key
    df = load_asset(asset)
    if start or end:
        df = window(df, start, end)
    names = list(grid)
    rows: list[dict] = []

    for combo in itertools.product(*(grid[n] for n in names)):
        params = dict(zip(names, combo))
        try:
            strat = get_strategy(strategy_name, params, asset=asset)
        except ValueError:
            continue  # invalid corner of the grid
        res = run_backtest(
            df,
            strat.generate_signals(df),
            asset,
            strategy=strategy_name,
            params=strat.params,
            config=config,
        )
        stats = res.stats()
        rows.append({**params, **{k: stats[k] for k in SWEEP_METRICS}})

    if not rows:
        raise ValueError(f"{strategy_name}: no valid parameter combination in the grid")
    return pd.DataFrame(rows)


def sharpe_surface(sweep: pd.DataFrame, x: str, y: str, metric: str = "sharpe") -> pd.DataFrame:
    """Pivot a two-parameter sweep into a grid the dashboard renders as a heatmap."""
    return sweep.pivot_table(index=y, columns=x, values=metric)


def plateau_report(sweep: pd.DataFrame, params: list[str], metric: str = "sharpe") -> dict:
    """Quantify whether the best parameter set is robust or a lucky spike.

    ``robustness`` is the median metric over the whole grid divided by the best
    cell. Near 1.0 means the surface is flat and the choice of parameters barely
    matters — the edge, if any, is real. Near 0 means one cell carries the result
    and everything around it is mediocre, which is the signature of over-fitting.

    ``best_vs_neighbours`` compares the best cell against the cells adjacent to
    it in parameter space. A genuine plateau has neighbours nearly as good; a
    spike is surrounded by a cliff.
    """
    if sweep.empty:
        raise ValueError("cannot summarise an empty sweep")

    values = sweep[metric].replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        raise ValueError(f"sweep has no finite '{metric}' values")

    best_idx = values.idxmax()
    best_row = sweep.loc[best_idx]
    best = float(values.loc[best_idx])
    median = float(values.median())

    # Neighbours: cells differing by one step in exactly one parameter.
    neighbours: list[float] = []
    ranks = {p: sorted(sweep[p].unique()) for p in params}
    best_pos = {p: ranks[p].index(best_row[p]) for p in params}
    for p in params:
        for step in (-1, 1):
            pos = best_pos[p] + step
            if 0 <= pos < len(ranks[p]):
                mask = pd.Series(True, index=sweep.index)
                for q in params:
                    want = ranks[q][best_pos[q] + (step if q == p else 0)] if q == p else best_row[q]
                    mask &= sweep[q] == want
                hit = sweep.loc[mask, metric]
                if not hit.empty and np.isfinite(hit.iloc[0]):
                    neighbours.append(float(hit.iloc[0]))

    neighbour_mean = float(np.mean(neighbours)) if neighbours else None
    share_positive = float((values > 0).mean())

    # `robustness` only means anything when the best cell is actually
    # profitable. On an all-negative surface median/best inverts: the more
    # uniformly bad the grid, the *higher* the ratio would score. Report it as
    # undefined instead and let the verdict say what is really going on.
    if best > 0:
        robustness = median / best
        neighbour_ratio = neighbour_mean / best if neighbour_mean is not None else None
    else:
        robustness = None
        neighbour_ratio = None

    return {
        "metric": metric,
        "combinations": int(len(sweep)),
        "best_params": {p: _native(best_row[p]) for p in params},
        "best": best,
        "median": median,
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "worst": float(values.min()),
        "spread": float(values.max() - values.min()),
        "share_positive": share_positive,
        "robustness": robustness,
        "neighbour_mean": neighbour_mean,
        "best_vs_neighbours": neighbour_ratio,
        "verdict": _verdict(best, robustness, share_positive),
    }


def _native(value):
    """numpy scalars are not JSON-serialisable; unwrap them."""
    return value.item() if hasattr(value, "item") else value


def _verdict(best: float, robustness: float | None, share_positive: float) -> str:
    """Plain-English reading of the surface.

    The unprofitable case is separated out deliberately. A grid where nothing
    works is *not* over-fitted — it is consistently unprofitable, which is a
    different and more useful thing to be told.
    """
    if best <= 0:
        return "unprofitable: no parameter set produced a positive result"
    if robustness is None:
        return "indeterminate: not enough finite results to judge"
    if robustness >= 0.6 and share_positive >= 0.8:
        return "robust: broad plateau, most parameter choices work"
    if robustness >= 0.35 and share_positive >= 0.5:
        return "moderate: sensitive to parameters but not a single lucky cell"
    return "fragile: result concentrated in a few cells, treat as over-fitted"


def relative_return(strategy: float, benchmark: float) -> float:
    """Geometric excess: how much more (or less) wealth the strategy produced.

    Subtracting two compounded total returns is badly misleading once they are
    large. NVDA's 2022-2024 window has the strategy at +176.8% and buy-and-hold
    at +816.0%; the arithmetic difference reads -639%, which sounds like a
    catastrophic loss. Geometrically the strategy ended with 30% of the
    benchmark's wealth, i.e. -69.8% - bad, but bounded and interpretable.

    Arithmetic difference is kept alongside this because it is the familiar
    figure for small returns; this is the one the reports display.
    """
    denominator = 1.0 + benchmark
    if denominator <= 0:
        return float("nan")
    return (1.0 + strategy) / denominator - 1.0


# ===========================================================================
# Cost and period sensitivity
# ===========================================================================


def cost_sweep(
    asset: str,
    strategy_name: str,
    params: dict | None = None,
    bps_levels: tuple[float, ...] = (0.0, 5.0, 10.0, 25.0, 50.0, 100.0),
    config: BacktestConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """How the result decays as friction rises. A strategy that only works at
    zero cost is an artefact of the data, not an edge."""
    base = config or BacktestConfig()
    rows = []
    for bps in bps_levels:
        cfg = replace(base, commission_bps=bps, slippage_bps=bps / 2)
        stats = run_strategy(asset, strategy_name, params, cfg, start=start, end=end).stats()
        rows.append(
            {"bps_per_side": bps, **{k: stats[k] for k in SWEEP_METRICS}}
        )
    return pd.DataFrame(rows)


def period_sweep(
    asset: str,
    strategy_name: str,
    params: dict | None = None,
    n_windows: int = 5,
    config: BacktestConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Split the history into consecutive windows and backtest each separately.

    A strategy whose entire result comes from one window did not find an edge;
    it found one episode. This is a cheap stand-in for full walk-forward
    analysis, which is out of scope for this build.
    """
    asset = get_asset(asset).key
    df = load_asset(asset)
    if start or end:
        df = window(df, start, end)
    strat = get_strategy(strategy_name, params, asset=asset)
    bounds = np.linspace(0, len(df), n_windows + 1).astype(int)

    rows = []
    for i in range(n_windows):
        chunk = df.iloc[bounds[i]: bounds[i + 1]]
        if len(chunk) < 30:
            continue
        # Signals are generated on the chunk alone, so each window is a genuine
        # out-of-sample run rather than a slice of a full-history signal.
        res = run_backtest(
            chunk, strat.generate_signals(chunk), asset,
            strategy=strategy_name, params=strat.params, config=config,
        )
        bench = buy_and_hold(chunk, asset, config=config).stats()
        stats = res.stats()
        rows.append(
            {
                "window": i + 1,
                "start": str(chunk.index[0].date()),
                "end": str(chunk.index[-1].date()),
                "bars": len(chunk),
                **{k: stats[k] for k in SWEEP_METRICS},
                "benchmark_return": bench["total_return"],
                # Arithmetic difference, kept because it is the familiar figure.
                "excess_return": stats["total_return"] - bench["total_return"],
                # Geometric excess - the one to quote. See relative_return().
                "relative_return": relative_return(
                    stats["total_return"], bench["total_return"]
                ),
                "beat_benchmark": stats["total_return"] > bench["total_return"],
            }
        )
    return pd.DataFrame(rows)


# ===========================================================================
# Regime attribution
# ===========================================================================


def regime_attribution(
    asset: str,
    strategy_name: str,
    params: dict | None = None,
    config: BacktestConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Slice a strategy's returns by market regime, against the benchmark.

    Answers the question a single headline number cannot: a strategy that beats
    buy-and-hold overall may do so entirely by sidestepping one bear market, and
    a strategy that loses overall may still be the better holding in every
    regime but one.

    ``exposure`` per regime is often the most revealing column — a trend
    strategy's value usually shows up as being 20% invested in bear regimes
    rather than as a higher return.
    """
    asset = get_asset(asset).key
    ann = get_asset(asset).ann_factor
    df = load_asset(asset)
    if start or end:
        df = window(df, start, end)

    res = run_strategy(asset, strategy_name, params, config, df=df)
    bench = buy_and_hold(df, asset, config=config)
    # Regime labels are computed on the FULL history deliberately: the trend
    # and volatility thresholds at a given bar depend on what came before it,
    # and recomputing them from the window's own start would relabel bars
    # according to a history that did not happen. The join below restricts them
    # to the window.
    reg = classify(asset)

    joined = pd.DataFrame(
        {
            "strategy_ret": res.returns,
            "benchmark_ret": bench.returns,
            "position": res.position,
        }
    ).join(reg[["trend_regime", "vol_regime"]], how="inner")

    rows: list[dict] = []
    for axis, axis_name in (("trend_regime", "trend"), ("vol_regime", "volatility")):
        labelled = joined[joined[axis].notna()]
        if labelled.empty:
            continue
        for label, grp in labelled.groupby(axis):
            if len(grp) < 2:
                continue
            strat_stats = summarise(grp["strategy_ret"], ann)
            bench_stats = summarise(grp["benchmark_ret"], ann)
            rows.append(
                {
                    "axis": axis_name,
                    "regime": str(label),
                    "days": int(len(grp)),
                    "share_of_period": len(grp) / len(labelled),
                    "exposure": float((grp["position"] != 0).mean()),
                    "strategy_return": strat_stats["total_return"],
                    "strategy_cagr": strat_stats["cagr"],
                    "strategy_sharpe": strat_stats["sharpe"],
                    "strategy_max_drawdown": strat_stats["max_drawdown"],
                    "benchmark_return": bench_stats["total_return"],
                    "benchmark_cagr": bench_stats["cagr"],
                    "benchmark_sharpe": bench_stats["sharpe"],
                    "excess_return": strat_stats["total_return"] - bench_stats["total_return"],
                    "relative_return": relative_return(
                        strat_stats["total_return"], bench_stats["total_return"]
                    ),
                    "beat_benchmark": strat_stats["total_return"] > bench_stats["total_return"],
                }
            )
    return rows
