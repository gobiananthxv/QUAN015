"""Cross-asset correlation analysis."""
from __future__ import annotations

import pandas as pd

from ..data.store import load_panel


def _returns_panel(keys: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Aligned simple-return panel. Correlate returns, never price levels:
    two trending price series correlate near 1 regardless of co-movement."""
    return load_panel(keys).pct_change().dropna()


def correlation_matrix(keys: tuple[str, ...] | None = None, method: str = "pearson") -> pd.DataFrame:
    return _returns_panel(keys).corr(method=method)


def covariance_matrix(keys: tuple[str, ...] | None = None) -> pd.DataFrame:
    return _returns_panel(keys).cov()


def rolling_correlation(a: str, b: str, window: int = 90) -> pd.Series:
    """Rolling pairwise correlation of returns between two assets."""
    rets = _returns_panel((a.upper(), b.upper()))
    return rets[a.upper()].rolling(window, min_periods=window).corr(rets[b.upper()]).dropna()


def rolling_correlation_all(window: int = 90, keys: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Every unique pair's rolling correlation, as columns named ``A~B``."""
    rets = _returns_panel(keys)
    cols = list(rets.columns)
    out = {}
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            out[f"{a}~{b}"] = rets[a].rolling(window, min_periods=window).corr(rets[b])
    return pd.DataFrame(out).dropna(how="all")
