"""Trading strategies.

Every strategy is a pure function of the price frame and its parameters:

    generate_signals(df) -> Series of target positions in {-1, 0, 1}

The value at bar *t* is the position the strategy wants **as of that bar's
close**. It is the engine's job, not the strategy's, to lag that by one bar and
fill it at the next open — so a strategy can never accidentally introduce
look-ahead by being written carelessly. Strategies only ever read causal
indicators (Phase 2 proves each one is causal), so the whole chain is clean.

Adding a fifth strategy means subclassing :class:`Strategy` and registering it;
nothing else in the platform changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import pandas as pd

from ..analytics.indicators import bollinger, ema, roc, sma


@dataclass
class Strategy:
    """Base class. Subclasses declare defaults and implement ``generate_signals``."""

    name: ClassVar[str] = "base"
    label: ClassVar[str] = "Base"
    description: ClassVar[str] = ""
    defaults: ClassVar[dict] = {}

    params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        merged = {**self.defaults, **(self.params or {})}
        self.params = {k: merged[k] for k in self.defaults}  # drop unknown keys
        self.validate()

    def validate(self) -> None:
        """Raise ValueError on a parameter combination that cannot work."""

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _hold(entry: pd.Series, exit_: pd.Series, index: pd.Index) -> pd.Series:
        """State machine: go long on ``entry``, flat on ``exit_``, else hold.

        Causal by construction — a forward fill only ever propagates a decision
        forwards in time.
        """
        state = pd.Series(pd.NA, index=index, dtype="object")
        state[entry] = 1.0
        state[exit_ & ~entry] = 0.0
        return state.ffill().fillna(0.0).astype("float64")

    def describe(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "params": dict(self.params),
            "defaults": dict(self.defaults),
        }


# ---------------------------------------------------------------------------


@dataclass
class SmaCrossover(Strategy):
    """Classic trend filter: long while the fast SMA sits above the slow one."""

    name: ClassVar[str] = "sma_crossover"
    label: ClassVar[str] = "SMA Crossover"
    description: ClassVar[str] = (
        "Long while the fast simple moving average is above the slow one, flat otherwise."
    )
    defaults: ClassVar[dict] = {"fast": 50, "slow": 200}

    def validate(self) -> None:
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("fast period must be shorter than slow period")
        if self.params["fast"] < 2:
            raise ValueError("fast period must be at least 2")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fast = sma(close, self.params["fast"])
        slow = sma(close, self.params["slow"])
        ready = fast.notna() & slow.notna()
        return (fast > slow).where(ready, False).astype("float64")


@dataclass
class EmaTrend(Strategy):
    """Price above its EMA, with momentum agreeing, inside a confirmation band.

    Two filters beyond a plain price-vs-EMA rule:

    * **ROC confirmation** refuses to buy a market that is above its average
      only because the average is falling faster than the price.
    * **A confirmation band** (``band``) separates the entry threshold from the
      exit threshold, so the signal cannot flip on a single tick across the EMA.

    The band exists for a structural reason, not a performance one. Without it
    this rule tests a strict inequality against a noisy quantity: on gold, 50%
    of its trades lasted two bars or fewer and transaction costs consumed 67% of
    its gross return. Trading noise at that rate is a defect you can identify
    without looking at a single return figure.

    The band makes the strategy **stateful** — between the two thresholds it
    holds whatever position it already had. ``band=0`` collapses the thresholds
    back together but keeps the hold-through behaviour, so it is not identical
    to the original stateless rule.

    The default is a round 1%, deliberately not tuned. Phase 5's robustness
    sweep decides whether that choice is a stable plateau or a lucky spike.
    """

    name: ClassVar[str] = "ema_trend"
    label: ClassVar[str] = "EMA Trend"
    description: ClassVar[str] = (
        "Long when price clears its EMA by a confirmation band and rate-of-change "
        "agrees; exits when price falls back through the band."
    )
    defaults: ClassVar[dict] = {"span": 50, "roc_window": 20, "band": 0.01}

    def validate(self) -> None:
        if self.params["span"] < 2:
            raise ValueError("span must be at least 2")
        if self.params["roc_window"] < 1:
            raise ValueError("roc_window must be at least 1")
        if not 0.0 <= self.params["band"] < 1.0:
            raise ValueError("band must be a fraction in [0, 1)")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        band = self.params["band"]
        trend = ema(close, self.params["span"])
        momentum = roc(close, self.params["roc_window"])

        entry = ((close > trend * (1 + band)) & (momentum > 0)).fillna(False)
        exit_ = (close < trend * (1 - band)).fillna(False)
        return self._hold(entry, exit_, df.index)


@dataclass
class Momentum(Strategy):
    """Time-series momentum: hold while trailing return clears a threshold.

    Like :class:`EmaTrend`, the raw rule tests a strict inequality against a
    noisy quantity and oscillates near the boundary — 31-43% of its trades
    lasted two bars or fewer. ``band`` widens the threshold into an entry level
    and a lower exit level, and the position is held between them.

    The default is a round 5%, deliberately not tuned.
    """

    name: ClassVar[str] = "momentum"
    label: ClassVar[str] = "Momentum"
    description: ClassVar[str] = (
        "Long while trailing rate-of-change clears a threshold by a band; exits "
        "when it falls the same distance below."
    )
    defaults: ClassVar[dict] = {"window": 90, "threshold": 0.0, "band": 0.05}

    def validate(self) -> None:
        if self.params["window"] < 2:
            raise ValueError("window must be at least 2")
        if self.params["band"] < 0.0:
            raise ValueError("band must not be negative")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        momentum = roc(df["close"], self.params["window"])
        threshold, band = self.params["threshold"], self.params["band"]

        entry = (momentum > threshold + band).fillna(False)
        exit_ = (momentum < threshold - band).fillna(False)
        return self._hold(entry, exit_, df.index)


@dataclass
class MeanReversion(Strategy):
    """Buy statistical cheapness, sell the reversion.

    Enters when price falls ``entry_z`` standard deviations below its own
    rolling mean, exits once it has recovered to ``exit_z``. Unlike the three
    trend strategies this one is stateful — being oversold is an *event*, not a
    condition that persists — so it holds its position between the two.
    """

    name: ClassVar[str] = "mean_reversion"
    label: ClassVar[str] = "Mean Reversion"
    description: ClassVar[str] = (
        "Buy when price is stretched below its Bollinger mean, exit on reversion to it."
    )
    defaults: ClassVar[dict] = {"window": 20, "entry_z": 2.0, "exit_z": 0.0}

    def validate(self) -> None:
        if self.params["window"] < 3:
            raise ValueError("window must be at least 3")
        if self.params["entry_z"] <= 0:
            raise ValueError("entry_z must be positive (it is a distance below the mean)")
        if self.params["exit_z"] < -self.params["entry_z"]:
            raise ValueError("exit_z must be above the entry level or the trade can never close")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        z = bollinger(df["close"], self.params["window"])["bb_z"]
        entry = (z <= -self.params["entry_z"]).fillna(False)
        exit_ = (z >= self.params["exit_z"]).fillna(False)
        return self._hold(entry, exit_, df.index)


# ---------------------------------------------------------------------------

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (SmaCrossover, EmaTrend, Momentum, MeanReversion)
}


def get_strategy(name: str, params: dict | None = None) -> Strategy:
    """Build a strategy by name. Raises KeyError on an unknown name."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise KeyError(f"Unknown strategy '{name}'. Known: {', '.join(REGISTRY)}") from None
    return cls(params=params or {})


def list_strategies() -> list[dict]:
    """Catalogue for the API and the dashboard's configuration panel."""
    return [cls(params={}).describe() for cls in REGISTRY.values()]
