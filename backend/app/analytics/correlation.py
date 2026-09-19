"""Cross-asset correlation analysis.

**Sample-selection note.** Two different calendars are used here, deliberately:

* :func:`correlation_matrix` and :func:`covariance_matrix` use the intersection
  of *all* requested assets' calendars. A matrix must be built from one common
  sample, otherwise its entries describe different periods and it is not
  internally consistent.
* :func:`rolling_correlation` uses the intersection of just that *pair's*
  calendars, which yields more observations and therefore a better estimate.

Consequence: the pairwise series may rest on slightly more data than the
matrix entry for the same pair (2,514 vs 2,511 rows for GOLD/NVDA, because
adding BTC to the panel costs three days). Both functions report on the sample
they actually used via :func:`sample_size`, so the difference is visible rather
than silent.

In every case correlation is computed on *returns*, never on price levels: two
independently trending price series correlate near 1 in levels while their
returns may be unrelated.
"""
from __future__ import annotations

import pandas as pd

from ..data.store import load_panel


def _returns_panel(
    keys: tuple[str, ...] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Aligned simple-return panel for the requested assets.

    A window is applied to *prices* before returns are taken, so the first bar
    of the window has no return. Slicing the return series instead would carry
    in one return computed against a close from outside the window.
    """
    panel = load_panel(keys)
    if start or end:
        panel = panel.loc[start:end]
        if panel.empty:
            raise ValueError(f"no bars between {start or 'start'} and {end or 'end'}")
    return panel.pct_change().dropna()


def sample_size(
    keys: tuple[str, ...] | None = None, start: str | None = None, end: str | None = None
) -> int:
    """Number of return observations backing a correlation over ``keys``."""
    return int(len(_returns_panel(keys, start, end)))


def correlation_matrix(
    keys: tuple[str, ...] | None = None,
    method: str = "pearson",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Static correlation matrix over the common calendar of all ``keys``."""
    return _returns_panel(keys, start, end).corr(method=method)


def covariance_matrix(
    keys: tuple[str, ...] | None = None, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    """Covariance matrix over the common calendar of all ``keys``."""
    return _returns_panel(keys, start, end).cov()


def rolling_correlation(
    a: str, b: str, window: int = 90, start: str | None = None, end: str | None = None
) -> pd.Series:
    """Rolling pairwise return correlation, on that pair's own common calendar."""
    a, b = a.upper(), b.upper()
    rets = _returns_panel((a, b), start, end)
    if a == b:
        # Correlating a series with itself is 1 by definition; pandas would
        # return a single column here and the .corr call would misalign.
        return pd.Series(1.0, index=rets.index[window - 1:], name=f"{a}~{b}")
    return rets[a].rolling(window, min_periods=window).corr(rets[b]).dropna()


def rolling_correlation_all(
    window: int = 90,
    keys: tuple[str, ...] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Every unique pair's rolling correlation, as columns named ``A~B``.

    Unlike :func:`rolling_correlation` this uses the common calendar of all
    ``keys``, so the columns are directly comparable against each other.
    """
    rets = _returns_panel(keys, start, end)
    cols = list(rets.columns)
    out = {}
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            out[f"{a}~{b}"] = rets[a].rolling(window, min_periods=window).corr(rets[b])
    return pd.DataFrame(out).dropna(how="all")
