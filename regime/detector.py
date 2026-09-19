"""
regime/detector.py — Orchestrates the full regime detection pipeline.

Pipeline
--------
DataLoader → FeatureEngineer → HMMRegimeModel / GMMRegimeModel
           → RegimeLabeler   → pd.Series of regime names

Usage
-----
    detector = RegimeDetector(ticker="SPY", model_type="hmm")
    result = detector.run(start="2010-01-01")
    print(result.regime_series.tail())
    print(result.current_regime)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional

import numpy as np
import pandas as pd

from config import (
    DEFAULT_START_DATE,
    DEFAULT_TICKER,
)
from data.data_loader import DataLoader
from features.feature_engineering import FeatureEngineer
from models.base_model import BaseRegimeModel
from models.gmm_model import GMMRegimeModel
from models.hmm_model import HMMRegimeModel
from regime.labeler import RegimeLabeler

logger = logging.getLogger(__name__)

ModelType = Literal["hmm", "gmm"]


@dataclass
class RegimeResult:
    """Container for all outputs produced by :class:`RegimeDetector`."""

    ticker: str
    model_type: str
    regime_series: pd.Series                      # DatetimeIndex → regime label
    raw_state_series: pd.Series                   # DatetimeIndex → int state ID
    state_proba: pd.DataFrame                     # DatetimeIndex → per-state probabilities
    label_map: Dict[int, str]                     # state ID → regime name
    cluster_stats: pd.DataFrame                   # per-state statistics
    price_data: pd.DataFrame                      # original OHLCV
    feature_data: pd.DataFrame                    # raw (unscaled) features
    model: BaseRegimeModel                        # fitted model object
    n_states: int = field(init=False)

    def __post_init__(self) -> None:
        self.n_states = self.model.n_states

    @property
    def current_regime(self) -> str:
        """The most recently detected regime label."""
        return self.regime_series.iloc[-1]

    @property
    def regime_counts(self) -> pd.Series:
        """Day-counts per regime label."""
        return self.regime_series.value_counts()

    def summary(self) -> str:
        lines = [
            f"Ticker     : {self.ticker}",
            f"Model      : {self.model_type.upper()}",
            f"N states   : {self.n_states}",
            f"Date range : {self.regime_series.index[0].date()} → "
            f"{self.regime_series.index[-1].date()}",
            f"Current    : {self.current_regime}",
            "",
            "Regime distribution:",
        ]
        for label, count in self.regime_counts.items():
            pct = 100 * count / len(self.regime_series)
            lines.append(f"  {label:<18} {count:>5} days  ({pct:.1f}%)")
        return "\n".join(lines)


class RegimeDetector:
    """End-to-end regime detection pipeline.

    Parameters
    ----------
    ticker :
        Yahoo Finance symbol to analyze.
    model_type :
        ``"hmm"`` for Hidden Markov Model, ``"gmm"`` for Gaussian Mixture.
    n_components :
        Fixed number of states. ``None`` → auto-select via BIC.
    cache_dir :
        Directory for OHLCV CSV cache.
    """

    def __init__(
        self,
        ticker: str = DEFAULT_TICKER,
        model_type: ModelType = "hmm",
        n_components: Optional[int] = None,
        cache_dir: str = "data_cache",
    ) -> None:
        self.ticker = ticker
        self.model_type = model_type
        self.n_components = n_components
        self._loader = DataLoader(cache_dir=cache_dir)
        self._feat_eng = FeatureEngineer()
        self._model: Optional[BaseRegimeModel] = None
        self._labeler: Optional[RegimeLabeler] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        start: str = DEFAULT_START_DATE,
        end: Optional[str] = None,
        force_download: bool = False,
    ) -> RegimeResult:
        """Execute the full pipeline and return a :class:`RegimeResult`.

        Parameters
        ----------
        start :
            Start date string ``YYYY-MM-DD``.
        end :
            End date string (inclusive). ``None`` → today.
        force_download :
            Re-download data even if cached.
        """
        logger.info(
            "Running %s regime detector for %s (%s → %s)",
            self.model_type.upper(),
            self.ticker,
            start,
            end or "today",
        )

        # 1. Load data ─────────────────────────────────────────────────
        price_df = self._loader.load(
            self.ticker, start=start, end=end, force_download=force_download
        )

        # 2. Feature engineering ───────────────────────────────────────
        X_scaled, valid_idx = self._feat_eng.fit_transform(price_df)
        raw_features = self._feat_eng.get_raw_features(price_df)

        # 3. Build & fit model ─────────────────────────────────────────
        model = self._build_model()
        logger.info("Fitting %s …", self.model_type.upper())
        model.fit(X_scaled)
        self._model = model

        # 4. Decode state sequence ─────────────────────────────────────
        raw_states = model.predict(X_scaled)
        state_proba = model.predict_proba(X_scaled)

        raw_state_series = pd.Series(raw_states, index=valid_idx, name="state")
        state_proba_df = pd.DataFrame(
            state_proba,
            index=valid_idx,
            columns=[f"state_{i}" for i in range(model.n_states)],
        )

        # 5. Semantic labeling ─────────────────────────────────────────
        labeler = RegimeLabeler(feature_names=FeatureEngineer.FEATURE_NAMES)
        # Pass raw (unscaled) features so labeler sees real return/vol magnitudes
        labeler.fit(raw_features.values, raw_states)
        self._labeler = labeler

        regime_series = labeler.transform(raw_states)
        regime_series.index = valid_idx
        regime_series.name = "regime"

        logger.info("Detection complete. Current regime: %s", regime_series.iloc[-1])

        return RegimeResult(
            ticker=self.ticker,
            model_type=self.model_type,
            regime_series=regime_series,
            raw_state_series=raw_state_series,
            state_proba=state_proba_df,
            label_map=labeler.label_map,
            cluster_stats=labeler.cluster_stats,
            price_data=price_df,
            feature_data=raw_features,
            model=model,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_model(self) -> BaseRegimeModel:
        if self.model_type == "hmm":
            return HMMRegimeModel(n_components=self.n_components)
        if self.model_type == "gmm":
            return GMMRegimeModel(n_components=self.n_components)
        raise ValueError(
            f"Unknown model_type '{self.model_type}'. Choose 'hmm' or 'gmm'."
        )
