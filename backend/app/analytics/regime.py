"""Market regime classification and per-regime performance attribution.

Two independent, deliberately simple and transparent axes:
  * trend : price above / below its 200-day SMA -> bull / bear
  * vol   : rolling 30-day annualised volatility against its own historical
            terciles -> low / normal / high

Both are computed causally. The volatility thresholds in particular use
*expanding* quantiles, not full-sample ones: the cutoff applied at bar *t* is
derived only from bars up to *t*, so a 2016 bar can never be labelled
"high volatility" because of what happened in 2020. Full-sample quantiles would
leak the future into the labels, and those labels are joined onto strategy
returns for attribution — the leak would flatter every regime conclusion.
"""
from __future__ import annotations

import pandas as pd

from ..config import get_asset
from ..data.store import load_asset
from .indicators import sma
from .metrics import TRADING_DAYS, rolling_volatility, summarise

TREND_LABELS = ("bull", "bear")
VOL_LABELS = ("low_vol", "normal_vol", "high_vol")


def classify_frame(
    close: pd.Series,
    ann_factor: int = TRADING_DAYS,
    vol_window: int = 30,
    trend_window: int = 200,
) -> pd.DataFrame:
    """Label a close-price series by trend and volatility regime.

    Pure function of the series passed in — no I/O — so it can be tested for
    causality by comparing a prefix against the full series.
    """
    trend_ma = sma(close, trend_window)
    trend = pd.Series(pd.NA, index=close.index, dtype="object")
    trend[close > trend_ma] = "bull"
    trend[close <= trend_ma] = "bear"

    rets = close.pct_change()
    rvol = rolling_volatility(rets, vol_window, ann_factor)

    min_hist = vol_window * 3
    q33 = rvol.expanding(min_periods=min_hist).quantile(0.33)
    q67 = rvol.expanding(min_periods=min_hist).quantile(0.67)

    vol = pd.Series(pd.NA, index=close.index, dtype="object")
    vol[rvol <= q33] = "low_vol"
    vol[(rvol > q33) & (rvol <= q67)] = "normal_vol"
    vol[rvol > q67] = "high_vol"

    out = pd.DataFrame(
        {"close": close, "rolling_vol": rvol, "trend_regime": trend, "vol_regime": vol}
    )
    out["regime"] = (
        out["trend_regime"].fillna("unknown").astype(str)
        + "/"
        + out["vol_regime"].fillna("unknown").astype(str)
    )
    return out


def classify(key: str, vol_window: int = 30, trend_window: int = 200) -> pd.DataFrame:
    """Regime labels for a cached asset."""
    asset = get_asset(key)
    return classify_frame(
        load_asset(asset.key)["close"], asset.ann_factor, vol_window, trend_window
    )


def regime_breakdown(key: str, returns: pd.Series | None = None) -> list[dict]:
    """Performance of ``returns`` sliced by each regime label.

    With ``returns=None`` this describes the asset itself (buy-and-hold);
    passing a strategy's return series answers "when does this strategy work?".
    """
    asset = get_asset(key)
    reg = classify(asset.key)
    if returns is None:
        returns = reg["close"].pct_change()

    joined = pd.DataFrame({"ret": returns}).join(
        reg[["trend_regime", "vol_regime"]], how="inner"
    )
    joined = joined.dropna(subset=["ret"])

    rows: list[dict] = []
    for axis, axis_name in (("trend_regime", "trend"), ("vol_regime", "volatility")):
        labelled = joined[joined[axis].notna()]
        if labelled.empty:
            continue
        for label, grp in labelled.groupby(axis):
            if len(grp) < 2:
                continue
            stats = summarise(grp["ret"], asset.ann_factor)
            rows.append(
                {
                    "axis": axis_name,
                    "regime": str(label),
                    "days": int(len(grp)),
                    # Share is within this axis, so the axis sums to 1.0.
                    "share_of_period": len(grp) / len(labelled),
                    **{
                        k: stats[k]
                        for k in ("total_return", "cagr", "volatility", "sharpe", "max_drawdown")
                    },
                }
            )
    return rows
