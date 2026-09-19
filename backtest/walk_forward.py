"""
backtest/walk_forward.py — Walk-forward validation to evaluate regime-adjusted returns.

Methodology (avoids look-ahead bias)
-------------------------------------
  For each fold i:
    train  = data[i : i + TRAIN_DAYS]
    test   = data[i + TRAIN_DAYS : i + TRAIN_DAYS + STEP_DAYS]
    1. Fit feature scaler + regime model on *train*.
    2. Predict regimes on *test* (using the scaler fitted on train).
    3. Apply AdaptiveStrategy position_size multiplier.
    4. Compute regime-adjusted returns vs. buy-and-hold benchmark.

Outputs
-------
  - fold_results : List[FoldResult] — per-fold metrics
  - equity_curve : pd.Series       — cumulative regime-adjusted portfolio value
  - benchmark    : pd.Series       — cumulative buy-and-hold value
  - metrics      : dict            — Sharpe, CAGR, max-drawdown for both strategies
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from config import (
    WALK_FORWARD_TRAIN_DAYS,
    WALK_FORWARD_STEP_DAYS,
    RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    DEFAULT_START_DATE,
    DEFAULT_TICKER,
)
from data.data_loader import DataLoader
from features.feature_engineering import FeatureEngineer
from models.base_model import BaseRegimeModel
from models.hmm_model import HMMRegimeModel
from models.gmm_model import GMMRegimeModel
from regime.labeler import RegimeLabeler
from strategy.adaptive_strategy import AdaptiveStrategy

logger = logging.getLogger(__name__)


@dataclass
class FoldResult:
    """Metrics for a single walk-forward fold."""

    fold_idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_states: int
    regimes_detected: List[str] = field(default_factory=list)
    regime_return: float = 0.0       # cumulative return of regime-adjusted strategy
    bh_return: float = 0.0           # cumulative return of buy-and-hold
    outperformance: float = 0.0      # regime_return - bh_return


@dataclass
class BacktestResult:
    """Full walk-forward backtest results."""

    ticker: str
    model_type: str
    fold_results: List[FoldResult]
    equity_curve: pd.Series           # cumulative portfolio value (starts at 1.0)
    benchmark: pd.Series              # cumulative buy-and-hold value (starts at 1.0)
    regime_series: pd.Series          # full out-of-sample regime series

    @property
    def metrics(self) -> dict:
        """Compute summary performance metrics."""
        return {
            "strategy": _compute_metrics(self.equity_curve, RISK_FREE_RATE),
            "benchmark": _compute_metrics(self.benchmark, RISK_FREE_RATE),
        }

    def summary(self) -> str:
        m = self.metrics
        s, b = m["strategy"], m["benchmark"]
        lines = [
            f"Walk-Forward Backtest — {self.ticker} ({self.model_type.upper()})",
            f"Folds          : {len(self.fold_results)}",
            "",
            f"{'Metric':<25} {'Strategy':>12} {'Buy & Hold':>12}",
            "-" * 52,
            f"{'CAGR':<25} {s['cagr']:>11.2%} {b['cagr']:>11.2%}",
            f"{'Sharpe Ratio':<25} {s['sharpe']:>12.2f} {b['sharpe']:>12.2f}",
            f"{'Max Drawdown':<25} {s['max_drawdown']:>11.2%} {b['max_drawdown']:>11.2%}",
            f"{'Total Return':<25} {s['total_return']:>11.2%} {b['total_return']:>11.2%}",
        ]
        return "\n".join(lines)


class WalkForwardBacktest:
    """Run walk-forward validation for regime-adjusted strategy.

    Parameters
    ----------
    ticker :
        Yahoo Finance symbol.
    model_type :
        ``"hmm"`` or ``"gmm"``.
    train_days :
        Number of trading days in the training window.
    step_days :
        Number of trading days to advance each fold.
    n_components :
        Fixed number of states (``None`` → auto-select).
    """

    def __init__(
        self,
        ticker: str = DEFAULT_TICKER,
        model_type: str = "hmm",
        train_days: int = WALK_FORWARD_TRAIN_DAYS,
        step_days: int = WALK_FORWARD_STEP_DAYS,
        n_components: Optional[int] = None,
        cache_dir: str = "data_cache",
    ) -> None:
        self.ticker = ticker
        self.model_type = model_type
        self.train_days = train_days
        self.step_days = step_days
        self.n_components = n_components
        self._loader = DataLoader(cache_dir=cache_dir)
        self._strategy = AdaptiveStrategy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        start: str = DEFAULT_START_DATE,
        end: Optional[str] = None,
        force_download: bool = False,
    ) -> BacktestResult:
        """Execute the walk-forward backtest.

        Returns
        -------
        :class:`BacktestResult`
        """
        price_df = self._loader.load(
            self.ticker, start=start, end=end, force_download=force_download
        )
        logger.info(
            "Walk-forward backtest: %d total rows, train=%d, step=%d",
            len(price_df),
            self.train_days,
            self.step_days,
        )

        fold_results: List[FoldResult] = []
        all_regime_dates: List[pd.Timestamp] = []
        all_regime_labels: List[str] = []
        all_strategy_returns: List[float] = []
        all_bh_returns: List[float] = []

        fold_idx = 0
        cursor = 0

        while cursor + self.train_days + self.step_days <= len(price_df):
            train_slice = price_df.iloc[cursor : cursor + self.train_days]
            test_slice = price_df.iloc[
                cursor + self.train_days : cursor + self.train_days + self.step_days
            ]

            fold_result, reg_dates, reg_labels, strat_rets, bh_rets = self._run_fold(
                fold_idx, train_slice, test_slice
            )
            fold_results.append(fold_result)
            all_regime_dates.extend(reg_dates)
            all_regime_labels.extend(reg_labels)
            all_strategy_returns.extend(strat_rets)
            all_bh_returns.extend(bh_rets)

            cursor += self.step_days
            fold_idx += 1

        if not fold_results:
            raise ValueError(
                "Not enough data for even one fold. "
                f"Need at least {self.train_days + self.step_days} rows."
            )

        # Build cumulative equity curves
        strat_ret_s = pd.Series(all_strategy_returns, index=all_regime_dates)
        bh_ret_s = pd.Series(all_bh_returns, index=all_regime_dates)
        equity_curve = (1 + strat_ret_s).cumprod()
        benchmark = (1 + bh_ret_s).cumprod()

        regime_series = pd.Series(
            all_regime_labels, index=all_regime_dates, name="regime"
        )

        logger.info("Walk-forward complete: %d folds.", len(fold_results))
        return BacktestResult(
            ticker=self.ticker,
            model_type=self.model_type,
            fold_results=fold_results,
            equity_curve=equity_curve,
            benchmark=benchmark,
            regime_series=regime_series,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_fold(
        self,
        fold_idx: int,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
    ):
        """Train on *train_df*, predict on *test_df*, compute returns."""
        # Feature engineering — fit scaler on train, transform test
        feat_eng = FeatureEngineer()
        X_train, _ = feat_eng.fit_transform(train_df)

        # Combine train + test to provide rolling-feature history context,
        # then slice out only the test rows after transform.
        # This is look-ahead safe: the *model* was fit only on train data.
        combined_df = pd.concat([train_df, test_df])
        X_combined, combined_idx = feat_eng.transform(combined_df)

        # Identify which combined rows fall within the test window
        test_mask = combined_idx >= test_df.index[0]
        X_test = X_combined[test_mask]
        test_idx = combined_idx[test_mask]

        if len(X_test) == 0:
            logger.warning("Fold %d: empty test features, skipping.", fold_idx)
            return (
                FoldResult(fold_idx, train_df.index[0], train_df.index[-1],
                           test_df.index[0], test_df.index[-1], 0),
                [], [], [], []
            )

        # Fit model on train data
        model = self._build_model()
        try:
            model.fit(X_train)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fold %d: model fit failed: %s", fold_idx, exc)
            return (
                FoldResult(fold_idx, train_df.index[0], train_df.index[-1],
                           test_df.index[0], test_df.index[-1], 0),
                [], [], [], []
            )

        # Predict on test
        raw_train_states = model.predict(X_train)
        raw_test_states = model.predict(X_test)

        # Labeler fitted on train
        raw_train_features = feat_eng.get_raw_features(train_df)
        labeler = RegimeLabeler(feature_names=FeatureEngineer.FEATURE_NAMES)
        labeler.fit(raw_train_features.values, raw_train_states)
        regime_labels = labeler.transform(raw_test_states).tolist()

        # Compute returns
        close_test = test_df["close"].reindex(test_idx)
        daily_bh = close_test.pct_change().fillna(0.0)

        strat_rets = []
        for regime, bh_ret in zip(regime_labels, daily_bh.values):
            multiplier = self._strategy.get_signal_multiplier(regime)
            strat_rets.append(bh_ret * multiplier)

        bh_rets = daily_bh.tolist()
        cum_strat = float(np.prod([1 + r for r in strat_rets]) - 1)
        cum_bh = float(np.prod([1 + r for r in bh_rets]) - 1)

        fold_result = FoldResult(
            fold_idx=fold_idx,
            train_start=train_df.index[0],
            train_end=train_df.index[-1],
            test_start=test_df.index[0],
            test_end=test_df.index[-1],
            n_states=model.n_states,
            regimes_detected=list(set(regime_labels)),
            regime_return=cum_strat,
            bh_return=cum_bh,
            outperformance=cum_strat - cum_bh,
        )

        return fold_result, list(test_idx), regime_labels, strat_rets, bh_rets


    def _build_model(self) -> BaseRegimeModel:
        if self.model_type == "hmm":
            return HMMRegimeModel(n_components=self.n_components)
        if self.model_type == "gmm":
            return GMMRegimeModel(n_components=self.n_components)
        raise ValueError(f"Unknown model_type: {self.model_type!r}")


# ---------------------------------------------------------------------------
# Performance metric helpers
# ---------------------------------------------------------------------------

def _compute_metrics(equity_curve: pd.Series, risk_free_rate: float = RISK_FREE_RATE) -> dict:
    """Compute CAGR, Sharpe Ratio, and Max Drawdown from a cumulative equity series."""
    if equity_curve.empty or len(equity_curve) < 2:
        return {"cagr": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "total_return": 0.0}

    daily_returns = equity_curve.pct_change().dropna()
    n_days = len(daily_returns)
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)
    years = n_days / TRADING_DAYS_PER_YEAR
    cagr = float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0

    excess = daily_returns - risk_free_rate / TRADING_DAYS_PER_YEAR
    sharpe = (
        float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
        if excess.std() > 0
        else 0.0
    )

    rolling_max = equity_curve.cummax()
    drawdowns = equity_curve / rolling_max - 1
    max_drawdown = float(drawdowns.min())

    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "total_return": total_return,
    }
