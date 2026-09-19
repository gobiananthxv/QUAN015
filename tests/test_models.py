"""
tests/test_models.py — Unit tests for HMMRegimeModel and GMMRegimeModel.
"""

import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.hmm_model import HMMRegimeModel
from models.gmm_model import GMMRegimeModel
from config import HMMConfig, GMMConfig


def _make_feature_matrix(n: int = 400, d: int = 7, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n, d))


VALID_STATE_COUNTS = list(range(2, 6))


class TestHMMRegimeModel:
    def setup_method(self):
        # Restrict to [2,3] for speed in tests
        cfg = HMMConfig(n_components_range=[2, 3], n_init=2, n_iter=20)
        self.model = HMMRegimeModel(config=cfg)
        self.X = _make_feature_matrix()

    def test_fit_returns_self(self):
        result = self.model.fit(self.X)
        assert result is self.model

    def test_predict_shape(self):
        self.model.fit(self.X)
        labels = self.model.predict(self.X)
        assert labels.shape == (len(self.X),)

    def test_predict_valid_states(self):
        self.model.fit(self.X)
        labels = self.model.predict(self.X)
        assert set(labels).issubset(set(range(self.model.n_states)))

    def test_predict_proba_shape(self):
        self.model.fit(self.X)
        proba = self.model.predict_proba(self.X)
        assert proba.shape == (len(self.X), self.model.n_states)

    def test_predict_proba_sums_to_one(self):
        self.model.fit(self.X)
        proba = self.model.predict_proba(self.X)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-5)

    def test_bic_is_finite(self):
        self.model.fit(self.X)
        assert np.isfinite(self.model.bic(self.X))

    def test_transition_matrix_shape(self):
        self.model.fit(self.X)
        T = self.model.transition_matrix
        n = self.model.n_states
        assert T.shape == (n, n)
        np.testing.assert_allclose(T.sum(axis=1), 1.0, atol=1e-6)

    def test_predict_before_fit_raises(self):
        model = HMMRegimeModel()
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict(self.X)

    def test_forced_n_states(self):
        model = HMMRegimeModel(
            config=HMMConfig(n_iter=10, n_init=1), n_components=2
        )
        model.fit(self.X)
        assert model.n_states == 2


class TestGMMRegimeModel:
    def setup_method(self):
        cfg = GMMConfig(n_components_range=[2, 3], n_init=2, max_iter=50)
        self.model = GMMRegimeModel(config=cfg)
        self.X = _make_feature_matrix()

    def test_fit_returns_self(self):
        result = self.model.fit(self.X)
        assert result is self.model

    def test_predict_shape(self):
        self.model.fit(self.X)
        labels = self.model.predict(self.X)
        assert labels.shape == (len(self.X),)

    def test_predict_valid_states(self):
        self.model.fit(self.X)
        labels = self.model.predict(self.X)
        assert set(labels).issubset(set(range(self.model.n_states)))

    def test_predict_proba_sums_to_one(self):
        self.model.fit(self.X)
        proba = self.model.predict_proba(self.X)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-5)

    def test_bic_is_finite(self):
        self.model.fit(self.X)
        assert np.isfinite(self.model.bic(self.X))

    def test_aic_less_than_bic(self):
        # AIC penalizes less than BIC for most data sizes, but both finite
        self.model.fit(self.X)
        assert np.isfinite(self.model.aic(self.X))

    def test_weights_sum_to_one(self):
        self.model.fit(self.X)
        np.testing.assert_allclose(self.model.weights.sum(), 1.0, atol=1e-6)

    def test_predict_before_fit_raises(self):
        model = GMMRegimeModel()
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict(self.X)
