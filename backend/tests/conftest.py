"""Shared test fixtures and path setup."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def linear_up() -> pd.Series:
    """Strictly increasing prices, 1.0 per bar."""
    return pd.Series(np.arange(100.0, 160.0), index=pd.date_range("2024-01-01", periods=60))


@pytest.fixture
def linear_down() -> pd.Series:
    return pd.Series(np.arange(160.0, 100.0, -1.0), index=pd.date_range("2024-01-01", periods=60))


@pytest.fixture
def flat() -> pd.Series:
    return pd.Series([100.0] * 60, index=pd.date_range("2024-01-01", periods=60))


@pytest.fixture
def noisy() -> pd.Series:
    """Deterministic pseudo-random walk — same every run, so failures reproduce."""
    rng = np.random.default_rng(42)
    steps = rng.normal(0.0005, 0.02, 500)
    return pd.Series(100 * np.exp(np.cumsum(steps)), index=pd.date_range("2022-01-01", periods=500))


@pytest.fixture
def ohlcv(noisy: pd.Series) -> pd.DataFrame:
    """A well-formed OHLCV frame derived from the random walk."""
    close = noisy
    rng = np.random.default_rng(7)
    spread = np.abs(rng.normal(0, 0.01, len(close))) * close
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) + spread
    low = pd.concat([open_, close], axis=1).min(axis=1) - spread
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": pd.Series(1e6, index=close.index),
        }
    )
