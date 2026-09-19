"""OHLCV validation and cleaning.

Runs before anything is written to the cache. Returns a report so the API can
surface data quality rather than hiding it.
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def validate_ohlcv(df: pd.DataFrame, key: str) -> tuple[pd.DataFrame, dict]:
    """Clean ``df`` in place-ish and return ``(clean_df, report)``.

    Checks, in order:
      * required columns present
      * index is a sorted, unique DatetimeIndex
      * rows with a null close are dropped (a bar without a close is unusable)
      * OHLC invariants: low <= min(open, close) and high >= max(open, close)
      * non-positive prices dropped
      * negative volume zeroed
      * calendar gaps counted (weekends excluded for non-crypto is not attempted;
        this is a signal, not an error)
    """
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{key}: missing columns {missing}")

    report: dict[str, object] = {"asset": key, "rows_in": int(len(df))}

    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"{key}: index must be a DatetimeIndex")
    df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
    df = df[~df.index.duplicated(keep="last")].sort_index()

    n = len(df)
    df = df.dropna(subset=["close"])
    report["dropped_null_close"] = n - len(df)

    n = len(df)
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    report["dropped_non_positive"] = n - len(df)

    # OHLC invariant violations are repaired, not dropped: providers occasionally
    # emit a high fractionally below the close. Dropping the bar loses more
    # information than widening the range.
    lo = df[["open", "close", "low"]].min(axis=1)
    hi = df[["open", "close", "high"]].max(axis=1)
    report["ohlc_repaired"] = int(((df["low"] > lo) | (df["high"] < hi)).sum())
    df["low"], df["high"] = lo, hi

    neg_vol = int((df["volume"] < 0).sum())
    df.loc[df["volume"] < 0, "volume"] = 0
    df["volume"] = df["volume"].fillna(0)
    report["negative_volume_zeroed"] = neg_vol

    if len(df) > 1:
        gaps = df.index.to_series().diff().dt.days.dropna()
        report["max_gap_days"] = int(gaps.max())
        report["gaps_over_7d"] = int((gaps > 7).sum())
    else:
        report["max_gap_days"] = 0
        report["gaps_over_7d"] = 0

    report["rows_out"] = int(len(df))
    report["start"] = str(df.index.min().date()) if len(df) else None
    report["end"] = str(df.index.max().date()) if len(df) else None
    return df, report
