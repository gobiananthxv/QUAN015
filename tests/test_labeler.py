"""
tests/test_labeler.py — Unit tests for RegimeLabeler.
"""

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from regime.labeler import RegimeLabeler
from features.feature_engineering import FeatureEngineer


def _make_synthetic_features(n: int = 400, seed: int = 7) -> np.ndarray:
    """Generate raw (unscaled) feature matrix with plausible financial ranges."""
    rng = np.random.default_rng(seed)
    # log_return_5d, log_return_21d, realized_vol_21d,
    # sma50_dist, sma200_dist, ema_ratio, high_vol_flag
    X = np.column_stack([
        rng.normal(0.01, 0.05, n),      # log_return_5d
        rng.normal(0.04, 0.10, n),      # log_return_21d  (positive = bull-ish)
        rng.uniform(0.10, 0.35, n),     # realized_vol_21d
        rng.normal(0.02, 0.05, n),      # sma50_dist
        rng.normal(0.05, 0.10, n),      # sma200_dist
        rng.uniform(0.98, 1.02, n),     # ema_ratio
        rng.choice([0.0, 1.0], n),      # high_vol_flag
    ])
    return X


VALID_REGIME_LABELS = {"Bull", "Bear", "High-Volatility", "Sideways", "Unknown"}


class TestRegimeLabeler:
    def setup_method(self):
        self.feat_names = FeatureEngineer.FEATURE_NAMES
        self.labeler = RegimeLabeler(feature_names=self.feat_names)
        self.X = _make_synthetic_features()
        # Create 3 synthetic clusters
        self.raw_labels = np.repeat([0, 1, 2], [150, 120, 130])

    def test_fit_returns_self(self):
        result = self.labeler.fit(self.X, self.raw_labels)
        assert result is self.labeler

    def test_label_map_has_all_cluster_ids(self):
        self.labeler.fit(self.X, self.raw_labels)
        assert set(self.labeler.label_map.keys()) == {0, 1, 2}

    def test_all_labels_valid(self):
        self.labeler.fit(self.X, self.raw_labels)
        for label in self.labeler.label_map.values():
            assert label in VALID_REGIME_LABELS, f"Unexpected label: {label}"

    def test_no_duplicate_labels(self):
        self.labeler.fit(self.X, self.raw_labels)
        labels = list(self.labeler.label_map.values())
        # With 3 clusters and 5 possible labels, no duplicates should occur
        assert len(labels) == len(set(labels))

    def test_transform_output_length(self):
        self.labeler.fit(self.X, self.raw_labels)
        out = self.labeler.transform(self.raw_labels)
        assert len(out) == len(self.raw_labels)

    def test_transform_all_valid_values(self):
        self.labeler.fit(self.X, self.raw_labels)
        out = self.labeler.transform(self.raw_labels)
        assert set(out).issubset(VALID_REGIME_LABELS)

    def test_fit_transform_consistent(self):
        out1 = self.labeler.fit_transform(self.X, self.raw_labels)
        out2 = RegimeLabeler(self.feat_names).fit_transform(self.X, self.raw_labels)
        assert (out1.values == out2.values).all()

    def test_cluster_stats_has_expected_columns(self):
        self.labeler.fit(self.X, self.raw_labels)
        stats = self.labeler.cluster_stats
        assert "mean_ann_return" in stats.columns
        assert "mean_ann_vol" in stats.columns

    def test_transform_before_fit_raises(self):
        labeler = RegimeLabeler(self.feat_names)
        with pytest.raises(RuntimeError, match="not fitted"):
            labeler.transform(self.raw_labels)
