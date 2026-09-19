"""
data/data_loader.py — Downloads and caches OHLCV data via yfinance.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from config import DATA_CACHE_DIR

logger = logging.getLogger(__name__)


class DataLoader:
    """Fetches and caches market OHLCV data from Yahoo Finance.

    Parameters
    ----------
    cache_dir : str
        Directory to store cached CSV files. Defaults to ``DATA_CACHE_DIR``.
    """

    def __init__(self, cache_dir: str = DATA_CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(
        self,
        ticker: str,
        start: str,
        end: Optional[str] = None,
        force_download: bool = False,
    ) -> pd.DataFrame:
        """Return a clean DataFrame of daily OHLCV data for *ticker*.

        The ``Adj Close`` column is renamed to ``close`` and used as the
        reference price. All columns are lower-cased.

        Parameters
        ----------
        ticker :
            Yahoo Finance ticker symbol, e.g. ``"SPY"``.
        start :
            Start date string in ``YYYY-MM-DD`` format.
        end :
            End date string (inclusive). ``None`` → today.
        force_download :
            If ``True``, skip cache and re-download.

        Returns
        -------
        pd.DataFrame
            DataFrame with a ``DatetimeIndex`` and columns:
            ``open``, ``close``, ``high``, ``low``, ``volume``.
        """
        cache_path = self._cache_path(ticker, start, end)

        if not force_download and cache_path.exists():
            logger.info("Loading %s from cache: %s", ticker, cache_path)
            # The cached CSV was already cleaned — parse the index as dates directly.
            df = pd.read_csv(cache_path, index_col=0)
            df.index = pd.to_datetime(df.index, format="mixed", dayfirst=False)
            df.index.name = "date"
            # Drop any rows where the index failed to parse (e.g. old corrupted cache)
            df = df[df.index.notna()]
            return df
        else:
            logger.info("Downloading %s from Yahoo Finance …", ticker)
            raw = self._download(ticker, start, end)
            # Clean BEFORE saving so the cached CSV is always in our simple format
            # (no yfinance MultiIndex "Ticker"/"Price" header rows).
            clean = self._clean(raw)
            clean.to_csv(cache_path)
            logger.info("Saved to cache: %s", cache_path)
            return clean

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _download(ticker: str, start: str, end: Optional[str]) -> pd.DataFrame:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError(f"No data returned for ticker '{ticker}'. Check the symbol.")
        return raw

    @staticmethod
    def _clean(df: pd.DataFrame) -> pd.DataFrame:
        """Normalise column names and drop rows with NaN close prices."""
        # Flatten MultiIndex columns that yfinance may produce
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # Prefer 'adj_close' if it survived; otherwise fall back to 'close'
        if "adj_close" in df.columns:
            df = df.rename(columns={"adj_close": "close"})

        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[keep].copy()
        df = df.dropna(subset=["close"])
        df.index = pd.to_datetime(df.index, format="mixed", dayfirst=False)
        df.index.name = "date"
        return df

    def _cache_path(self, ticker: str, start: str, end: Optional[str]) -> Path:
        end_str = end or "today"
        filename = f"{ticker}_{start}_{end_str}.csv".replace(":", "-")
        return self.cache_dir / filename
