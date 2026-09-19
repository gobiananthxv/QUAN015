"""Indicator correctness.

Values are hand-computed, not snapshotted from the implementation — a snapshot
test would happily lock in a bug.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.indicators import atr, bollinger, compute_indicators, ema, macd, roc, rsi, sma


# ---------------------------------------------------------------- SMA


def test_sma_hand_computed():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = sma(s, 3)
    assert out.iloc[:2].isna().all(), "first window-1 values must be NaN"
    assert out.iloc[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert out.iloc[3] == pytest.approx(3.0)  # (2+3+4)/3
    assert out.iloc[4] == pytest.approx(4.0)  # (3+4+5)/3


def test_sma_window_longer_than_series_is_all_nan():
    assert sma(pd.Series([1.0, 2.0]), 5).isna().all()


# ---------------------------------------------------------------- EMA


def test_ema_recursive_form_hand_computed():
    """span=3 -> alpha=0.5. Recursion: e[i] = 0.5*x[i] + 0.5*e[i-1], seeded at x[0]."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ema(s, 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(2.25)    # 0.5*3 + 0.5*1.5
    assert out.iloc[3] == pytest.approx(3.125)   # 0.5*4 + 0.5*2.25
    assert out.iloc[4] == pytest.approx(4.0625)  # 0.5*5 + 0.5*3.125


def test_ema_reacts_faster_than_sma(linear_up):
    """On a rising series the EMA must sit above the SMA of the same period."""
    assert ema(linear_up, 20).iloc[-1] > sma(linear_up, 20).iloc[-1]


def test_ema_of_constant_is_the_constant(flat):
    assert ema(flat, 10).dropna().eq(100.0).all()


# ---------------------------------------------------------------- RSI


def test_rsi_monotonic_up_is_100(linear_up):
    assert rsi(linear_up).dropna().eq(100.0).all()


def test_rsi_monotonic_down_is_0(linear_down):
    assert rsi(linear_down).dropna().eq(0.0).all()


def test_rsi_flat_is_neutral_50(flat):
    """No gains AND no losses is neutral, not overbought. Regression: this
    returned 100 before the Phase 2 audit. Gold has 82 such bars."""
    assert rsi(flat).dropna().eq(50.0).all()


def test_rsi_stays_in_bounds(noisy):
    v = rsi(noisy).dropna()
    assert len(v) > 0
    assert v.min() >= 0.0 and v.max() <= 100.0


def test_rsi_warmup_is_nan(noisy):
    assert rsi(noisy, 14).iloc[:13].isna().all()


# ---------------------------------------------------------------- MACD


def test_macd_is_ema_difference(noisy):
    out = macd(noisy, 12, 26, 9)
    expected = ema(noisy, 12) - ema(noisy, 26)
    pd.testing.assert_series_equal(
        out["macd"].dropna(), expected.dropna(), check_names=False
    )


def test_macd_histogram_is_line_minus_signal(noisy):
    out = macd(noisy).dropna()
    assert np.allclose(out["macd_hist"], out["macd"] - out["macd_signal"])


def test_macd_negative_in_downtrend(linear_down):
    assert macd(linear_down)["macd"].dropna().iloc[-1] < 0


# ---------------------------------------------------------------- Bollinger


