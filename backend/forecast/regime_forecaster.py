"""
forecast/regime_forecaster.py — Future regime prediction using HMM transition matrix.

How prediction works
--------------------
Given the current hidden-state probability vector p₀ (shape: n_states),
the probability of being in each state n steps ahead is:

    p(n) = p₀ · T^n

where T is the learned HMM transition matrix.

As n → ∞, p(n) converges to the **stationary distribution** π
(the left eigenvector of T for eigenvalue 1).  At that point the
forecast carries no useful information beyond the long-run base rates.

Prediction Horizon
------------------
We measure how long predictions stay "useful" via two metrics:

1. **Max Confidence** – the probability of the single most likely
   regime at each step ahead.  Horizon = last step where this exceeds
   `1/n_states + confidence_margin`.

2. **KL Divergence** – KL(p(n) ‖ π).  Horizon = last step where
   KL > `kl_threshold`.  High KL means we know more than the base rate.

Monte Carlo Simulation
-----------------------
We sample `n_paths` futures by rolling dice according to T at each step.
This shows the *distribution of possible futures* rather than just the
expected probability.

Usage
-----
    from forecast.regime_forecaster import RegimeForecaster

    forecaster = RegimeForecaster(result)          # RegimeResult from detector
    forecast_df = forecaster.forecast(n_steps=60)
    print(forecaster.prediction_horizon())
    forecaster.plot(save_path="output/plots/forecast.png")
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.colors import ListedColormap

from config import REGIME_COLORS, FIGURE_DPI, FIGURE_STYLE

logger = logging.getLogger(__name__)

try:
    plt.style.use(FIGURE_STYLE)
except OSError:
    plt.style.use("ggplot")


class RegimeForecaster:
    """Predicts future market regime probabilities using the HMM transition matrix.

    Parameters
    ----------
    result :
        A :class:`regime.detector.RegimeResult` from ``RegimeDetector.run()``.
        The model must be an ``HMMRegimeModel`` (uses transition matrix).
    confidence_margin :
        Extra margin above ``1/n_states`` to count as a "confident" prediction.
        Default ``0.10`` (10 percentage points above random).
    kl_threshold :
        KL divergence below which the forecast is considered "uninformative".
        Default ``0.02``.
    """

    def __init__(
        self,
        result,
        confidence_margin: float = 0.10,
        kl_threshold: float = 0.02,
    ) -> None:
        self._result = result
        self.confidence_margin = confidence_margin
        self.kl_threshold = kl_threshold

        # Validate model type
        model_type = getattr(result, "model_type", "")
        if model_type != "hmm":
            raise ValueError(
                f"RegimeForecaster requires an HMM result (got '{model_type}'). "
                "Run RegimeDetector with model_type='hmm'."
            )

        self._T: np.ndarray = result.model.transition_matrix   # (n, n)
        self._n_states: int  = result.model.n_states
        self._label_map: Dict[int, str] = result.label_map     # int → regime name
        self._stationary: np.ndarray = self._compute_stationary()

        # Current state probability vector (last observed day)
        self._p0: np.ndarray = result.state_proba.iloc[-1].values.astype(float)
        self._p0 = np.clip(self._p0, 1e-10, 1.0)
        self._p0 /= self._p0.sum()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def forecast(self, n_steps: int = 60) -> pd.DataFrame:
        """Compute future regime probability distributions for each step ahead.

        Parameters
        ----------
        n_steps :
            Number of trading days to forecast (default 60 ≈ 3 months).

        Returns
        -------
        pd.DataFrame, shape (n_steps, n_states)
            Index = 1 … n_steps (trading days ahead).
            Columns = regime label strings.
        """
        rows = []
        p = self._p0.copy()
        for _ in range(n_steps):
            p = p @ self._T
            row = {self._label_map.get(s, f"State {s}"): p[s] for s in range(self._n_states)}
            rows.append(row)

        df = pd.DataFrame(rows, index=range(1, n_steps + 1))
        df.index.name = "days_ahead"
        return df

    def stationary_distribution(self) -> pd.Series:
        """Long-run (stationary) regime probabilities — where the forecast converges."""
        return pd.Series(
            {self._label_map.get(s, f"State {s}"): self._stationary[s]
             for s in range(self._n_states)},
            name="stationary",
        )

    def confidence_decay(self, n_steps: int = 60) -> pd.DataFrame:
        """Return confidence metrics for each step ahead.

        Returns
        -------
        pd.DataFrame with columns:
          - ``max_prob``    : probability of the single most likely state
          - ``kl_div``      : KL(p(n) ‖ stationary)
          - ``entropy``     : Shannon entropy of p(n) in nats
          - ``top_regime``  : label of the most probable regime
          - ``is_useful``   : True while prediction is still informative
        """
        rows = []
        p = self._p0.copy()
        for _ in range(n_steps):
            p = p @ self._T
            max_prob   = float(p.max())
            top_state  = int(p.argmax())
            kl         = _kl_divergence(p, self._stationary)
            entropy    = _entropy(p)
            useful     = (
                max_prob > (1.0 / self._n_states + self.confidence_margin)
                and kl > self.kl_threshold
            )
            rows.append({
                "max_prob":   max_prob,
                "kl_div":     kl,
                "entropy":    entropy,
                "top_regime": self._label_map.get(top_state, f"State {top_state}"),
                "is_useful":  useful,
            })

        df = pd.DataFrame(rows, index=range(1, n_steps + 1))
        df.index.name = "days_ahead"
        return df

    def prediction_horizon(self, n_steps: int = 120) -> Dict[str, int]:
        """Estimate how many days ahead the forecast remains informative.

        Returns
        -------
        dict with keys:
          - ``max_prob_horizon`` : last day where max regime prob > threshold
          - ``kl_horizon``       : last day where KL divergence > kl_threshold
          - ``conservative``     : min of the two (safer estimate)
        """
        decay = self.confidence_decay(n_steps)
        useful = decay["is_useful"]
        # Find last consecutive useful day from the start
        # (once it becomes uninformative, we stop)
        mp_horizon = 0
        kl_horizon = 0
        for i, row in decay.iterrows():
            if row["max_prob"] > (1.0 / self._n_states + self.confidence_margin):
                mp_horizon = int(i)
            else:
                break
        for i, row in decay.iterrows():
            if row["kl_div"] > self.kl_threshold:
                kl_horizon = int(i)
            else:
                break
        return {
            "max_prob_horizon": mp_horizon,
            "kl_horizon":       kl_horizon,
            "conservative":     min(mp_horizon, kl_horizon),
        }

    def simulate_paths(
        self,
        n_paths: int = 500,
        n_steps: int = 60,
        seed: int = 42,
    ) -> np.ndarray:
        """Monte Carlo simulation of future regime paths.

        At each step, sample the next state from the transition distribution.

        Parameters
        ----------
        n_paths :
            Number of independent scenario paths.
        n_steps :
            Steps (trading days) per path.
        seed :
            Random seed for reproducibility.

        Returns
        -------
        np.ndarray, shape (n_paths, n_steps)
            Integer state IDs along each simulated path.
        """
        rng = np.random.default_rng(seed)
        # Start each path from a state sampled from the current distribution
        start_states = rng.choice(self._n_states, size=n_paths, p=self._p0)

        paths = np.empty((n_paths, n_steps), dtype=int)
        paths[:, 0] = start_states

        for step in range(1, n_steps):
            prev_states = paths[:, step - 1]
            next_states = np.array([
                rng.choice(self._n_states, p=self._T[s])
                for s in prev_states
            ])
            paths[:, step] = next_states

        return paths

    # -------------------------------------------------------------------------
    # Visualisation
    # -------------------------------------------------------------------------

    def plot(
        self,
        n_steps: int = 60,
        n_paths: int = 500,
        save_path: Optional[str] = None,
        show: bool = True,
    ) -> plt.Figure:
        """Generate a 4-panel future regime forecast dashboard.

        Panels
        ------
        1. Stacked area chart — probability of each regime over the forecast window
        2. Confidence decay — max probability and KL divergence vs days ahead
        3. Monte Carlo simulation heatmap — regime frequency across simulated paths
        4. Prediction horizon summary — bar chart with colour-coded horizon bands

        Parameters
        ----------
        n_steps :
            Trading days to forecast.
        n_paths :
            Monte Carlo paths for panel 3.
        save_path :
            If set, save the figure to this path.
        show :
            If ``True``, call ``plt.show()``.
        """
        forecast_df = self.forecast(n_steps)
        decay_df    = self.confidence_decay(n_steps)
        horizon     = self.prediction_horizon(n_steps * 2)
        paths       = self.simulate_paths(n_paths=n_paths, n_steps=n_steps)

        fig = plt.figure(figsize=(18, 16), dpi=FIGURE_DPI)
        fig.suptitle(
            f"Market Regime Forecast — {self._result.ticker}"
            f"  [Current: {self._result.current_regime}]"
            f"  |  Horizon: ~{horizon['conservative']} trading days",
            fontsize=15, fontweight="bold", y=0.99,
        )

        gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.42, wspace=0.32)

        ax1 = fig.add_subplot(gs[0, :])        # Full width: stacked area
        ax2 = fig.add_subplot(gs[1, 0])        # Left: confidence decay
        ax3 = fig.add_subplot(gs[1, 1])        # Right: MC heatmap
        ax4 = fig.add_subplot(gs[2, :])        # Full width: horizon summary

        self._plot_stacked_area(ax1, forecast_df, horizon)
        self._plot_confidence_decay(ax2, decay_df, horizon)
        self._plot_mc_heatmap(ax3, paths, n_steps)
        self._plot_horizon_summary(ax4, forecast_df, decay_df, horizon)

        if save_path:
            fig.savefig(save_path, bbox_inches="tight", dpi=FIGURE_DPI)
            logger.info("Forecast chart saved: %s", save_path)
        if show:
            plt.show()
        else:
            plt.close(fig)

        return fig

    # -------------------------------------------------------------------------
    # Panel rendering helpers
    # -------------------------------------------------------------------------

    def _plot_stacked_area(
        self,
        ax: plt.Axes,
        forecast_df: pd.DataFrame,
        horizon: dict,
    ) -> None:
        """Panel 1: Stacked area chart of future regime probabilities."""
        x = forecast_df.index.values
        regimes = list(forecast_df.columns)
        colors  = [REGIME_COLORS.get(r, "#95a5a6") for r in regimes]

        # Stack from bottom
        bottom = np.zeros(len(x))
        for regime, color in zip(regimes, colors):
            vals = forecast_df[regime].values
            ax.fill_between(x, bottom, bottom + vals, alpha=0.80, color=color,
                            label=regime, linewidth=0)
            bottom += vals

        # Horizon marker
        h = horizon["conservative"]
        if 0 < h <= len(x):
            ax.axvline(h, color="white", linewidth=2.5, linestyle="--", zorder=5)
            ax.text(h + 0.5, 0.97, f"Horizon\n~{h}d",
                    transform=ax.get_xaxis_transform(),
                    color="white", fontsize=10, fontweight="bold",
                    va="top", ha="left",
                    bbox=dict(boxstyle="round,pad=0.3", fc="#2c3e50", alpha=0.7))

        ax.set_xlim(1, len(x))
        ax.set_ylim(0, 1)
        ax.set_xlabel("Trading Days Ahead", fontsize=11)
        ax.set_ylabel("Probability", fontsize=11)
        ax.set_title("Future Regime Probability Distribution (Stacked)", fontsize=13)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.8)
        ax.grid(True, alpha=0.2)

        # Shade the "uncertain zone" past the horizon
        if 0 < h < len(x):
            ax.axvspan(h, len(x), color="gray", alpha=0.15,
                       label="Low-confidence zone")

    def _plot_confidence_decay(
        self,
        ax: plt.Axes,
        decay_df: pd.DataFrame,
        horizon: dict,
    ) -> None:
        """Panel 2: Max confidence and KL divergence vs days ahead."""
        x     = decay_df.index.values
        color_mp = "#27ae60"
        color_kl = "#e74c3c"

        ax2 = ax.twinx()

        ln1, = ax.plot(x, decay_df["max_prob"],
                       color=color_mp, linewidth=2.2, label="Max Regime Prob")
        ln2, = ax2.plot(x, decay_df["kl_div"],
                        color=color_kl, linewidth=2.2, linestyle="--",
                        label="KL Divergence")

        # Random-chance baseline
        baseline = 1.0 / self._n_states + self.confidence_margin
        ax.axhline(baseline, color=color_mp, linewidth=1.2, linestyle=":",
                   alpha=0.7, label=f"Confidence threshold ({baseline:.0%})")

        # KL threshold line
        ax2.axhline(self.kl_threshold, color=color_kl, linewidth=1.2,
                    linestyle=":", alpha=0.7)

        # Horizon line
        h = horizon["conservative"]
        if 0 < h <= len(x):
            ax.axvline(h, color="#2c3e50", linewidth=2, linestyle="--")
            ax.text(h + 0.4, baseline + 0.02,
                    f"Horizon\n~{h}d", fontsize=9, color="#2c3e50",
                    fontweight="bold")

        ax.set_xlim(1, len(x))
        ax.set_ylim(0, 1)
        ax.set_xlabel("Trading Days Ahead", fontsize=10)
        ax.set_ylabel("Max Regime Probability", fontsize=10, color=color_mp)
        ax2.set_ylabel("KL Divergence (nats)", fontsize=10, color=color_kl)
        ax.set_title("Prediction Confidence Decay", fontsize=12)
        ax.tick_params(axis="y", labelcolor=color_mp)
        ax2.tick_params(axis="y", labelcolor=color_kl)

        lines = [ln1, ln2]
        labels = [l.get_label() for l in lines]
        ax.legend(lines, labels, fontsize=8, loc="upper right")
        ax.grid(True, alpha=0.3)

    def _plot_mc_heatmap(
        self,
        ax: plt.Axes,
        paths: np.ndarray,
        n_steps: int,
    ) -> None:
        """Panel 3: Heatmap of regime frequency across Monte Carlo paths."""
        n_paths = paths.shape[0]
        freq = np.zeros((self._n_states, n_steps))
        for s in range(self._n_states):
            freq[s] = (paths == s).sum(axis=0) / n_paths

        # Map state IDs to regime names
        state_labels = [self._label_map.get(s, f"S{s}") for s in range(self._n_states)]
        colors_list  = [REGIME_COLORS.get(lbl, "#95a5a6") for lbl in state_labels]

        x = np.arange(1, n_steps + 1)
        bottom = np.zeros(n_steps)
        for s_idx, (lbl, color) in enumerate(zip(state_labels, colors_list)):
            ax.bar(x, freq[s_idx], bottom=bottom, color=color,
                   label=lbl, alpha=0.85, width=1.0, linewidth=0)
            bottom += freq[s_idx]

        ax.set_xlim(0.5, n_steps + 0.5)
        ax.set_ylim(0, 1)
        ax.set_xlabel("Trading Days Ahead", fontsize=10)
        ax.set_ylabel("Path Frequency", fontsize=10)
        ax.set_title(f"Monte Carlo Simulation ({n_paths:,} Paths)", fontsize=12)
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(True, axis="y", alpha=0.3)

    def _plot_horizon_summary(
        self,
        ax: plt.Axes,
        forecast_df: pd.DataFrame,
        decay_df: pd.DataFrame,
        horizon: dict,
    ) -> None:
        """Panel 4: Horizon summary — most likely regime per day with confidence shade."""
        x       = forecast_df.index.values
        regimes = list(forecast_df.columns)

        # Most likely regime at each step
        top_regime = forecast_df.idxmax(axis=1)
        top_prob   = forecast_df.max(axis=1)

        # Draw a horizontal colour band for each day
        for i, (day, regime) in enumerate(top_regime.items()):
            color = REGIME_COLORS.get(regime, "#95a5a6")
            ax.barh(0, 1, left=day - 1, height=0.6,
                    color=color, alpha=float(top_prob.iloc[i]) * 0.9 + 0.1)

        # Probability line on secondary axis
        ax2 = ax.twinx()
        ax2.plot(x, top_prob.values, color="#2c3e50", linewidth=2.0,
                 label="Top-regime probability")
        ax2.set_ylim(0, 1)
        ax2.set_ylabel("Confidence", fontsize=10)

        # Horizon bands
        h_cons = horizon["conservative"]
        h_max  = max(horizon["max_prob_horizon"], horizon["kl_horizon"])
        if 0 < h_cons <= len(x):
            ax.axvline(h_cons - 1, color="red", linewidth=2.5, linestyle="--")
            ax.text(h_cons - 1 + 0.3, 0.35,
                    f"Conservative\nhorizon\n~{h_cons}d",
                    fontsize=9, color="red", fontweight="bold")
        if h_max != h_cons and 0 < h_max <= len(x):
            ax.axvline(h_max - 1, color="orange", linewidth=2.0, linestyle="--")
            ax.text(h_max - 1 + 0.3, -0.25,
                    f"Max\nhorizon\n~{h_max}d",
                    fontsize=9, color="orange", fontweight="bold")

        # Legend patches
        patches = [mpatches.Patch(color=REGIME_COLORS.get(r, "#95a5a6"),
                                   label=r, alpha=0.8)
                   for r in regimes if r in REGIME_COLORS]
        ax.legend(handles=patches, loc="upper right", fontsize=8)
        ax.set_xlim(0, len(x))
        ax.set_ylim(-0.5, 0.5)
        ax.set_yticks([])
        ax.set_xlabel("Trading Days Ahead", fontsize=11)
        ax.set_title(
            "Most Likely Future Regime per Day  "
            "(colour intensity = confidence, dashed = prediction horizon)",
            fontsize=12,
        )
        ax.grid(True, axis="x", alpha=0.3)
        ax2.legend(fontsize=8, loc="lower right")

    # -------------------------------------------------------------------------
    # Stationary distribution
    # -------------------------------------------------------------------------

    def _compute_stationary(self) -> np.ndarray:
        """Compute left eigenvector of T for eigenvalue 1 (stationary dist)."""
        T = self._T
        # Solve π @ (T - I) = 0 with constraint sum(π) = 1
        n = T.shape[0]
        A = (T - np.eye(n)).T
        A = np.vstack([A, np.ones(n)])
        b = np.zeros(n + 1)
        b[-1] = 1.0
        try:
            pi, *_ = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError:
            pi = np.ones(n) / n
        pi = np.clip(pi, 1e-10, 1.0)
        pi /= pi.sum()
        return pi


# ─────────────────────────────────────────────────────────────────────────────
# Math helpers
# ─────────────────────────────────────────────────────────────────────────────

def _kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """KL(p ‖ q) in nats.  Both arrays clipped to avoid log(0)."""
    p = np.clip(p, 1e-10, 1.0)
    q = np.clip(q, 1e-10, 1.0)
    return float(np.sum(p * np.log(p / q)))


def _entropy(p: np.ndarray) -> float:
    """Shannon entropy in nats."""
    p = np.clip(p, 1e-10, 1.0)
    return float(-np.sum(p * np.log(p)))
