"""Robustness sweeps and regime attribution."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import BacktestConfig
from app.backtest.robustness import (
    cost_sweep,
    parameter_sweep,
    period_sweep,
    plateau_report,
    regime_attribution,
    relative_return,
    run_strategy,
    sharpe_surface,
)

CHEAP = BacktestConfig(initial_capital=100_000.0, commission_bps=10.0, slippage_bps=5.0)


# ================================================================ sweeps


def test_parameter_sweep_covers_the_whole_grid():
    sweep = parameter_sweep("NVDA", "momentum", {"window": [30, 60, 90], "band": [0.0, 0.05]})
    assert len(sweep) == 6
    assert set(sweep["window"]) == {30, 60, 90}
    assert set(sweep["band"]) == {0.0, 0.05}


def test_parameter_sweep_skips_invalid_combinations():
    """A grid may contain corners the strategy rejects (fast >= slow). Those are
    dropped, not crashed on — but every valid cell must still appear."""
    grid = {"fast": [10, 50, 200], "slow": [20, 100]}
    sweep = parameter_sweep("GOLD", "sma_crossover", grid)
    valid = [(f, s) for f in grid["fast"] for s in grid["slow"] if f < s]
    assert len(sweep) == len(valid)
    assert (sweep["fast"] < sweep["slow"]).all()


def test_parameter_sweep_raises_when_nothing_is_valid():
    with pytest.raises(ValueError, match="no valid parameter"):
        parameter_sweep("GOLD", "sma_crossover", {"fast": [200], "slow": [50]})


def test_parameter_sweep_reports_every_metric():
    sweep = parameter_sweep("BTC", "momentum", {"window": [60, 90]})
    for col in ("total_return", "sharpe", "max_drawdown", "num_trades", "exposure", "total_costs"):
        assert col in sweep.columns


def test_sweep_results_match_a_direct_backtest():
    """A sweep cell must be identical to running that parameter set on its own —
    otherwise the surface describes something other than the strategy."""
    sweep = parameter_sweep("NVDA", "momentum", {"window": [90]}, config=CHEAP)
    direct = run_strategy("NVDA", "momentum", {"window": 90}, config=CHEAP).stats()
    assert sweep.iloc[0]["sharpe"] == pytest.approx(direct["sharpe"])
    assert sweep.iloc[0]["total_return"] == pytest.approx(direct["total_return"])


def test_sharpe_surface_pivots_to_a_grid():
    sweep = parameter_sweep("GOLD", "sma_crossover", {"fast": [10, 20, 50], "slow": [100, 200]})
    surface = sharpe_surface(sweep, "fast", "slow")
    assert surface.shape == (2, 3)
    assert list(surface.columns) == [10, 20, 50]
    assert list(surface.index) == [100, 200]


# ================================================================ plateau detection


def _grid_frame(values: np.ndarray) -> pd.DataFrame:
    """Build a sweep-shaped frame from an explicit surface, so plateau detection
    is tested against a known answer rather than whatever the market did."""
    rows = []
    for i, a in enumerate([1, 2, 3, 4, 5]):
        for j, b in enumerate([10, 20, 30, 40, 50]):
            rows.append({"a": a, "b": b, "sharpe": float(values[i, j])})
    return pd.DataFrame(rows)


def test_plateau_report_calls_a_flat_surface_robust():
    """Every cell roughly equal -> the parameter choice barely matters."""
    flat = _grid_frame(np.full((5, 5), 1.2) + np.random.default_rng(0).normal(0, 0.01, (5, 5)))
    report = plateau_report(flat, ["a", "b"])
    assert report["robustness"] > 0.9
    assert report["share_positive"] == 1.0
    assert report["verdict"].startswith("robust")


def test_plateau_report_calls_a_single_spike_fragile():
    """One brilliant cell in a field of nothing is the signature of over-fitting."""
    spike = np.full((5, 5), 0.02)
    spike[2, 2] = 3.0
    report = plateau_report(_grid_frame(spike), ["a", "b"])
    assert report["robustness"] < 0.1
    assert report["best"] == pytest.approx(3.0)
    assert report["verdict"].startswith("fragile")


def test_plateau_report_finds_the_best_cell():
    surface = np.full((5, 5), 0.5)
    surface[3, 1] = 2.5
    report = plateau_report(_grid_frame(surface), ["a", "b"])
    assert report["best_params"] == {"a": 4, "b": 20}
    assert report["best"] == pytest.approx(2.5)


def test_plateau_report_neighbours_are_adjacent_cells():
    """A spike's neighbours are poor; a plateau's are nearly as good."""
    spike = np.full((5, 5), 0.1)
    spike[2, 2] = 2.0
    assert plateau_report(_grid_frame(spike), ["a", "b"])["neighbour_mean"] == pytest.approx(0.1)

    ridge = np.full((5, 5), 0.1)
    ridge[2, :] = 2.0
    ridge[2, 2] = 2.1
    # Two of four neighbours sit on the ridge at 2.0, two are off it at 0.1.
    assert plateau_report(_grid_frame(ridge), ["a", "b"])["neighbour_mean"] == pytest.approx(1.05)


def test_plateau_report_calls_an_all_negative_surface_unprofitable_not_fragile():
    """A grid where nothing works is consistently unprofitable, NOT over-fitted.

    Regression: these previously both scored robustness 0.0 and were labelled
    "fragile", conflating two opposite diagnoses. median/best also inverts on a
    negative surface - the more uniformly bad the grid, the higher it would
    score - so robustness is reported as undefined instead.
    """
    uniform = plateau_report(_grid_frame(np.full((5, 5), -0.5)), ["a", "b"])
    assert uniform["share_positive"] == 0.0
    assert uniform["robustness"] is None
    assert uniform["verdict"].startswith("unprofitable")

    spiky = np.full((5, 5), -2.0)
    spiky[2, 2] = -0.1
    assert plateau_report(_grid_frame(spiky), ["a", "b"])["verdict"].startswith("unprofitable")


def test_plateau_report_reports_spread_regardless_of_sign():
    """`spread` works on negative surfaces where `robustness` cannot."""
    surface = np.full((5, 5), -2.0)
    surface[1, 1] = -0.5
    assert plateau_report(_grid_frame(surface), ["a", "b"])["spread"] == pytest.approx(1.5)


def test_plateau_report_ignores_infinities():
    """Sortino can legitimately be inf; it must not become the 'best' cell."""
    surface = np.full((5, 5), 1.0)
    frame = _grid_frame(surface)
    frame.loc[0, "sharpe"] = np.inf
    report = plateau_report(frame, ["a", "b"])
    assert np.isfinite(report["best"])
    assert report["best"] == pytest.approx(1.0)


def test_plateau_report_rejects_an_empty_sweep():
    with pytest.raises(ValueError, match="empty sweep"):
        plateau_report(pd.DataFrame(), ["a"])


def test_plateau_report_is_json_serialisable():
    """numpy scalars break json.dumps; the API layer depends on this."""
    sweep = parameter_sweep("GOLD", "sma_crossover", {"fast": [10, 20], "slow": [100, 200]})
    json.dumps(plateau_report(sweep, ["fast", "slow"]))


def test_plateau_report_emits_no_nan_values():
    """NaN is not valid JSON. Undefined figures must be None, so FastAPI emits
    `null` rather than a payload no strict JSON parser will accept."""
    report = plateau_report(_grid_frame(np.full((5, 5), -0.5)), ["a", "b"])
    for key, value in report.items():
        if isinstance(value, float):
            assert not np.isnan(value), f"{key} is NaN"
    json.dumps(report, allow_nan=False)


# ================================================================ cost sensitivity


def test_cost_sweep_returns_decay_monotonically():
    sweep = cost_sweep("NVDA", "momentum", bps_levels=(0.0, 10.0, 50.0, 100.0))
    assert sweep["total_return"].is_monotonic_decreasing
    assert sweep["total_costs"].is_monotonic_increasing


def test_cost_sweep_starts_frictionless():
    sweep = cost_sweep("GOLD", "sma_crossover", bps_levels=(0.0, 25.0))
    assert sweep.iloc[0]["total_costs"] == pytest.approx(0.0)
    assert sweep.iloc[1]["total_costs"] > 0


def test_cost_sweep_does_not_mutate_the_base_config():
    """BacktestConfig is frozen and the sweep uses dataclasses.replace; if it
    ever mutated in place, every later run in the session would be wrong."""
    base = BacktestConfig(commission_bps=7.0, slippage_bps=3.0)
    cost_sweep("GOLD", "momentum", bps_levels=(0.0, 50.0), config=base)
    assert base.commission_bps == 7.0
    assert base.slippage_bps == 3.0


# ================================================================ period stability


def test_period_sweep_windows_are_contiguous_and_disjoint():
    windows = period_sweep("NVDA", "sma_crossover", n_windows=5)
    assert len(windows) == 5
    assert windows["window"].tolist() == [1, 2, 3, 4, 5]
    starts = pd.to_datetime(windows["start"])
    ends = pd.to_datetime(windows["end"])
    assert (starts.shift(-1).dropna() > ends[:-1]).all(), "windows must not overlap"


def test_period_sweep_bars_sum_to_the_full_history():
    from app.data.store import load_asset

    windows = period_sweep("GOLD", "momentum", n_windows=4)
    assert windows["bars"].sum() == len(load_asset("GOLD"))


def test_period_sweep_reports_excess_over_the_benchmark():
    windows = period_sweep("BTC", "sma_crossover", n_windows=4)
    recomputed = windows["total_return"] - windows["benchmark_return"]
    assert np.allclose(windows["excess_return"], recomputed)


def test_relative_return_is_bounded_where_arithmetic_excess_is_not():
    """Regression: subtracting two large compounded returns is misleading.

    +176.8% against a benchmark's +816.0% reads as -639% arithmetically, which
    sounds like a total wipeout. Geometrically the strategy ended with 30% of
    the benchmark's wealth: -69.8%. Bad, but bounded and interpretable.
    """
    assert relative_return(1.768, 8.160) == pytest.approx(2.768 / 9.160 - 1, abs=1e-9)
    assert relative_return(1.768, 8.160) > -1.0
    assert (1.768 - 8.160) < -6.0, "the arithmetic figure really is that misleading"


def test_relative_return_is_zero_when_matching_the_benchmark():
    assert relative_return(0.5, 0.5) == pytest.approx(0.0)
    assert relative_return(0.0, 0.0) == pytest.approx(0.0)


def test_relative_return_agrees_with_arithmetic_on_small_returns():
    """The two measures converge as returns shrink, so nothing is lost."""
    assert relative_return(0.02, 0.01) == pytest.approx(0.01, abs=1e-3)


def test_period_sweep_relative_return_never_implies_worse_than_total_loss():
    """A strategy cannot lose more than everything; the arithmetic figure can
    suggest otherwise."""
    for asset in ("GOLD", "BTC", "NVDA"):
        windows = period_sweep(asset, "sma_crossover", n_windows=5)
        assert (windows["relative_return"] > -1.0).all()


def test_period_sweep_beat_flag_matches_the_returns():
    windows = period_sweep("NVDA", "momentum", n_windows=4)
    expected = windows["total_return"] > windows["benchmark_return"]
    assert (windows["beat_benchmark"] == expected).all()
    # Both excess measures must agree on the SIGN, whatever their magnitude.
    assert ((windows["excess_return"] > 0) == (windows["relative_return"] > 0)).all()


# ================================================================ regime attribution


def test_regime_attribution_shares_sum_to_one_per_axis():
    rows = regime_attribution("NVDA", "sma_crossover")
    for axis in ("trend", "volatility"):
        share = sum(r["share_of_period"] for r in rows if r["axis"] == axis)
        assert share == pytest.approx(1.0)


def test_regime_attribution_exposure_is_a_valid_fraction():
    for row in regime_attribution("BTC", "momentum"):
        assert 0.0 <= row["exposure"] <= 1.0


def test_regime_attribution_pairs_strategy_with_benchmark():
    rows = regime_attribution("GOLD", "sma_crossover")
    assert rows
    for row in rows:
        assert row["excess_return"] == pytest.approx(
            row["strategy_return"] - row["benchmark_return"]
        )
        assert row["relative_return"] == pytest.approx(
            relative_return(row["strategy_return"], row["benchmark_return"])
        )
        assert row["beat_benchmark"] == (row["strategy_return"] > row["benchmark_return"])


def test_regime_relative_return_is_interpretable():
    """NVDA's bull regime shows a -22,340% arithmetic excess, which is noise.
    The geometric figure stays inside (-100%, +inf)."""
    for row in regime_attribution("NVDA", "momentum"):
        assert row["relative_return"] > -1.0


def test_trend_strategy_reduces_exposure_in_bear_regimes():
    """The whole point of a trend filter. If this fails, the strategy is not
    doing the job it exists to do."""
    rows = {r["regime"]: r for r in regime_attribution("NVDA", "sma_crossover") if r["axis"] == "trend"}
    assert rows["bear"]["exposure"] < rows["bull"]["exposure"]


def test_regime_attribution_covers_every_label():
    rows = regime_attribution("BTC", "momentum")
    trend = {r["regime"] for r in rows if r["axis"] == "trend"}
    vol = {r["regime"] for r in rows if r["axis"] == "volatility"}
    assert trend == {"bull", "bear"}
    assert vol == {"low_vol", "normal_vol", "high_vol"}


def test_regime_attribution_is_json_serialisable():
    json.dumps(regime_attribution("GOLD", "mean_reversion"))


def test_regime_benchmark_matches_a_plain_buy_and_hold():
    """The benchmark column must be the real benchmark, not a stand-in."""
    from app.analytics.metrics import summarise
    from app.backtest.engine import buy_and_hold
    from app.analytics.regime import classify
    from app.config import get_asset
    from app.data.store import load_asset

    df = load_asset("NVDA")
    bench = buy_and_hold(df, "NVDA")
    reg = classify("NVDA")
    joined = pd.DataFrame({"r": bench.returns}).join(reg[["trend_regime"]], how="inner")
    bull = joined[joined["trend_regime"] == "bull"]["r"]
    expected = summarise(bull, get_asset("NVDA").ann_factor)["total_return"]

    row = next(
        r for r in regime_attribution("NVDA", "sma_crossover")
        if r["axis"] == "trend" and r["regime"] == "bull"
    )
    assert row["benchmark_return"] == pytest.approx(expected)
