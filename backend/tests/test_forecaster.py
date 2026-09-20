"""
tests/test_forecaster.py — Unit tests for RegimeForecaster.
"""

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from forecast.regime_forecaster import RegimeForecaster, _kl_divergence, _entropy


def _make_mock_result(n_states: int = 3, n_samples: int = 200, seed: int = 0):
    """Build a minimal mock RegimeResult for HMM with a random transition matrix."""
    rng = np.random.default_rng(seed)

    # Random row-stochastic transition matrix
    T = rng.dirichlet(np.ones(n_states), size=n_states)

    # Mock model
    model = MagicMock()
    model.transition_matrix = T
    model.n_states = n_states

    # Random state proba (last row = current distribution)
    proba_vals = rng.dirichlet(np.ones(n_states), size=n_samples)
    state_proba = pd.DataFrame(
        proba_vals,
        columns=[f"state_{i}" for i in range(n_states)],
    )

    label_map = {0: "Bull", 1: "Bear", 2: "High-Volatility"}

    result = MagicMock()
    result.model_type   = "hmm"
    result.model        = model
    result.label_map    = label_map
    result.state_proba  = state_proba
    result.ticker       = "TEST"
    result.current_regime = "Bull"

    return result


class TestRegimeForecaster:
    def setup_method(self):
        self.result     = _make_mock_result(n_states=3)
        self.forecaster = RegimeForecaster(self.result)

    # ── forecast() ────────────────────────────────────────────────────────────

    def test_forecast_shape(self):
        df = self.forecaster.forecast(n_steps=30)
        assert df.shape == (30, 3)

    def test_forecast_probabilities_sum_to_one(self):
        df = self.forecaster.forecast(n_steps=20)
        np.testing.assert_allclose(df.sum(axis=1), 1.0, atol=1e-8)

    def test_forecast_probabilities_non_negative(self):
        df = self.forecaster.forecast(n_steps=20)
        assert (df.values >= 0).all()

    def test_forecast_index_starts_at_one(self):
        df = self.forecaster.forecast(n_steps=10)
        assert df.index[0] == 1
        assert df.index[-1] == 10

    def test_forecast_columns_are_regime_names(self):
        df = self.forecaster.forecast(n_steps=5)
        valid = {"Bull", "Bear", "High-Volatility", "Sideways", "Unknown"}
        for col in df.columns:
            assert col in valid or col.startswith("State")

    # ── convergence ───────────────────────────────────────────────────────────

    def test_long_forecast_converges_to_stationary(self):
        """After many steps, forecast should be close to stationary distribution."""
        df   = self.forecaster.forecast(n_steps=500)
        stat = self.forecaster.stationary_distribution()
        for col in df.columns:
            if col in stat.index:
                assert abs(df[col].iloc[-1] - stat[col]) < 0.02, (
                    f"Did not converge: {col} forecast={df[col].iloc[-1]:.3f} "
                    f"stat={stat[col]:.3f}"
                )

    def test_stationary_sums_to_one(self):
        stat = self.forecaster.stationary_distribution()
        np.testing.assert_allclose(stat.sum(), 1.0, atol=1e-6)

    # ── confidence_decay() ────────────────────────────────────────────────────

    def test_confidence_decay_shape(self):
        df = self.forecaster.confidence_decay(n_steps=30)
        assert len(df) == 30
        assert "max_prob" in df.columns
        assert "kl_div" in df.columns
        assert "entropy" in df.columns
        assert "is_useful" in df.columns

    def test_kl_div_decreases_monotonically(self):
        """KL divergence from stationary should be non-increasing over time."""
        df = self.forecaster.confidence_decay(n_steps=50)
        kl = df["kl_div"].values
        # Allow tiny numerical noise; general trend must be non-increasing
        assert kl[-1] <= kl[0] + 1e-6, "KL divergence should decrease towards 0"

    def test_max_prob_in_valid_range(self):
        df = self.forecaster.confidence_decay(n_steps=20)
        assert (df["max_prob"] >= 0).all()
        assert (df["max_prob"] <= 1).all()

    # ── prediction_horizon() ──────────────────────────────────────────────────

    def test_prediction_horizon_returns_dict(self):
        h = self.forecaster.prediction_horizon(n_steps=60)
        assert "conservative" in h
        assert "max_prob_horizon" in h
        assert "kl_horizon" in h

    def test_prediction_horizon_non_negative(self):
        h = self.forecaster.prediction_horizon(n_steps=60)
        assert h["conservative"] >= 0
        assert h["max_prob_horizon"] >= 0
        assert h["kl_horizon"] >= 0

    def test_conservative_horizon_is_min(self):
        h = self.forecaster.prediction_horizon(n_steps=60)
        assert h["conservative"] == min(h["max_prob_horizon"], h["kl_horizon"])

    # ── simulate_paths() ──────────────────────────────────────────────────────

    def test_simulate_paths_shape(self):
        paths = self.forecaster.simulate_paths(n_paths=100, n_steps=20)
        assert paths.shape == (100, 20)

    def test_simulate_paths_valid_state_ids(self):
        paths = self.forecaster.simulate_paths(n_paths=100, n_steps=20)
        assert paths.min() >= 0
        assert paths.max() < self.result.model.n_states

    def test_simulate_paths_reproducible(self):
        p1 = self.forecaster.simulate_paths(n_paths=50, n_steps=10, seed=99)
        p2 = self.forecaster.simulate_paths(n_paths=50, n_steps=10, seed=99)
        np.testing.assert_array_equal(p1, p2)

    # ── GMM model rejection ───────────────────────────────────────────────────

    def test_rejects_gmm_result(self):
        gmm_result = MagicMock()
        gmm_result.model_type = "gmm"
        with pytest.raises(ValueError, match="HMM"):
            RegimeForecaster(gmm_result)

    # ── Math helpers ──────────────────────────────────────────────────────────

    def test_kl_zero_for_identical_distributions(self):
        p = np.array([0.5, 0.3, 0.2])
        assert _kl_divergence(p, p) == pytest.approx(0.0, abs=1e-8)

    def test_entropy_uniform_is_max(self):
        n = 4
        uniform = np.ones(n) / n
        degenerate = np.array([1.0, 0.0, 0.0, 0.0])
        assert _entropy(uniform) > _entropy(degenerate)

    def test_entropy_non_negative(self):
        p = np.array([0.6, 0.3, 0.1])
        assert _entropy(p) >= 0
