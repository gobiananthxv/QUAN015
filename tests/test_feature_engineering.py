"""
tests/test_feature_engineering.py — Unit tests for FeatureEngineer.
"""

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from features.feature_engineering import FeatureEngineer


def _make_price_df(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Create a synthetic price DataFrame with a DatetimeIndex."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-02", periods=n)
    returns = rng.normal(0.0005, 0.012, size=n)
    close = 100.0 * np.cumprod(1 + returns)
    volume = rng.integers(1_000_000, 10_000_000, size=n)
    return pd.DataFrame(
        {"open": close * 0.999, "high": close * 1.005, "low": close * 0.995,
         "close": close, "volume": volume},
        index=dates,
    )


class TestFeatureEngineer:
    def setup_method(self):
        self.fe = FeatureEngineer()
        self.df = _make_price_df(n=500)

    def test_fit_transform_shape(self):
        X, idx = self.fe.fit_transform(self.df)
        assert X.ndim == 2
        assert X.shape[1] == len(FeatureEngineer.FEATURE_NAMES)

    def test_no_nans_in_output(self):
        X, idx = self.fe.fit_transform(self.df)
        assert not np.isnan(X).any(), "Scaled feature matrix must have no NaN"

    def test_scaled_mean_near_zero(self):
        X, idx = self.fe.fit_transform(self.df)
        # StandardScaler guarantees mean≈0, std≈1
        np.testing.assert_allclose(X.mean(axis=0), 0, atol=1e-10)

    def test_index_length_matches_rows(self):
        X, idx = self.fe.fit_transform(self.df)
        assert len(idx) == X.shape[0]

    def test_transform_reuses_scaler(self):
        X_train, _ = self.fe.fit_transform(self.df.iloc[:300])
        X_test, idx = self.fe.transform(self.df.iloc[300:])
        assert X_test.shape[1] == X_train.shape[1]

    def test_transform_before_fit_raises(self):
        fe = FeatureEngineer()
        with pytest.raises(RuntimeError, match="Scaler not fitted"):
            fe.transform(self.df)

    def test_insufficient_data_raises(self):
        tiny_df = _make_price_df(n=5)
        with pytest.raises(ValueError):
            FeatureEngineer().fit_transform(tiny_df)

    def test_feature_names_match_columns(self):
        raw = self.fe.get_raw_features(self.df)
        assert list(raw.columns) == FeatureEngineer.FEATURE_NAMES

    def test_high_vol_flag_binary(self):
        raw = self.fe.get_raw_features(self.df)
        assert raw["high_vol_flag"].isin([0.0, 1.0]).all()
