"""
tests/test_walk_forward.py — Tests for walk-forward backtest no-lookahead guarantee.
"""

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.walk_forward import WalkForwardBacktest, _compute_metrics


def _make_price_df(n: int = 800, seed: int = 99) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-02", periods=n)
    rets = rng.normal(0.0003, 0.012, size=n)
    close = 100.0 * np.cumprod(1 + rets)
    return pd.DataFrame({"close": close, "open": close, "high": close, "low": close,
                         "volume": 1_000_000}, index=dates)


class TestWalkForwardNoLookahead:
    """Verify that training data always ends before test data begins."""

    def test_no_lookahead_bias(self):
        """Each fold's test_start must be strictly after train_end."""
        price_df = _make_price_df(n=800)
        bt = WalkForwardBacktest(
            ticker="SYNTHETIC",
            model_type="gmm",
            train_days=252,
            step_days=21,
            n_components=2,
        )
        # Monkey-patch loader
        bt._loader.load = lambda *a, **kw: price_df

        result = bt.run(start="2015-01-01")
        for fold in result.fold_results:
            assert fold.train_end < fold.test_start, (
                f"Lookahead in fold {fold.fold_idx}: "
                f"train_end={fold.train_end}, test_start={fold.test_start}"
            )

    def test_equity_curve_starts_near_one(self):
        price_df = _make_price_df(n=600)
        bt = WalkForwardBacktest(
            ticker="SYNTHETIC",
            model_type="gmm",
            train_days=252,
            step_days=21,
            n_components=2,
        )
        bt._loader.load = lambda *a, **kw: price_df
        result = bt.run(start="2015-01-01")
        # Equity curve first value should be close to (1 + first_day_return * pos_size)
        assert 0.5 <= result.equity_curve.iloc[0] <= 1.5


class TestComputeMetrics:
    def _make_equity(self, returns):
        s = pd.Series(returns)
        return (1 + s).cumprod()

    def test_total_return_positive_trend(self):
        equity = self._make_equity([0.01] * 100)
        m = _compute_metrics(equity)
        assert m["total_return"] > 0

    def test_max_drawdown_negative(self):
        equity = self._make_equity([0.01, -0.05, -0.05, 0.01] * 30)
        m = _compute_metrics(equity)
        assert m["max_drawdown"] < 0

    def test_empty_series_returns_zeros(self):
        m = _compute_metrics(pd.Series([], dtype=float))
        assert m["total_return"] == 0.0

    def test_sharpe_higher_for_lower_vol(self):
        low_vol = self._make_equity([0.001] * 252)
        high_vol = self._make_equity(
            [0.001 if i % 2 == 0 else -0.002 for i in range(252)]
        )
        m_low = _compute_metrics(low_vol)
        m_high = _compute_metrics(high_vol)
        assert m_low["sharpe"] > m_high["sharpe"]
