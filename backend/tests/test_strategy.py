"""
tests/test_strategy.py — Unit tests for AdaptiveStrategy.
"""

import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategy.adaptive_strategy import AdaptiveStrategy


REGIME_LABELS = ["Bull", "Bear", "High-Volatility", "Sideways", "Unknown"]


class TestAdaptiveStrategy:
    def setup_method(self):
        self.strategy = AdaptiveStrategy()

    def test_get_params_all_regimes(self):
        for regime in REGIME_LABELS:
            params = self.strategy.get_params(regime)
            assert isinstance(params, dict)
            assert "position_size" in params
            assert "stop_loss_pct" in params
            assert "take_profit_pct" in params
            assert "signal_filter" in params

    def test_position_size_in_range(self):
        for regime in REGIME_LABELS:
            ps = self.strategy.get_params(regime)["position_size"]
            assert 0.0 <= ps <= 1.0, f"position_size out of range for {regime}"

    def test_bull_has_largest_position_size(self):
        bull_ps = self.strategy.get_params("Bull")["position_size"]
        for regime in ["Bear", "High-Volatility", "Sideways"]:
            assert bull_ps >= self.strategy.get_params(regime)["position_size"]

    def test_bear_has_smallest_stop_loss(self):
        bear_sl = self.strategy.get_params("Bear")["stop_loss_pct"]
        for regime in ["Bull", "High-Volatility", "Sideways"]:
            assert bear_sl <= self.strategy.get_params(regime)["stop_loss_pct"]

    def test_unknown_regime_returns_fallback(self):
        params = self.strategy.get_params("DOES_NOT_EXIST")
        assert "position_size" in params

    def test_signal_multiplier_matches_position_size(self):
        for regime in REGIME_LABELS:
            mult = self.strategy.get_signal_multiplier(regime)
            ps = self.strategy.get_params(regime)["position_size"]
            assert mult == pytest.approx(ps)

    def test_apply_to_series_returns_dataframe(self):
        dates = pd.date_range("2020-01-01", periods=5, freq="B")
        regimes = pd.Series(["Bull", "Bear", "Sideways", "High-Volatility", "Unknown"], index=dates)
        df = self.strategy.apply_to_series(regimes)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5
        assert "position_size" in df.columns

    def test_custom_params_override(self):
        custom = {"Bull": {"position_size": 0.75}}
        strategy = AdaptiveStrategy(custom_params=custom)
        assert strategy.get_params("Bull")["position_size"] == 0.75

    def test_regime_summary_returns_dataframe(self):
        summary = self.strategy.regime_summary()
        assert isinstance(summary, pd.DataFrame)
        assert "Position Size" in summary.columns
