"""
models/base_model.py — Abstract base class for all regime detection models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
import pandas as pd


class BaseRegimeModel(ABC):
    """Common interface for HMM and GMM regime models.

    Every concrete model must implement:
      - ``fit(X)``     — train on feature matrix *X*
      - ``predict(X)`` — return integer state sequence for *X*
      - ``bic(X)``     — Bayesian Information Criterion (lower = better)
      - ``n_states``   — number of discovered regimes
    """

    @abstractmethod
    def fit(self, X: np.ndarray) -> "BaseRegimeModel":
        """Fit the model to the (scaled) feature matrix.

        Parameters
        ----------
        X : np.ndarray, shape (n_samples, n_features)

        Returns
        -------
        self
        """

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return integer state labels, shape (n_samples,)."""

    @abstractmethod
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return soft state probabilities, shape (n_samples, n_states)."""

    @abstractmethod
    def bic(self, X: np.ndarray) -> float:
        """Bayesian Information Criterion for *X* given the fitted model."""

    @property
    @abstractmethod
    def n_states(self) -> int:
        """Number of hidden/mixture states in the fitted model."""

    # ------------------------------------------------------------------
    # Optional convenience methods (not abstract; subclasses may override)
    # ------------------------------------------------------------------

    def get_state_stats(
        self, X: np.ndarray, feature_names: Optional[list] = None
    ) -> pd.DataFrame:
        """Return per-state mean and std for each feature.

        Parameters
        ----------
        X :
            Scaled feature matrix used for prediction.
        feature_names :
            Optional list of column names; used as column index.

        Returns
        -------
        pd.DataFrame with MultiIndex columns (stat × feature).
        """
        labels = self.predict(X)
        n_feat = X.shape[1]
        cols = feature_names if feature_names else [f"f{i}" for i in range(n_feat)]
        rows = []
        for s in range(self.n_states):
            mask = labels == s
            subset = X[mask]
            row = {
                **{f"mean_{c}": subset[:, i].mean() for i, c in enumerate(cols)},
                **{f"std_{c}": subset[:, i].std() for i, c in enumerate(cols)},
                "count": mask.sum(),
            }
            rows.append(row)
        return pd.DataFrame(rows, index=[f"State {s}" for s in range(self.n_states)])
