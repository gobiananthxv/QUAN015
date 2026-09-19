"""Return, risk and risk-adjusted performance metrics.

All functions take a *returns* series (simple, per-bar) unless noted. The
annualisation factor is always passed in explicitly rather than assumed to be
252, because this platform mixes crypto (365) with equities and futures (252).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import RISK_FREE_RATE

TRADING_DAYS = 252


def daily_returns(prices: pd.Series) -> pd.Series:
    return prices.pct_change().dropna()


def cumulative_returns(returns: pd.Series) -> pd.Series:
    """Growth of 1 unit, minus 1 -> cumulative return path."""
    return (1 + returns).cumprod() - 1


def total_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float((1 + returns).prod() - 1)


def cagr(returns: pd.Series, ann_factor: int = TRADING_DAYS) -> float:
    """Compound annual growth rate implied by the return series."""
    if len(returns) < 2:
        return 0.0
    years = len(returns) / ann_factor
    growth = float((1 + returns).prod())
    if years <= 0 or growth <= 0:
        return 0.0
    return growth ** (1 / years) - 1


def volatility(returns: pd.Series, ann_factor: int = TRADING_DAYS, annualise: bool = True) -> float:
    if len(returns) < 2:
        return 0.0
    sd = float(returns.std(ddof=1))
    return sd * np.sqrt(ann_factor) if annualise else sd


def rolling_volatility(returns: pd.Series, window: int = 30, ann_factor: int = TRADING_DAYS) -> pd.Series:
    return returns.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(ann_factor)


def sharpe_ratio(returns: pd.Series, ann_factor: int = TRADING_DAYS, rf: float = RISK_FREE_RATE) -> float:
    """Annualised Sharpe, with the risk-free rate de-annualised to per-bar."""
    if len(returns) < 2:
        return 0.0
    rf_per_bar = (1 + rf) ** (1 / ann_factor) - 1
    excess = returns - rf_per_bar
    sd = float(excess.std(ddof=1))
    if sd == 0:
        return 0.0
    return float(excess.mean() / sd * np.sqrt(ann_factor))


def sortino_ratio(returns: pd.Series, ann_factor: int = TRADING_DAYS, rf: float = RISK_FREE_RATE) -> float:
    """Like Sharpe but penalises only downside deviation."""
    if len(returns) < 2:
        return 0.0
    rf_per_bar = (1 + rf) ** (1 / ann_factor) - 1
    excess = returns - rf_per_bar
    downside = excess[excess < 0]
    if downside.empty:
        # No bar ever returned below the risk-free rate. Sortino is undefined
        # (division by zero downside deviation); reporting 0.0 would read as
        # "no risk-adjusted return", the opposite of the truth.
        return float("inf") if excess.mean() > 0 else 0.0
    dd = float(np.sqrt((downside ** 2).mean()))
    if dd == 0:
        return float("inf") if excess.mean() > 0 else 0.0
    return float(excess.mean() / dd * np.sqrt(ann_factor))


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Underwater curve: fractional distance below the running peak."""
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    return equity / peak - 1


def max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float(drawdown_series(returns).min())


def max_drawdown_duration(returns: pd.Series) -> int:
    """Longest run of consecutive bars spent below a prior peak."""
    if returns.empty:
        return 0
    dd = drawdown_series(returns)
    underwater = dd < 0
    longest = run = 0
    for flag in underwater:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return int(longest)


def calmar_ratio(returns: pd.Series, ann_factor: int = TRADING_DAYS) -> float:
    mdd = abs(max_drawdown(returns))
    if mdd == 0:
        return 0.0
    return float(cagr(returns, ann_factor) / mdd)


def rolling_returns(prices: pd.Series, window: int = 252) -> pd.Series:
    """Trailing ``window``-bar return at each point in time."""
    return prices.pct_change(window)


def summarise(returns: pd.Series, ann_factor: int = TRADING_DAYS) -> dict[str, float]:
    """The standard metric block used for assets, strategies and the benchmark."""
    return {
        "total_return": total_return(returns),
        "cagr": cagr(returns, ann_factor),
        "volatility": volatility(returns, ann_factor),
        "sharpe": sharpe_ratio(returns, ann_factor),
        "sortino": sortino_ratio(returns, ann_factor),
        "calmar": calmar_ratio(returns, ann_factor),
        "max_drawdown": max_drawdown(returns),
        "max_drawdown_duration": max_drawdown_duration(returns),
        "best_day": float(returns.max()) if len(returns) else 0.0,
        "worst_day": float(returns.min()) if len(returns) else 0.0,
        "positive_days": float((returns > 0).mean()) if len(returns) else 0.0,
    }
