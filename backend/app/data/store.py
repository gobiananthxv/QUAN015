"""The committed market-data snapshot, and the multi-asset aligned panel.

**This is a snapshot, not a cache.** It has no TTL, never expires and is never
invalidated automatically. Reading an asset does *not* contact Yahoo — it reads
a CSV committed to the repository. The network is touched in exactly two cases:
the file is missing, or a caller passes ``refresh=True``.

That is deliberate, for three reasons:

* **Reproducibility.** A backtest must give the same answer today and tomorrow.
  If the underlying data moved between runs, every reported figure would drift
  and the tests asserting exact values would fail daily.
* **Availability.** The platform must work with no internet connection.
* **Speed.** ~14 ms from disk against ~500 ms over the network, and the
  robustness sweep runs dozens of backtests per click.

Refresh explicitly via ``scripts/bootstrap_data.py --refresh`` or the
``POST /api/data/refresh`` endpoint.

CSV rather than Parquet is deliberate — a few thousand rows per asset, read in
milliseconds, keeping the dependency list to pandas + requests while staying
diffable in git.
"""
from __future__ import annotations

import time
from functools import lru_cache

import pandas as pd

from ..config import ASSETS, SNAPSHOT_DIR, get_asset
from .sources import fetch_ohlcv
from .validate import validate_ohlcv

_REPORTS: dict[str, dict] = {}


def _path(key: str):
    return SNAPSHOT_DIR / f"{key.upper()}.csv"


def load_asset(key: str, refresh: bool = False) -> pd.DataFrame:
    """Return validated OHLCV for one asset.

    Reads the committed snapshot. Only downloads when the file is absent or
    ``refresh=True`` — see the module docstring for why.
    """
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
    """Validation report for an asset, recomputed from the snapshot if not in memory."""
    key = get_asset(key).key
    if key not in _REPORTS:
        _, report = validate_ohlcv(load_asset(key), key)
        _REPORTS[key] = report
    return _REPORTS[key]


# The provider publishes one bar per day, so re-downloading more often than
# that cannot produce a different result — it just spends a network round trip
# to rewrite identical rows. (Yahoo's intraday quotes are delayed ~15-20 minutes,
# which is irrelevant here: we never read them.)
MIN_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60


def age_seconds(key: str) -> float | None:
    """How long ago this asset's snapshot file was written, or None if absent."""
    path = _path(get_asset(key).key)
    return time.time() - path.stat().st_mtime if path.exists() else None


def refresh(keys: list[str] | None = None, force: bool = False) -> dict:
    """Re-download the requested assets and overwrite the snapshot.

    This is the *only* code path that reaches the network during normal
    operation, and it is always caller-initiated — nothing refreshes on a timer
    or on a page load, because a backtest whose data moves underneath it is not
    reproducible.

    An asset fetched within the last day is **skipped**, because the data is
    daily: a second fetch would rewrite byte-identical rows. ``force=True``
    overrides that, which is what you want after a provider outage or a bad
    partial write. Skips are reported rather than silently folded into
    successes, so pressing Refresh twice says "already current" instead of
    pretending to have done work.

    Failures are collected per asset rather than aborting: one unreachable
    ticker should not leave the other two half-updated with no explanation.
    """
    targets = [get_asset(k).key for k in (keys or ASSETS)]
    updated: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for key in targets:
        age = age_seconds(key)
        if not force and age is not None and age < MIN_REFRESH_INTERVAL_SECONDS:
            skipped.append(
                {
                    "asset": key,
                    "age_hours": round(age / 3600, 1),
                    "reason": "already fetched within the last day; daily bars cannot have changed",
                }
            )
            continue
        try:
            load_asset(key, refresh=True)
            report = quality_report(key)
            updated.append({"asset": key, "rows": report["rows_out"],
                            "start": report["start"], "end": report["end"]})
        except Exception as exc:  # noqa: BLE001 - report per asset, keep going
            failed.append({"asset": key, "error": f"{type(exc).__name__}: {exc}"})

    load_panel.cache_clear()
    return {
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "snapshot": snapshot_status(),
    }


def snapshot_status() -> list[dict]:
    """What the snapshot currently holds, so the UI can show its age."""
    rows = []
    for key, asset in ASSETS.items():
        path = _path(key)
        row = {"asset": key, "name": asset.name, "ticker": asset.ticker, "available": path.exists()}
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
