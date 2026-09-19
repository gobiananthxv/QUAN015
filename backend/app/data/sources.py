"""Market data ingestion from the Yahoo Finance chart API.

We call the public chart endpoint directly with ``requests`` rather than going
through ``yfinance``. Reasons, in order of importance for this project:

  * One dependency we already have, instead of a large transitive tree.
  * The response shape is stable and documented by use; yfinance's wrapper API
    changes between minor versions and silently returns empty frames on failure.
  * We control retries, timeouts and the error surface, so a bad fetch raises
    loudly instead of writing an empty file into the cache.

All three asset classes (commodity future, crypto, equity) come from this one
endpoint, so normalisation is single-path.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from ..config import HISTORY_PERIOD, get_asset

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# Yahoo rejects requests without a browser-ish UA.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]


def _request(ticker: str, period: str, timeout: int, retries: int = 3) -> dict:
    """GET the chart payload, retrying transient failures with a backoff."""
    params = {
        "range": period,
        "interval": "1d",
        # Ask for the split/dividend adjustment series alongside the raw quotes.
        "events": "div,split",
        "includeAdjustedClose": "true",
    }
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                CHART_URL.format(ticker=ticker), params=params, headers=HEADERS, timeout=timeout
            )
            resp.raise_for_status()
            payload = resp.json()
            chart = payload.get("chart") or {}
            if chart.get("error"):
                raise RuntimeError(f"provider error for {ticker}: {chart['error']}")
            results = chart.get("result")
            if not results:
                raise RuntimeError(f"provider returned no result block for {ticker}")
            return results[0]
        except Exception as exc:  # noqa: BLE001 - retry any transient failure
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {ticker} after {retries} attempts: {last_exc}")


def fetch_ohlcv(key: str, period: str = HISTORY_PERIOD, timeout: int = 30) -> pd.DataFrame:
    """Download daily OHLCV for one asset and normalise it.

    Returns a frame indexed by tz-naive date with lowercase
    ``open/high/low/close/volume`` columns, adjusted for splits and dividends.
    Raises on an empty or malformed response, so a silent failure can never be
    written into the cache.
    """
    asset = get_asset(key)
    result = _request(asset.ticker, period, timeout)

    timestamps = result.get("timestamp")
    if not timestamps:
        raise RuntimeError(f"{key}: no timestamps returned for {asset.ticker}")

    quote = result["indicators"]["quote"][0]
    df = pd.DataFrame({f: quote.get(f) for f in OHLCV_FIELDS})

    # Prefer the adjusted close: split/dividend adjusted prices make the return
    # series comparable across time and across assets. Scale OHLC by the same
    # factor so intraday relationships (and open-based fills) stay consistent.
    adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
    if adj is not None:
        adj_close = pd.Series(adj, dtype="float64")
        factor = (adj_close / df["close"]).where(df["close"] > 0)
        factor = factor.ffill().bfill().fillna(1.0)
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] * factor

    df.index = pd.to_datetime(pd.Series(timestamps), unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    df.index.name = "date"
    df = df.astype("float64")

    if df["close"].notna().sum() == 0:
        raise RuntimeError(f"{key}: all closes are null for {asset.ticker}")
    return df
