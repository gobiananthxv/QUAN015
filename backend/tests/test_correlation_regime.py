"""Correlation and market-regime correctness."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.correlation import (
    correlation_matrix,
    covariance_matrix,
    rolling_correlation,
    rolling_correlation_all,
    sample_size,
)
from app.analytics.regime import TREND_LABELS, VOL_LABELS, classify, classify_frame, regime_breakdown
from app.config import ASSETS
from app.data.store import load_asset, load_panel


# ---------------------------------------------------------------- panel


def test_panel_has_no_missing_values():
    assert not load_panel().isna().any().any()


def test_panel_is_sorted_and_unique():
    idx = load_panel().index
    assert idx.is_monotonic_increasing
    assert not idx.has_duplicates


def test_panel_covers_every_asset():
    assert set(load_panel().columns) == set(ASSETS)


def test_panel_is_an_intersection_not_a_union():
    """Every panel date must exist in every asset's own series. If this fails we
    are forward-filling phantom bars, which biases correlation toward zero."""
    panel = load_panel()
    for key in ASSETS:
        own = load_asset(key).index
        assert panel.index.isin(own).all(), f"{key}: panel has dates the asset never traded"


def test_panel_drops_crypto_weekends():
    """BTC trades 365 days; the aligned panel must be shorter than BTC alone."""
    assert len(load_panel()) < len(load_asset("BTC"))


# ---------------------------------------------------------------- correlation


def test_correlation_matrix_shape_and_diagonal():
    m = correlation_matrix()
    assert m.shape == (len(ASSETS), len(ASSETS))
    assert np.allclose(np.diag(m.values), 1.0)


def test_correlation_matrix_is_symmetric():
    m = correlation_matrix().values
    assert np.allclose(m, m.T)


def test_correlation_values_are_in_range():
    m = correlation_matrix().values
    assert m.min() >= -1.0 - 1e-9 and m.max() <= 1.0 + 1e-9


def test_correlation_is_computed_on_returns_not_prices():
    """Two independent upward-trending price series correlate near 1 in levels
    but near 0 in returns. Our matrix must reflect the returns figure."""
    panel = load_panel()
    price_corr = panel.corr().loc["GOLD", "NVDA"]
    return_corr = correlation_matrix().loc["GOLD", "NVDA"]
    assert abs(return_corr) < abs(price_corr)
    assert abs(return_corr) < 0.5, "cross-asset daily return correlation should be modest"


def test_covariance_diagonal_matches_return_variance():
    cov = covariance_matrix()
    rets = load_panel().pct_change().dropna()
    for key in ASSETS:
        assert cov.loc[key, key] == pytest.approx(rets[key].var())


# ---------------------------------------------------------------- rolling correlation


def test_rolling_correlation_is_bounded():
    rc = rolling_correlation("BTC", "NVDA", 90).dropna()
    assert len(rc) > 0
    assert rc.min() >= -1.0 - 1e-9 and rc.max() <= 1.0 + 1e-9


def test_rolling_correlation_respects_window():
    """With a 90-bar window the first 89 observations cannot be defined.

    Measured against the PAIR's own panel, not the all-asset panel - see the
    sample-selection note in app/analytics/correlation.py.
    """
    pair_len = sample_size(("BTC", "NVDA"))
    rc = rolling_correlation("BTC", "NVDA", 90)
    assert len(rc) == pair_len - 89


def test_pairwise_sample_is_at_least_the_full_panel_sample():
    """Documents the deliberate sample difference: dropping an asset from the
    panel can only add trading days back, never remove them."""
    full = sample_size()
    pair = sample_size(("BTC", "NVDA"))
    assert pair >= full
    assert pair == len(load_asset("NVDA")) - 1  # NVDA is the binding calendar here


def test_rolling_correlation_is_symmetric_in_its_arguments():
    a = rolling_correlation("BTC", "NVDA", 90)
    b = rolling_correlation("NVDA", "BTC", 90)
    pd.testing.assert_series_equal(a, b, check_names=False)


def test_rolling_correlation_self_is_one():
    rc = rolling_correlation("BTC", "BTC", 60).dropna()
    assert np.allclose(rc.values, 1.0)


def test_rolling_correlation_all_covers_every_pair():
    cols = set(rolling_correlation_all(90).columns)
    assert cols == {"GOLD~BTC", "GOLD~NVDA", "BTC~NVDA"}


def test_rolling_correlation_varies_over_time():
    """The whole point of rolling correlation: relationships are not static."""
    rc = rolling_correlation("BTC", "NVDA", 90).dropna()
    assert rc.max() - rc.min() > 0.1


# ---------------------------------------------------------------- regime


def _synthetic_close() -> pd.Series:
    rng = np.random.default_rng(11)
    steps = rng.normal(0.0004, 0.015, 900)
    return pd.Series(100 * np.exp(np.cumsum(steps)), index=pd.date_range("2020-01-01", periods=900))


def test_regime_labels_are_from_the_known_vocabulary():
    reg = classify("NVDA")
    trend = set(reg["trend_regime"].dropna().unique())
    vol = set(reg["vol_regime"].dropna().unique())
    assert trend <= set(TREND_LABELS), f"unexpected trend labels: {trend}"
    assert vol <= set(VOL_LABELS), f"unexpected vol labels: {vol}"


def test_regime_produces_both_trend_states_over_a_decade():
    trend = set(classify("NVDA")["trend_regime"].dropna().unique())
    assert trend == set(TREND_LABELS), "10 years should contain both bull and bear"


def test_regime_produces_all_three_volatility_states():
    vol = set(classify("BTC")["vol_regime"].dropna().unique())
    assert vol == set(VOL_LABELS)


def test_trend_label_matches_the_200_sma_rule():
    """Spot-check the definition rather than trusting the label."""
    from app.analytics.indicators import sma

    reg = classify("NVDA")
    close = load_asset("NVDA")["close"]
    ma = sma(close, 200)
    labelled = reg["trend_regime"].notna()
    bull = reg.loc[labelled & (reg["trend_regime"] == "bull")].index
    bear = reg.loc[labelled & (reg["trend_regime"] == "bear")].index
    assert (close.loc[bull] > ma.loc[bull]).all()
    assert (close.loc[bear] <= ma.loc[bear]).all()


def test_regime_classification_is_causal():
    """THE regime leak test.

    Volatility thresholds use expanding quantiles. If they were full-sample,
    truncating the series would change earlier labels — meaning a 2016 bar had
    been labelled using 2020 information, and every regime attribution built on
    it would be contaminated.
    """
    close = _synthetic_close()
    cutoff = 600
    on_prefix = classify_frame(close.iloc[:cutoff])
    on_full = classify_frame(close).iloc[:cutoff]
    pd.testing.assert_frame_equal(on_prefix, on_full)


def test_regime_warmup_is_unlabelled():
    """Before 200 bars there is no trend MA, so no trend label may be emitted."""
    reg = classify_frame(_synthetic_close(), trend_window=200)
    assert reg["trend_regime"].iloc[:199].isna().all()


def test_regime_breakdown_shares_sum_to_one_per_axis():
    rows = regime_breakdown("NVDA")
    assert rows, "breakdown should not be empty"
    for axis in ("trend", "volatility"):
        share = sum(r["share_of_period"] for r in rows if r["axis"] == axis)
        assert share == pytest.approx(1.0), f"{axis} shares sum to {share}"


def test_regime_breakdown_day_counts_are_positive():
    for row in regime_breakdown("GOLD"):
        assert row["days"] > 1
        assert set(row) >= {"axis", "regime", "days", "sharpe", "max_drawdown"}


def test_regime_breakdown_accepts_a_custom_return_series():
    """This is how strategy-vs-regime attribution will be driven in Phase 5."""
    close = load_asset("BTC")["close"]
    half = close.pct_change().iloc[: len(close) // 2]
    rows = regime_breakdown("BTC", returns=half)
    assert rows
    assert sum(r["days"] for r in rows if r["axis"] == "trend") <= len(half)


def test_high_vol_regime_really_has_higher_volatility():
    """Sanity: the label must correspond to the thing it claims to measure."""
    rows = {r["regime"]: r for r in regime_breakdown("BTC") if r["axis"] == "volatility"}
    assert rows["high_vol"]["volatility"] > rows["low_vol"]["volatility"]
