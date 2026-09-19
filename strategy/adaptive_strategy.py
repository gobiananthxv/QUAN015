"""
strategy/adaptive_strategy.py — Adjust trading parameters based on detected regime.

The AdaptiveStrategy class is a parameter recommendation engine:
  - It does NOT execute trades.
  - Given the current regime label, it returns the recommended position size,
    stop-loss, take-profit, and signal filter type.
  - It also computes a signal multiplier to scale raw strategy signals up/down.

Usage
-----
    strategy = AdaptiveStrategy()
    params = strategy.get_params("Bull")
    # {'position_size': 1.0, 'stop_loss_pct': 0.05, ...}

    multiplier = strategy.get_signal_multiplier("Bear")
    # 0.30  (scale signal strength down in bear markets)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd

from config import STRATEGY_PARAMS, REGIME_LABELS

logger = logging.getLogger(__name__)

# Default fallback when regime is unrecognized
_FALLBACK_PARAMS = STRATEGY_PARAMS["Unknown"]


class AdaptiveStrategy:
    """Returns regime-specific trading parameters.

    Parameters
    ----------
    custom_params :
        Optional dict of ``{regime_label: params_dict}`` to override defaults.
        Merged with (and takes precedence over) the defaults in ``config.py``.
    """

    def __init__(self, custom_params: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._params: Dict[str, Dict[str, Any]] = dict(STRATEGY_PARAMS)
        if custom_params:
            for label, overrides in custom_params.items():
                if label in self._params:
                    self._params[label].update(overrides)
                else:
                    self._params[label] = overrides

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_params(self, regime: str) -> Dict[str, Any]:
        """Return the strategy parameters for the given regime label.

        Parameters
        ----------
        regime :
            One of ``Bull``, ``Bear``, ``High-Volatility``, ``Sideways``,
            or ``Unknown``.

        Returns
        -------
        dict with keys:
          - ``position_size``   : fraction of portfolio to deploy (0–1)
          - ``stop_loss_pct``   : stop-loss as fraction of entry price
          - ``take_profit_pct`` : take-profit as fraction of entry price
          - ``signal_filter``   : string key identifying the signal type
          - ``leverage``        : leverage multiplier
          - ``description``     : human-readable explanation
        """
        params = self._params.get(regime)
        if params is None:
            logger.warning("Unknown regime '%s', using fallback params.", regime)
            return dict(_FALLBACK_PARAMS)
        return dict(params)

    def get_signal_multiplier(self, regime: str) -> float:
        """Return a [0, 1] multiplier to scale raw signal strength.

        Derived from ``position_size`` in the regime params.
        """
        return float(self.get_params(regime).get("position_size", 0.5))

    def apply_to_series(self, regime_series: pd.Series) -> pd.DataFrame:
        """Vectorized: return a DataFrame of params for each date in *regime_series*.

        Parameters
        ----------
        regime_series :
            A time-indexed :class:`~pandas.Series` of regime label strings.

        Returns
        -------
        pd.DataFrame with columns matching the strategy param keys, indexed by date.
        """
        records = [self.get_params(r) for r in regime_series]
        df = pd.DataFrame(records, index=regime_series.index)
        df.index.name = "date"
        return df

    def regime_summary(self) -> pd.DataFrame:
        """Return a table summarizing all configured regimes."""
        rows = []
        for label, params in self._params.items():
            rows.append(
                {
                    "Regime": label,
                    "Position Size": f"{params['position_size']:.0%}",
                    "Stop Loss": f"{params['stop_loss_pct']:.1%}",
                    "Take Profit": f"{params['take_profit_pct']:.1%}",
                    "Signal Filter": params["signal_filter"],
                    "Description": params["description"],
                }
            )
        return pd.DataFrame(rows).set_index("Regime")
