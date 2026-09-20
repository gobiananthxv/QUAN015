"""
regime/labeler.py — Maps raw cluster IDs (0, 1, 2, …) to human-readable
                    semantic regime names (Bull, Bear, High-Volatility, Sideways).

Algorithm
---------
1. For each cluster, compute the mean annualized log return and mean
   annualized realized volatility across all member days.
2. Apply rule-based assignment (priority order):
   - High-Volatility : vol > HIGH_VOL_THRESHOLD (regardless of return)
   - Bear            : return < BEAR_RETURN_THRESHOLD
   - Bull            : return > BULL_RETURN_THRESHOLD
   - Sideways        : everything else
3. If two clusters would get the same label, the one with the "more extreme"
   characteristic keeps it, and the duplicate gets the next best fit.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

from config import (
    BULL_RETURN_THRESHOLD,
    BEAR_RETURN_THRESHOLD,
    HIGH_VOL_THRESHOLD,
    TRADING_DAYS_PER_YEAR,
    REGIME_LABELS,
)

logger = logging.getLogger(__name__)


class RegimeLabeler:
    """Assigns human-readable labels to raw integer cluster IDs.

    Parameters
    ----------
    feature_names :
        List of feature column names in the same order as in the feature
        matrix *X*.  Used to locate ``log_return_21d`` and
        ``realized_vol_21d``.
    """

    # Priority of regime assignment (highest → lowest)
    _PRIORITY = ["High-Volatility", "Bear", "Bull", "Sideways", "Transitional"]

    def __init__(self, feature_names: List[str]) -> None:
        self.feature_names = feature_names
        self._label_map: Dict[int, str] = {}
        self._cluster_stats: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        X: np.ndarray,
        raw_labels: np.ndarray,
    ) -> "RegimeLabeler":
        """Derive cluster statistics and build the cluster-ID → label map.

        Parameters
        ----------
        X :
            **Unscaled** (raw) feature matrix, shape (n_samples, n_features).
            Must have the same column order as ``self.feature_names``.
        raw_labels :
            Integer cluster IDs from the model, shape (n_samples,).

        Returns
        -------
        self
        """
        stats = self._compute_cluster_stats(X, raw_labels)
        self._cluster_stats = stats
        self._label_map = self._assign_labels(stats)
        logger.info("Regime label map: %s", self._label_map)
        return self

    def transform(self, raw_labels: np.ndarray) -> pd.Series:
        """Map raw integer cluster IDs to semantic regime name strings."""
        if not self._label_map:
            raise RuntimeError("Labeler not fitted. Call fit() first.")
        return pd.Series(raw_labels).map(self._label_map).fillna("Transitional")

    def fit_transform(
        self,
        X: np.ndarray,
        raw_labels: np.ndarray,
    ) -> pd.Series:
        """Convenience: fit then transform."""
        return self.fit(X, raw_labels).transform(raw_labels)

    @property
    def label_map(self) -> Dict[int, str]:
        """Dict mapping cluster ID → regime name."""
        return dict(self._label_map)

    @property
    def cluster_stats(self) -> pd.DataFrame:
        """Per-cluster mean return, mean volatility, and day-count."""
        return self._cluster_stats.copy()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_cluster_stats(
        self, X: np.ndarray, raw_labels: np.ndarray
    ) -> pd.DataFrame:
        """Return a DataFrame with per-cluster annualized return and vol."""
        df = pd.DataFrame(X, columns=self.feature_names)
        df["_cluster"] = raw_labels

        # Use 21-day log return (already rolling sum) → annualize
        ret_col = "log_return_21d" if "log_return_21d" in df.columns else df.columns[0]
        vol_col = "realized_vol_21d" if "realized_vol_21d" in df.columns else df.columns[2]

        rows = []
        for cid, grp in df.groupby("_cluster"):
            # 21d return → annualize: multiply by (252/21)
            ann_ret = grp[ret_col].mean() * (TRADING_DAYS_PER_YEAR / 21)
            ann_vol = grp[vol_col].mean()  # already annualized in feature engineering
            rows.append(
                {
                    "cluster_id": int(cid),
                    "mean_ann_return": ann_ret,
                    "mean_ann_vol": ann_vol,
                    "count": len(grp),
                }
            )

        return pd.DataFrame(rows).set_index("cluster_id")

    def _assign_labels(self, stats: pd.DataFrame) -> Dict[int, str]:
        """Greedy label assignment with de-duplication."""
        # Score each cluster for each regime (lower = better fit)
        label_map: Dict[int, str] = {}
        assigned: Dict[str, int] = {}   # label → cluster_id already assigned

        # Sort clusters by "extremity" so the most obvious ones win ties
        # (highest vol first, then lowest return, then highest return)
        cluster_ids = stats.index.tolist()

        def _best_label(cid: int) -> str:
            ann_ret = stats.loc[cid, "mean_ann_return"]
            ann_vol = stats.loc[cid, "mean_ann_vol"]
            if ann_vol > HIGH_VOL_THRESHOLD:
                return "High-Volatility"
            if ann_ret < BEAR_RETURN_THRESHOLD:
                return "Bear"
            if ann_ret > BULL_RETURN_THRESHOLD:
                return "Bull"
            return "Sideways"

        # Sort by volatility descending so high-vol clusters get priority
        sorted_ids = sorted(cluster_ids, key=lambda c: stats.loc[c, "mean_ann_vol"], reverse=True)

        for cid in sorted_ids:
            preferred = _best_label(cid)
            # Try priority list until we find an unassigned label
            for candidate in [preferred] + [l for l in self._PRIORITY if l != preferred]:
                if candidate not in assigned:
                    label_map[cid] = candidate
                    assigned[candidate] = cid
                    break
            else:
                label_map[cid] = "Transitional"

        return label_map

