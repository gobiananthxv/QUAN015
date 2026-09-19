"""
features/feature_engineering.py — Compute the feature matrix fed into HMM/GMM.

Features (all normalized with StandardScaler before modelling):
  - log_return_5d        : 5-day rolling log return
  - log_return_21d       : 21-day rolling log return
  - realized_vol_21d     : 21-day realized volatility (annualized)
  - sma50_dist           : % distance from 50-day SMA
  - sma200_dist          : % distance from 200-day SMA
  - ema_ratio            : EMA-12 / EMA-26  (MACD-like ratio)
  - high_vol_flag        : 1 if realized_vol_21d > VOL_SPIKE_MULTIPLIER × long-term median
"""

from __future__ import annotations

import logging
from typing import List, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from config import (
    RETURN_WINDOWS,
    VOLATILITY_WINDOW,
    SMA_WINDOWS,
    EMA_SHORT,
    EMA_LONG,
    TRADING_DAYS_PER_YEAR,
    VOL_SPIKE_MULTIPLIER,
)

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Compute and scale the feature matrix from OHLCV data.

    Parameters
    ----------
    return_windows :
        List of rolling windows (in days) for log-return features.
    vol_window :
        Window for realized volatility calculation.
    sma_windows :
        List of windows for SMA distance features.
    ema_short / ema_long :
        Spans for the EMA ratio feature.
    """

    FEATURE_NAMES: List[str] = [
        "log_return_5d",
        "log_return_21d",
        "realized_vol_21d",
        "sma50_dist",
        "sma200_dist",
        "ema_ratio",
        "high_vol_flag",
    ]

    def __init__(
        self,
        return_windows: List[int] = RETURN_WINDOWS,
        vol_window: int = VOLATILITY_WINDOW,
        sma_windows: List[int] = SMA_WINDOWS,
        ema_short: int = EMA_SHORT,
        ema_long: int = EMA_LONG,
    ) -> None:
        self.return_windows = return_windows
        self.vol_window = vol_window
        self.sma_windows = sma_windows
        self.ema_short = ema_short
        self.ema_long = ema_long
        self._scaler: StandardScaler = StandardScaler()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit_transform(self, df: pd.DataFrame) -> Tuple[np.ndarray, pd.Index]:
        """Compute raw features, fit scaler, and return scaled array.

        Parameters
        ----------
        df :
            OHLCV DataFrame with at least a ``close`` column and a
            ``DatetimeIndex``.

        Returns
        -------
        X : np.ndarray, shape (n_samples, n_features)
            Scaled feature matrix (NaN rows dropped).
        valid_index : pd.DatetimeIndex
            The index of rows that survived NaN-dropping.
        """
        raw = self._compute_raw_features(df)
        clean = raw.dropna()
        if clean.empty:
            raise ValueError("All feature rows contain NaN — check your data length.")
        logger.info(
            "Feature matrix: %d rows × %d features (dropped %d NaN rows)",
            len(clean),
            clean.shape[1],
            len(raw) - len(clean),
        )
        X_scaled = self._scaler.fit_transform(clean.values)
        return X_scaled, clean.index

    def transform(self, df: pd.DataFrame) -> Tuple[np.ndarray, pd.Index]:
        """Transform new data using a previously fitted scaler.

        Raises
        ------
        RuntimeError
            If the scaler hasn't been fitted yet (call ``fit_transform`` first).
        """
        if not hasattr(self._scaler, "mean_"):
            raise RuntimeError("Scaler not fitted. Call fit_transform() on training data first.")
        raw = self._compute_raw_features(df)
        clean = raw.dropna()
        X_scaled = self._scaler.transform(clean.values)
        return X_scaled, clean.index

    def get_raw_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return the un-scaled feature DataFrame (for inspection / plotting)."""
        return self._compute_raw_features(df).dropna()

    # ------------------------------------------------------------------
    # Internal feature computation
    # ------------------------------------------------------------------

    def _compute_raw_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build the raw (unscaled) feature DataFrame from close prices."""
        close = df["close"].copy().astype(float)
        log_ret = np.log(close / close.shift(1))

        features = pd.DataFrame(index=df.index)

        # ── Rolling log returns ──────────────────────────────────────
        for w in self.return_windows:
            col = f"log_return_{w}d"
            features[col] = log_ret.rolling(w).sum()

        # ── Realized volatility (annualized) ────────────────────────
        features["realized_vol_21d"] = (
            log_ret.rolling(self.vol_window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        )

        # ── SMA distances ────────────────────────────────────────────
        for sma_w in self.sma_windows:
            sma = close.rolling(sma_w).mean()
            features[f"sma{sma_w}_dist"] = (close - sma) / sma

        # ── EMA ratio (MACD proxy) ───────────────────────────────────
        ema_s = close.ewm(span=self.ema_short, adjust=False).mean()
        ema_l = close.ewm(span=self.ema_long, adjust=False).mean()
        features["ema_ratio"] = ema_s / ema_l

        # ── High-volatility binary flag ──────────────────────────────
        long_term_median_vol = features["realized_vol_21d"].expanding().median()
        features["high_vol_flag"] = (
            features["realized_vol_21d"] > VOL_SPIKE_MULTIPLIER * long_term_median_vol
        ).astype(float)

        return features
