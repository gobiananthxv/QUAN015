"""
visualization/plotter.py — Four-panel dashboard for market regime detection results.

Panels
------
1. Price chart with regime color bands overlaid
2. Feature heatmap (rolling vol, returns, SMA distances over time)
3. HMM transition matrix heatmap  (or GMM component weights)
4. Regime-adjusted equity curve vs. buy-and-hold benchmark
"""

from __future__ import annotations

import logging
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns

from config import REGIME_COLORS, FIGURE_DPI, FIGURE_STYLE

logger = logging.getLogger(__name__)

try:
    plt.style.use(FIGURE_STYLE)
except OSError:
    plt.style.use("seaborn-v0_8-darkgrid" if "seaborn-v0_8-darkgrid" in plt.style.available
                  else "ggplot")


class RegimePlotter:
    """Generates publication-quality charts for regime detection results.

    Parameters
    ----------
    save_dir :
        If set, all figures are saved as PNG files to this directory.
    show :
        If ``True``, call ``plt.show()`` after each figure.
    """

    def __init__(
        self,
        save_dir: Optional[str] = None,
        show: bool = True,
    ) -> None:
        self.save_dir = save_dir
        self.show = show
        if save_dir:
            from pathlib import Path
            Path(save_dir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Main dashboard
    # ------------------------------------------------------------------

    def plot_dashboard(
        self,
        price_df: pd.DataFrame,
        regime_series: pd.Series,
        feature_df: pd.DataFrame,
        model,
        equity_curve: Optional[pd.Series] = None,
        benchmark: Optional[pd.Series] = None,
        ticker: str = "",
        model_type: str = "hmm",
    ) -> plt.Figure:
        """Four-panel regime dashboard.

        Parameters
        ----------
        price_df :
            OHLCV DataFrame.
        regime_series :
            DatetimeIndex → regime label.
        feature_df :
            Raw (unscaled) feature DataFrame.
        model :
            Fitted HMMRegimeModel or GMMRegimeModel.
        equity_curve :
            Optional regime-adjusted equity series (for panel 4).
        benchmark :
            Optional buy-and-hold equity series (for panel 4).
        ticker :
            Ticker symbol used in the title.
        model_type :
            ``"hmm"`` or ``"gmm"``.
        """
        has_equity = equity_curve is not None and benchmark is not None
        n_panels = 4 if has_equity else 3
        fig_height = 16 if has_equity else 13

        fig, axes = plt.subplots(
            n_panels, 1, figsize=(16, fig_height), dpi=FIGURE_DPI,
            gridspec_kw={"height_ratios": [3, 2, 2, 2][:n_panels]},
        )
        if n_panels == 3:
            axes = list(axes)

        fig.suptitle(
            f"Market Regime Detection — {ticker}  [{model_type.upper()}]",
            fontsize=16, fontweight="bold", y=0.98,
        )

        self._plot_price_with_regimes(axes[0], price_df, regime_series, ticker)
        self._plot_feature_heatmap(axes[1], feature_df)
        self._plot_transition_or_weights(axes[2], model, model_type)
        if has_equity:
            self._plot_equity_curves(axes[3], equity_curve, benchmark)

        fig.tight_layout(rect=[0, 0, 1, 0.97])
        self._save_or_show(fig, f"{ticker}_{model_type}_dashboard.png")
        return fig

    # ------------------------------------------------------------------
    # Individual panel methods
    # ------------------------------------------------------------------

    def _plot_price_with_regimes(
        self,
        ax: plt.Axes,
        price_df: pd.DataFrame,
        regime_series: pd.Series,
        ticker: str,
    ) -> None:
        """Panel 1: Price line with regime-colored background bands."""
        close = price_df["close"].reindex(regime_series.index)
        ax.plot(close.index, close.values, color="#2c3e50", linewidth=1.2, zorder=3)

        # Draw colored spans for each contiguous regime block
        legend_patches = {}
        prev_regime = None
        span_start = None

        for date, regime in regime_series.items():
            if regime != prev_regime:
                if prev_regime is not None and span_start is not None:
                    color = REGIME_COLORS.get(prev_regime, "#95a5a6")
                    ax.axvspan(span_start, date, alpha=0.25, color=color, zorder=1)
                    if prev_regime not in legend_patches:
                        legend_patches[prev_regime] = mpatches.Patch(
                            color=color, alpha=0.6, label=prev_regime
                        )
                span_start = date
                prev_regime = regime

        # Close the last span
        if prev_regime and span_start:
            color = REGIME_COLORS.get(prev_regime, "#95a5a6")
            ax.axvspan(span_start, regime_series.index[-1], alpha=0.25, color=color, zorder=1)
            if prev_regime not in legend_patches:
                legend_patches[prev_regime] = mpatches.Patch(
                    color=color, alpha=0.6, label=prev_regime
                )

        ax.set_title(f"{ticker} Price with Regime Bands", fontsize=13)
        ax.set_ylabel("Adjusted Close Price")
        ax.set_xlabel("")
        ax.legend(handles=list(legend_patches.values()), loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.4)

    def _plot_feature_heatmap(
        self,
        ax: plt.Axes,
        feature_df: pd.DataFrame,
    ) -> None:
        """Panel 2: Normalized feature values over time as a heatmap."""
        # Normalize each feature to [-1, 1] for visual comparability
        normed = feature_df.copy()
        for col in normed.columns:
            col_range = normed[col].max() - normed[col].min()
            if col_range > 0:
                normed[col] = 2 * (normed[col] - normed[col].min()) / col_range - 1

        # Downsample for performance (keep at most 500 date ticks)
        step = max(1, len(normed) // 500)
        normed_ds = normed.iloc[::step]

        sns.heatmap(
            normed_ds.T,
            ax=ax,
            cmap="RdYlGn",
            center=0,
            cbar_kws={"label": "Normalized value"},
            xticklabels=False,
            yticklabels=True,
        )
        ax.set_title("Feature Heatmap (normalized, green=high, red=low)", fontsize=13)
        ax.set_ylabel("")
        ax.tick_params(axis="y", labelsize=8)

    def _plot_transition_or_weights(
        self,
        ax: plt.Axes,
        model,
        model_type: str,
    ) -> None:
        """Panel 3: Transition matrix (HMM) or component weights bar chart (GMM)."""
        if model_type == "hmm":
            self._plot_hmm_transition(ax, model)
        else:
            self._plot_gmm_weights(ax, model)

    def _plot_hmm_transition(self, ax: plt.Axes, model) -> None:
        trans = model.transition_matrix
        n = trans.shape[0]
        state_labels = [f"S{i}" for i in range(n)]
        sns.heatmap(
            trans,
            ax=ax,
            annot=True,
            fmt=".2f",
            cmap="Blues",
            xticklabels=state_labels,
            yticklabels=state_labels,
            cbar_kws={"label": "Transition Probability"},
            vmin=0,
            vmax=1,
        )
        ax.set_title("HMM State Transition Matrix", fontsize=13)
        ax.set_xlabel("To State")
        ax.set_ylabel("From State")

    def _plot_gmm_weights(self, ax: plt.Axes, model) -> None:
        weights = model.weights
        n = len(weights)
        colors = [list(REGIME_COLORS.values())[i % len(REGIME_COLORS)] for i in range(n)]
        bars = ax.bar(
            [f"Component {i}" for i in range(n)],
            weights,
            color=colors,
            edgecolor="white",
        )
        for bar, w in zip(bars, weights):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.005,
                f"{w:.2%}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        ax.set_title("GMM Component Weights (Regime Priors)", fontsize=13)
        ax.set_ylabel("Weight")
        ax.set_ylim(0, max(weights) * 1.25)
        ax.grid(True, axis="y", alpha=0.4)

    def _plot_equity_curves(
        self,
        ax: plt.Axes,
        equity_curve: pd.Series,
        benchmark: pd.Series,
    ) -> None:
        """Panel 4: Regime-adjusted vs. buy-and-hold equity curves."""
        ax.plot(
            equity_curve.index, equity_curve.values,
            label="Regime-Adjusted Strategy", color="#27ae60", linewidth=1.5,
        )
        ax.plot(
            benchmark.index, benchmark.values,
            label="Buy & Hold", color="#e74c3c", linewidth=1.5, linestyle="--",
        )
        ax.set_title("Walk-Forward Equity Curve: Strategy vs. Buy & Hold", fontsize=13)
        ax.set_ylabel("Portfolio Value (normalized)")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.4)

    # ------------------------------------------------------------------
    # Regime distribution bar chart (standalone)
    # ------------------------------------------------------------------

    def plot_regime_distribution(
        self,
        regime_series: pd.Series,
        ticker: str = "",
    ) -> plt.Figure:
        """Bar chart of time spent in each regime."""
        counts = regime_series.value_counts()
        colors = [REGIME_COLORS.get(r, "#95a5a6") for r in counts.index]
        fig, ax = plt.subplots(figsize=(8, 4), dpi=FIGURE_DPI)
        bars = ax.bar(counts.index, counts.values, color=colors, edgecolor="white")
        for bar, val in zip(bars, counts.values):
            pct = 100 * val / counts.sum()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1,
                f"{val} days\n({pct:.1f}%)",
                ha="center", va="bottom", fontsize=9,
            )
        ax.set_title(f"Regime Distribution — {ticker}", fontsize=13)
        ax.set_ylabel("Trading Days")
        ax.grid(True, axis="y", alpha=0.4)
        fig.tight_layout()
        self._save_or_show(fig, f"{ticker}_regime_distribution.png")
        return fig

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _save_or_show(self, fig: plt.Figure, filename: str) -> None:
        if self.save_dir:
            from pathlib import Path
            path = Path(self.save_dir) / filename
            fig.savefig(path, bbox_inches="tight", dpi=FIGURE_DPI)
            logger.info("Saved figure: %s", path)
        if self.show:
            plt.show()
        else:
            plt.close(fig)
