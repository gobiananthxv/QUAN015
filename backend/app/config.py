"""Central configuration: asset registry and engine defaults."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# A committed snapshot of market data, not a cache: it has no TTL and never
# expires on its own. Backtests must be reproducible, so the data a result was
# computed from is pinned in the repository and only changes when someone
# explicitly refreshes it.
SNAPSHOT_DIR = BASE_DIR / "data_snapshot"
SNAPSHOT_DIR.mkdir(exist_ok=True)

# History window pulled from the provider on a cold cache.
HISTORY_PERIOD = "10y"


@dataclass(frozen=True)
class Asset:
    """One tradable instrument.

    ``ann_factor`` is the number of trading periods per year and is deliberately
    per-asset: crypto trades every calendar day, equities and futures do not.
    Annualising BTC volatility with 252 understates it by ~20%.
    """

    key: str
    name: str
    ticker: str
    asset_class: str
    ann_factor: int


ASSETS: dict[str, Asset] = {
    "GOLD": Asset("GOLD", "Gold Futures", "GC=F", "commodity", 252),
    "BTC": Asset("BTC", "Bitcoin", "BTC-USD", "crypto", 365),
    "NVDA": Asset("NVDA", "NVIDIA", "NVDA", "equity", 252),
}

DEFAULT_ASSET_KEYS = list(ASSETS)

# Backtest defaults (overridable per request).
DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_COMMISSION_BPS = 10.0  # 0.10% per side
DEFAULT_SLIPPAGE_BPS = 5.0     # 0.05% per side
DEFAULT_POSITION_PCT = 1.0     # fraction of equity committed per entry
# Annual borrow fee charged while a short position is open. 50 bps is a typical
# easy-to-borrow rate; hard-to-borrow names cost far more. Zero would let a
# short be held indefinitely for free.
DEFAULT_BORROW_BPS_ANNUAL = 50.0
# Annual interest on a negative cash balance, i.e. the cost of holding more than
# 100% exposure. Institutional funding sits near this level; retail margin is
# often 8-12%, which is why the figure is a visible, adjustable input rather
# than a constant buried in the engine — a levered result is only as good as
# the rate you can actually borrow at.
DEFAULT_FINANCING_BPS_ANNUAL = 500.0
# Minimum change in target exposure, as a fraction of the exposure already held,
# before the engine will trade. Zero reproduces classic all-in/all-out
# behaviour; a continuously-sized strategy needs a band or it pays commission
# every single bar.
DEFAULT_NO_TRADE_BAND = 0.0

RISK_FREE_RATE = 0.02  # annual, used by Sharpe/Sortino


def get_asset(key: str) -> Asset:
    try:
        return ASSETS[key.upper()]
    except KeyError:
        raise KeyError(f"Unknown asset '{key}'. Known: {', '.join(ASSETS)}") from None
