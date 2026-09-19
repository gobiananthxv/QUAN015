"""Market regime classification and per-regime performance attribution.

Two independent, deliberately simple and transparent axes:
  * trend  : price above / below its 200-day SMA  -> bull / bear
  * vol    : rolling 30-day annualised volatility vs its own historical
             terciles -> low / normal / high

Both are computed causally (rolling/expanding only), so a regime label at bar
*t* never uses information from after *t*. That matters because regime labels
are joined onto strategy returns for attribution.
"""
from __future__ import annotations

import pandas as pd

from ..config import get_asset
from ..data.store import load_asset
from .indicators import sma
from .metrics import rolling_volatility, summarise


def classify(key: str, vol_window: int = 30, trend_window: int = 200) -> pd.DataFrame:
    """Return a frame of ``trend_regime``, ``vol_regime`` and ``regime`` labels."""
    asset = get_asset(key)
    df = load_asset(asset.key)
    close = df["close"]

    trend = pd.Series("bear", index=close.index, dtype="object")
    trend[close > sma(close, trend_window)] = "bull"
    trend[sma(close, trend_window).isna()] = None

    rets = close.pct_change()
    rvol = rolling_volatility(rets, vol_window, asset.ann_factor)

    # Expanding quantiles: the threshold at bar t uses only history up to t, so a
    # 2015 bar is never labelled "high vol" because of what happened in 2020.
    q33 = rvol.expanding(min_periods=vol_window * 3).quantile(0.33)
    q67 = rvol.expanding(min_periods=vol_window * 3).quantile(0.67)
    vol = pd.Series(None, index=close.index, dtype="object")
    vol[rvol <= q33] = "low_vol"
    vol[(rvol > q33) & (rvol <= q67)] = "normal_vol"
    vol[rvol > q67] = "high_vol"

    out = pd.DataFrame({"close": close, "rolling_vol": rvol, "trend_regime": trend, "vol_regime": vol})
    out["regime"] = out["trend_regime"].fillna("") + "/" + out["vol_regime"].fillna("")
    return out


def regime_breakdown(key: str, returns: pd.Series | None = None) -> list[dict]:
    """Performance of ``returns`` sliced by each regime label.

    With ``returns=None`` this describes the asset itself (buy-and-hold);
    passing a strategy's return series answers "when does this strategy work?".
    """
    asset = get_asset(key)
    reg = classify(asset.key)
    if returns is None:
        returns = reg["close"].pct_change()

    joined = pd.DataFrame({"ret": returns}).join(reg[["trend_regime", "vol_regime"]], how="inner")

    rows: list[dict] = []
    for axis in ("trend_regime", "vol_regime"):
        for label, grp in joined.dropna(subset=[axis]).groupby(axis):
            if len(grp) < 2:
                continue
            stats = summarise(grp["ret"], asset.ann_factor)
            rows.append(
                {
                    "axis": "trend" if axis == "trend_regime" else "volatility",
                    "regime": label,
                    "days": int(len(grp)),
                    "share_of_period": len(grp) / len(joined),
                    **{k: stats[k] for k in ("total_return", "cagr", "volatility", "sharpe", "max_drawdown")},
                }
            )
    return rows
