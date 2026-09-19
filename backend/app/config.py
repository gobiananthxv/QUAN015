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

RISK_FREE_RATE = 0.02  # annual, used by Sharpe/Sortino


def get_asset(key: str) -> Asset:
    try:
        return ASSETS[key.upper()]
    except KeyError:
        raise KeyError(f"Unknown asset '{key}'. Known: {', '.join(ASSETS)}") from None
