"""Technical indicators, implemented directly in pandas/NumPy.

Every function takes and returns aligned pandas objects and is causal: the value
at bar *t* uses only data up to and including bar *t*. That property is what the
backtester relies on when it lags signals.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).mean()


def ema(s: pd.Series, span: int) -> pd.Series:
    # adjust=False gives the recursive form used by charting platforms, so values
    # match what a user sees in TradingView rather than the expanding-mean form.
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(s: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's RSI (smoothed with alpha = 1/window).

    The zero-average-loss case needs care: if there were no losses *and* no
    gains the price was flat and RSI is neutral (50), not overbought (100).
    Gold has ~80 flat bars in this dataset, so this branch is reachable.
    """
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    no_loss = avg_loss == 0
    out = out.mask(no_loss & (avg_gain > 0), 100.0)
    out = out.mask(no_loss & (avg_gain == 0), 50.0)
    return out.where(avg_loss.notna() & avg_gain.notna(), np.nan)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(s: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(s, window)
    sd = s.rolling(window, min_periods=window).std(ddof=0)
    return pd.DataFrame(
        {
            "bb_mid": mid,
            "bb_upper": mid + num_std * sd,
            "bb_lower": mid - num_std * sd,
            # z-score of price within the band: the mean-reversion signal input
            "bb_z": (s - mid) / sd.replace(0.0, np.nan),
        }
    )


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing). Needs high/low/close."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def roc(s: pd.Series, window: int = 20) -> pd.Series:
    """Rate of change over ``window`` bars, as a fraction."""
    return s.pct_change(window)


def realised_vol(s: pd.Series, window: int = 20, ann_factor: int = 252) -> pd.Series:
    """Annualised standard deviation of daily returns over a trailing window.

    ``ann_factor`` is per-asset for the same reason it is everywhere else in
    this codebase: crypto compounds 365 times a year and equities 252, so a
    shared constant would understate BTC volatility by about 20%.

    Uses the sample standard deviation (``ddof=1``, pandas' default) and
    requires a full window, so the series is NaN until enough history exists
    rather than quietly reporting a one-observation volatility of zero.
    """
    return s.pct_change().rolling(window, min_periods=window).std() * np.sqrt(ann_factor)


def compute_indicators(
    df: pd.DataFrame,
    sma_fast: int = 20,
    sma_slow: int = 50,
    ema_fast: int = 12,
    ema_slow: int = 26,
    rsi_window: int = 14,
    bb_window: int = 20,
    roc_window: int = 20,
) -> pd.DataFrame:
    """Full indicator set for one asset, returned alongside the OHLCV columns."""
    close = df["close"]
    out = df.copy()
    out[f"sma_{sma_fast}"] = sma(close, sma_fast)
    out[f"sma_{sma_slow}"] = sma(close, sma_slow)
    out["sma_200"] = sma(close, 200)
    out[f"ema_{ema_fast}"] = ema(close, ema_fast)
    out[f"ema_{ema_slow}"] = ema(close, ema_slow)
    out["rsi"] = rsi(close, rsi_window)
    out = out.join(macd(close))
    out = out.join(bollinger(close, bb_window))
    out["atr"] = atr(df)
    out["roc"] = roc(close, roc_window)
    return out
