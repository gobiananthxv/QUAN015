"""
models/gmm_model.py — GaussianMixture regime model via scikit-learn.

Key design choices:
  - Automatically selects n_components in [2, 5] by BIC.
  - Provides soft regime probabilities (posterior membership per state).
  - Uses full covariance to capture inter-feature correlations.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from sklearn.mixture import GaussianMixture

from config import GMM_CONFIG, GMMConfig
from models.base_model import BaseRegimeModel

logger = logging.getLogger(__name__)


class GMMRegimeModel(BaseRegimeModel):
    """Gaussian Mixture Model for market regime detection.

    Parameters
    ----------
    config :
        :class:`GMMConfig` dataclass; if ``None``, the global default is used.
    n_components :
        If given, fixes the number of mixture components rather than
        auto-selecting via BIC.
    """

    def __init__(
        self,
        config: Optional[GMMConfig] = None,
        n_components: Optional[int] = None,
    ) -> None:
        self.config = config or GMM_CONFIG
        self._forced_n = n_components
        self._model: Optional[GaussianMixture] = None
        self._best_n: int = 0

    # ------------------------------------------------------------------
    # BaseRegimeModel interface
    # ------------------------------------------------------------------

    def fit(self, X: np.ndarray) -> "GMMRegimeModel":
        """Fit the best GaussianMixture to *X* (auto-select via BIC if needed)."""
        if self._forced_n is not None:
            candidates = [self._forced_n]
        else:
            candidates = self.config.n_components_range

        bic_scores = {}
        models = {}

        for n in candidates:
            model = GaussianMixture(
                n_components=n,
                covariance_type=self.config.covariance_type,
                n_init=self.config.n_init,
                max_iter=self.config.max_iter,
                tol=self.config.tol,
                random_state=self.config.random_state,
            )
            model.fit(X)
            score = model.bic(X)
            bic_scores[n] = score
            models[n] = model
            logger.info("  n_components=%d  BIC=%.2f", n, score)

        best_n = min(bic_scores, key=bic_scores.__getitem__)
        self._model = models[best_n]
        self._best_n = best_n
        logger.info(
            "GMM selected: n_components=%d  BIC=%.2f", best_n, bic_scores[best_n]
        )
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return hard cluster labels (argmax of posteriors), shape (n_samples,)."""
        self._check_fitted()
        return self._model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return soft posterior probabilities, shape (n_samples, n_components)."""
        self._check_fitted()
        return self._model.predict_proba(X)

    def bic(self, X: np.ndarray) -> float:
        """BIC of the fitted model on *X*."""
        self._check_fitted()
        return float(self._model.bic(X))

    def aic(self, X: np.ndarray) -> float:
        """Akaike Information Criterion of the fitted model on *X*."""
        self._check_fitted()
        return float(self._model.aic(X))

    @property
    def n_states(self) -> int:
        return self._best_n

    # ------------------------------------------------------------------
    # GMM-specific properties
    # ------------------------------------------------------------------

    @property
    def means(self) -> np.ndarray:
        """Component means, shape (n_components, n_features)."""
        self._check_fitted()
        return self._model.means_

    @property
    def covariances(self) -> np.ndarray:
        """Component covariance matrices."""
        self._check_fitted()
        return self._model.covariances_

    @property
    def weights(self) -> np.ndarray:
        """Mixture weights (prior probabilities), shape (n_components,)."""
        self._check_fitted()
        return self._model.weights_

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_fitted(self) -> None:
        if self._model is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
