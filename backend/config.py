"""
config.py — Centralized configuration for the ML-Based Market Regime Detection system.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
DEFAULT_TICKER = "SPY"
DEFAULT_TICKERS = ["SPY", "QQQ"]
DEFAULT_START_DATE = "2005-01-01"
DEFAULT_END_DATE = None  # None → today

DATA_CACHE_DIR = "data_cache"

# ---------------------------------------------------------------------------
# Feature engineering windows (in trading days)
# ---------------------------------------------------------------------------
RETURN_WINDOWS = [5, 21]          # short-term (1-week) and medium-term (1-month) log returns
VOLATILITY_WINDOW = 21             # 21-day realized volatility (annualized)
SMA_WINDOWS = [50, 200]            # simple moving average windows
EMA_SHORT = 12
EMA_LONG = 26
TRADING_DAYS_PER_YEAR = 252
VOL_SPIKE_MULTIPLIER = 2.0         # vol > N × long-term median → high-vol flag

# ---------------------------------------------------------------------------
# Model hyperparameters
# ---------------------------------------------------------------------------

@dataclass
class HMMConfig:
    n_components_range: List[int] = field(default_factory=lambda: [2, 3, 4, 5])
    covariance_type: str = "full"      # full | tied | diag | spherical
    n_iter: int = 200
    tol: float = 1e-4
    n_init: int = 5                    # number of random restarts (pick best BIC)
    random_state: int = 42
    algorithm: str = "viterbi"         # viterbi | map


@dataclass
class GMMConfig:
    n_components_range: List[int] = field(default_factory=lambda: [2, 3, 4, 5])
    covariance_type: str = "full"
    n_init: int = 10
    max_iter: int = 300
    tol: float = 1e-4
    random_state: int = 42


HMM_CONFIG = HMMConfig()
GMM_CONFIG = GMMConfig()

# ---------------------------------------------------------------------------
# Regime labels
# ---------------------------------------------------------------------------
REGIME_LABELS = {
    "bull": "Bull",
    "bear": "Bear",
    "high_vol": "High-Volatility",
    "sideways": "Sideways",
    "unknown": "Transitional",
}

# Thresholds used by RegimeLabeler to assign semantic names
# (based on annualised return and annualised volatility of each cluster)
BULL_RETURN_THRESHOLD = 0.05        # mean annualized return > 5%  → bullish candidate
BEAR_RETURN_THRESHOLD = -0.02       # mean annualized return < -2%  → bearish candidate
HIGH_VOL_THRESHOLD = 0.20           # annualized vol > 20%          → high-vol candidate
SIDEWAYS_VOL_THRESHOLD = 0.15       # vol < 15% and |return| < 5%   → sideways

# ---------------------------------------------------------------------------
# Strategy parameters per regime
# ---------------------------------------------------------------------------
STRATEGY_PARAMS: Dict[str, Dict[str, Any]] = {
    "Bull": {
        "position_size": 1.00,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.20,
        "signal_filter": "trend_following",
        "leverage": 1.0,
        "description": "Full exposure, trend-following, wide stops.",
    },
    "Bear": {
        "position_size": 0.30,
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.08,
        "signal_filter": "mean_reversion",
        "leverage": 0.3,
        "description": "Reduced exposure, tight stops, mean-reversion bias or cash.",
    },
    "High-Volatility": {
        "position_size": 0.50,
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.10,
        "signal_filter": "volatility_breakout",
        "leverage": 0.5,
        "description": "Half exposure, volatility-breakout signals, moderate stops.",
    },
    "Sideways": {
        "position_size": 0.70,
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.12,
        "signal_filter": "range_bound",
        "leverage": 0.7,
        "description": "Mostly invested, range-bound / oscillator-based signals.",
    },
    "Transitional": {
        "position_size": 0.50,
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.10,
        "signal_filter": "neutral",
        "leverage": 0.5,
        "description": "Transitional / structural shift state: conservative half-exposure.",
    },
    "Unknown": {
        "position_size": 0.50,
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.10,
        "signal_filter": "neutral",
        "leverage": 0.5,
        "description": "Fallback: conservative half-exposure.",
    },
}

# ---------------------------------------------------------------------------
# Walk-forward backtest
# ---------------------------------------------------------------------------
WALK_FORWARD_TRAIN_DAYS = 252       # 1 year of trading days for training
WALK_FORWARD_STEP_DAYS = 21         # 1 month step between folds
RISK_FREE_RATE = 0.04               # annual risk-free rate for Sharpe calculation

# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------
REGIME_COLORS = {
    "Bull": "#2ecc71",
    "Bear": "#e74c3c",
    "High-Volatility": "#f39c12",
    "Sideways": "#3498db",
    "Transitional": "#8b5cf6",
    "Unknown": "#8b5cf6",
}


FIGURE_DPI = 150
FIGURE_STYLE = "seaborn-v0_8-darkgrid"
