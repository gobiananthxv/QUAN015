"""
models/hmm_model.py — GaussianHMM regime model via hmmlearn.

Key design choices:
  - Automatically selects n_components in [2, 5] by BIC (run multiple times
    with different random seeds and pick the best).
  - Uses Viterbi decoding to extract the most likely state sequence.
  - Exposes the learned transition matrix for interpretability.
"""

from __future__ import annotations

import logging
import warnings
from typing import List, Optional

import numpy as np
from hmmlearn.hmm import GaussianHMM

from config import HMM_CONFIG, HMMConfig
from models.base_model import BaseRegimeModel

logger = logging.getLogger(__name__)


class HMMRegimeModel(BaseRegimeModel):
    """Gaussian Hidden Markov Model for market regime detection.

    Parameters
    ----------
    config :
        :class:`HMMConfig` dataclass; if ``None``, the global default is used.
    n_components :
        If given, fixes the number of states rather than auto-selecting via BIC.
    """

    def __init__(
        self,
        config: Optional[HMMConfig] = None,
        n_components: Optional[int] = None,
    ) -> None:
        self.config = config or HMM_CONFIG
        self._forced_n = n_components
        self._model: Optional[GaussianHMM] = None
        self._best_n: int = 0

    # ------------------------------------------------------------------
    # BaseRegimeModel interface
    # ------------------------------------------------------------------

    def fit(self, X: np.ndarray) -> "HMMRegimeModel":
        """Fit the best GaussianHMM to *X* (auto-select via BIC if needed)."""
        if self._forced_n is not None:
            candidates = [self._forced_n]
        else:
            candidates = self.config.n_components_range

        best_bic = np.inf
        best_model: Optional[GaussianHMM] = None
        best_n = candidates[0]

        for n in candidates:
            model, score = self._fit_with_restarts(X, n)
            logger.info("  n_states=%d  BIC=%.2f", n, score)
            if score < best_bic:
                best_bic = score
                best_model = model
                best_n = n

        self._model = best_model
        self._best_n = best_n
        logger.info(
            "HMM selected: n_states=%d  BIC=%.2f", self._best_n, best_bic
        )
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return the Viterbi-decoded state sequence, shape (n_samples,)."""
        self._check_fitted()
        _, states = self._model.decode(X, algorithm=self.config.algorithm)
        return states

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return posterior state probabilities via the forward–backward algorithm."""
        self._check_fitted()
        return self._model.predict_proba(X)

    def bic(self, X: np.ndarray) -> float:
        """BIC of the fitted model on *X*."""
        self._check_fitted()
        return self._compute_bic(self._model, X)

    @property
    def n_states(self) -> int:
        return self._best_n

    # ------------------------------------------------------------------
    # HMM-specific properties
    # ------------------------------------------------------------------

    @property
    def transition_matrix(self) -> np.ndarray:
        """State transition probability matrix, shape (n_states, n_states)."""
        self._check_fitted()
        return self._model.transmat_

    @property
    def emission_means(self) -> np.ndarray:
        """Mean of each state's emission Gaussian, shape (n_states, n_features)."""
        self._check_fitted()
        return self._model.means_

    @property
    def emission_covars(self) -> np.ndarray:
        """Covariance matrices, shape (n_states, n_features, n_features)."""
        self._check_fitted()
        return self._model.covars_

    @property
    def log_likelihood(self) -> float:
        """Log-likelihood of the training data under the fitted model."""
        self._check_fitted()
        return self._model.monitor_.history[-1] if self._model.monitor_ else float("nan")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fit_with_restarts(
        self, X: np.ndarray, n: int
    ) -> tuple[GaussianHMM, float]:
        """Run ``n_init`` restarts and return the (model, BIC) with the best score."""
        best_bic = np.inf
        best_model: Optional[GaussianHMM] = None

        lengths = [len(X)]  # single contiguous sequence

        for seed in range(self.config.n_init):
            model = GaussianHMM(
                n_components=n,
                covariance_type=self.config.covariance_type,
                n_iter=self.config.n_iter,
                tol=self.config.tol,
                random_state=self.config.random_state + seed,
                verbose=False,
            )
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model.fit(X, lengths=lengths)
                score = self._compute_bic(model, X)
                if score < best_bic:
                    best_bic = score
                    best_model = model
            except Exception as exc:  # noqa: BLE001
                logger.debug("HMM fit failed (n=%d, seed=%d): %s", n, seed, exc)

        if best_model is None:
            raise RuntimeError(
                f"All {self.config.n_init} HMM restarts failed for n_states={n}."
            )
        return best_model, best_bic

    @staticmethod
    def _compute_bic(model: GaussianHMM, X: np.ndarray) -> float:
        """Compute BIC = -2·log_likelihood + k·ln(n).

        ``k`` is the number of free parameters in a full-covariance GaussianHMM.
        """
        n, d = X.shape
        k_n = model.n_components
        # Free params: initial probs (k-1), transition (k*(k-1)),
        # means (k*d), covariances (k * d*(d+1)/2 for full)
        k_params = (
            (k_n - 1)
            + k_n * (k_n - 1)
            + k_n * d
            + k_n * d * (d + 1) // 2
        )
        try:
            log_l = model.score(X)
        except Exception:  # noqa: BLE001
            return np.inf
        return -2 * log_l + k_params * np.log(n)

    def _check_fitted(self) -> None:
        if self._model is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
