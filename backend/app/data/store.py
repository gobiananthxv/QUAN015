"""CSV-backed cache and the multi-asset aligned panel.

The cache is committed to the repo: the platform must not depend on Yahoo being
reachable at demo time. ``refresh=True`` re-fetches and overwrites.

CSV rather than Parquet is deliberate — the whole dataset is ~7k rows per asset,
the read cost is milliseconds, and it keeps the dependency list to pandas +
requests while staying diffable in git.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from ..config import ASSETS, CACHE_DIR, get_asset
from .sources import fetch_ohlcv
from .validate import validate_ohlcv

_REPORTS: dict[str, dict] = {}


def _path(key: str):
    return CACHE_DIR / f"{key.upper()}.csv"


def load_asset(key: str, refresh: bool = False) -> pd.DataFrame:
    """Return validated OHLCV for one asset, fetching only on a cold cache."""
    key = get_asset(key).key
    path = _path(key)

    if path.exists() and not refresh:
        df = pd.read_csv(path, index_col="date", parse_dates=["date"])
        df.index.name = "date"
        return df

    df, report = validate_ohlcv(fetch_ohlcv(key), key)
    df.to_csv(path)
    _REPORTS[key] = report
    load_panel.cache_clear()
    return df


def quality_report(key: str) -> dict:
    """Validation report for an asset, recomputed from cache if not in memory."""
    key = get_asset(key).key
    if key not in _REPORTS:
        _, report = validate_ohlcv(load_asset(key), key)
        _REPORTS[key] = report
    return _REPORTS[key]


def refresh_all() -> dict[str, dict]:
    """Re-fetch every asset. Used by the bootstrap script and /data/refresh."""
    out: dict[str, dict] = {}
    for key in ASSETS:
        load_asset(key, refresh=True)
        out[key] = quality_report(key)
    return out


def cache_status() -> list[dict]:
    """What is cached right now — surfaced by the API so the UI can show it."""
    rows = []
    for key, asset in ASSETS.items():
        path = _path(key)
        row = {"asset": key, "name": asset.name, "ticker": asset.ticker, "cached": path.exists()}
        if path.exists():
            df = load_asset(key)
            row.update(
                {
                    "rows": int(len(df)),
                    "start": str(df.index.min().date()),
                    "end": str(df.index.max().date()),
                }
            )
        rows.append(row)
    return rows


@lru_cache(maxsize=8)
def load_panel(keys: tuple[str, ...] | None = None, field: str = "close") -> pd.DataFrame:
    """Wide frame of one price field across assets, on a COMMON trading calendar.

    This alignment is what makes the correlation analysis meaningful. BTC trades
    365 days a year; NVDA and gold futures do not. An outer join with a forward
    fill would inject hundreds of weekend rows where the equity is flat by
    construction, mechanically dragging correlation toward zero. We intersect the
    calendars instead, so every row is a day on which *all* selected assets
    actually traded.
    """
    keys = tuple(keys or ASSETS.keys())
    series = {k: load_asset(k)[field].rename(k) for k in keys}
    panel = pd.concat(series.values(), axis=1, join="inner").dropna()
    panel.index.name = "date"
    return panel