def test_bollinger_hand_computed():
    """Population std (ddof=0) of [1..5] is sqrt(2) = 1.41421356."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = bollinger(s, window=5, num_std=2.0)
    assert out["bb_mid"].iloc[4] == pytest.approx(3.0)
    assert out["bb_upper"].iloc[4] == pytest.approx(3.0 + 2 * np.sqrt(2.0))
    assert out["bb_lower"].iloc[4] == pytest.approx(3.0 - 2 * np.sqrt(2.0))
    # last price 5 is (5-3)/sqrt(2) = 1.41421 standard deviations above the mean
    assert out["bb_z"].iloc[4] == pytest.approx(2.0 / np.sqrt(2.0))


def test_bollinger_bands_ordered(noisy):
    out = bollinger(noisy).dropna()
    assert (out["bb_upper"] >= out["bb_mid"]).all()
    assert (out["bb_mid"] >= out["bb_lower"]).all()


def test_bollinger_zero_width_on_flat_series(flat):
    out = bollinger(flat).dropna(subset=["bb_mid"])
    assert np.allclose(out["bb_upper"], out["bb_lower"])


# ---------------------------------------------------------------- ATR


def test_atr_hand_computed_constant_range():
    """A constant true range of 2.0 must smooth to exactly 2.0."""
    idx = pd.date_range("2024-01-01", periods=30)
    df = pd.DataFrame(
        {"high": [102.0] * 30, "low": [100.0] * 30, "close": [101.0] * 30}, index=idx
    )
    assert atr(df, 14).dropna().iloc[-1] == pytest.approx(2.0)


def test_atr_is_positive(ohlcv):
    assert (atr(ohlcv).dropna() > 0).all()


# ---------------------------------------------------------------- ROC


def test_roc_hand_computed():
    s = pd.Series([100.0, 110.0, 121.0])
    assert roc(s, 1).iloc[1] == pytest.approx(0.10)
    assert roc(s, 2).iloc[2] == pytest.approx(0.21)


# ---------------------------------------------------------------- causality

CAUSAL_CASES = [
    ("sma", lambda s: sma(s, 20)),
    ("ema", lambda s: ema(s, 20)),
    ("rsi", lambda s: rsi(s, 14)),
    ("macd", lambda s: macd(s)["macd"]),
    ("macd_signal", lambda s: macd(s)["macd_signal"]),
    ("bb_upper", lambda s: bollinger(s)["bb_upper"]),
    ("bb_z", lambda s: bollinger(s)["bb_z"]),
    ("roc", lambda s: roc(s, 20)),
]


@pytest.mark.parametrize("name,fn", CAUSAL_CASES, ids=[c[0] for c in CAUSAL_CASES])
def test_indicator_is_causal(name, fn, noisy):
    """THE test the backtester depends on.

    An indicator value at bar t must depend only on bars <= t. We compute it on
    a truncated series and on the full series, and assert the overlapping region
    is identical. If appending future bars changes a past value, the indicator
    leaks the future and every backtest built on it is invalid.
    """
    cutoff = 300
    on_prefix = fn(noisy.iloc[:cutoff])
    on_full = fn(noisy).iloc[:cutoff]
    pd.testing.assert_series_equal(on_prefix, on_full, check_names=False)


def test_atr_is_causal(ohlcv):
    cutoff = 300
    pd.testing.assert_series_equal(
        atr(ohlcv.iloc[:cutoff]), atr(ohlcv).iloc[:cutoff], check_names=False
    )


# ---------------------------------------------------------------- bundle


def test_compute_indicators_preserves_ohlcv_and_index(ohlcv):
    out = compute_indicators(ohlcv)
    assert len(out) == len(ohlcv)
    assert out.index.equals(ohlcv.index)
    for col in ["open", "high", "low", "close", "volume"]:
        pd.testing.assert_series_equal(out[col], ohlcv[col])


def test_compute_indicators_emits_every_required_column(ohlcv):
    out = compute_indicators(ohlcv)
    required = [
        "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "rsi",
        "macd", "macd_signal", "macd_hist",
        "bb_mid", "bb_upper", "bb_lower", "bb_z", "atr", "roc",
    ]
    missing = [c for c in required if c not in out.columns]
    assert not missing, f"missing indicator columns: {missing}"


def test_compute_indicators_respects_custom_periods(ohlcv):
    out = compute_indicators(ohlcv, sma_fast=5, sma_slow=15)
    assert "sma_5" in out.columns and "sma_15" in out.columns
    pd.testing.assert_series_equal(
        out["sma_5"], sma(ohlcv["close"], 5), check_names=False
    )
