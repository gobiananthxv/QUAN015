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

from ..config import get_asset
from ..analytics.indicators import bollinger, ema, realised_vol, roc, sma


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


@dataclass
class VolatilityTarget(Strategy):
    """Always invested, but never at a constant size.

    Every other strategy in this registry answers "am I in or out?". This one
    answers "how much?", which is the question that actually moves risk-adjusted
    return. Target exposure is

        scale = clip(target_vol / realised_vol, floor, cap)

    so the position shrinks when the market gets turbulent and grows when it
    calms down. Two consequences are worth stating plainly:

    * **It never goes flat.** Analysis of this dataset found 84-90% of the
      equity and gold return arrives overnight, while the market is shut; a
      strategy that sits in cash to avoid volatility forfeits that drift. Sizing
      down keeps you invested through the recovery you cannot time.
    * **``cap`` above 1.0 means borrowing.** Capping at 1.0 leaves the strategy
      systematically under-invested in calm markets, which costs return. Letting
      it lever up restores that, and the engine charges
      ``financing_bps_annual`` on the borrowed cash for as long as it is held.
      Whether the edge survives the funding cost is a question about your broker,
      not about the strategy, which is why the rate is an adjustable input.

    The target is continuous, so it would rebalance every bar if allowed to.
    Pair it with the engine's ``no_trade_band`` — a 10% band cut turnover by
    roughly a quarter in testing.

    The defaults are round numbers chosen for legibility, not tuned. Phase 5's
    robustness sweep decides whether they sit on a plateau or a spike, and the
    verdict it returns is the one this project reports.
    """

    name: ClassVar[str] = "vol_target"
    label: ClassVar[str] = "Volatility Target"
    description: ClassVar[str] = (
        "Always invested, sized inversely to recent volatility: smaller in "
        "turbulent markets, larger in calm ones, within a floor and a cap."
    )
    defaults: ClassVar[dict] = {
        "vol_window": 20,
        "target_vol": 0.25,
        "cap": 2.0,
        "floor": 0.2,
        "ann_factor": 252,
    }

    def validate(self) -> None:
        if self.params["vol_window"] < 2:
            raise ValueError("vol_window must be at least 2")
        if self.params["target_vol"] <= 0:
            raise ValueError("target_vol must be positive")
        if self.params["floor"] < 0:
            raise ValueError("floor must not be negative")
        if self.params["cap"] <= 0:
            raise ValueError("cap must be positive")
        if self.params["cap"] < self.params["floor"]:
            raise ValueError("cap must be at least floor")
        if self.params["ann_factor"] < 1:
            raise ValueError("ann_factor must be at least 1")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        vol = realised_vol(df["close"], self.params["vol_window"], self.params["ann_factor"])
        # Before the window is full there is no volatility estimate and
        # therefore no defensible size, so the strategy stays flat rather than
        # guessing. A zero reading (a run of identical closes) would divide to
        # infinity, so it is treated as "no estimate" too.
        scale = (self.params["target_vol"] / vol.where(vol > 0)).clip(
            lower=self.params["floor"], upper=self.params["cap"]
        )
        return scale.fillna(0.0).astype("float64")


# ---------------------------------------------------------------------------

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (SmaCrossover, EmaTrend, Momentum, MeanReversion, VolatilityTarget)
}

# Parameters that describe the *asset's* calendar rather than the strategy's
# behaviour. When the caller knows which asset is being traded, these are filled
# in from the registry so a BTC backtest is not annualised on an equity year.
CALENDAR_PARAMS = {"ann_factor"}


def get_strategy(name: str, params: dict | None = None, asset: str | None = None) -> Strategy:
    """Build a strategy by name. Raises KeyError on an unknown name.

    ``asset`` supplies calendar defaults (see :data:`CALENDAR_PARAMS`). An
    explicit value in ``params`` always wins, so the sweeps can still vary it.
    """
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise KeyError(f"Unknown strategy '{name}'. Known: {', '.join(REGISTRY)}") from None

    merged = dict(params or {})
    if asset is not None:
        for key in CALENDAR_PARAMS & set(cls.defaults):
            merged.setdefault(key, get_asset(asset).ann_factor)
    return cls(params=merged)


def list_strategies() -> list[dict]:
    """Catalogue for the API and the dashboard's configuration panel."""
    return [cls(params={}).describe() for cls in REGISTRY.values()]
