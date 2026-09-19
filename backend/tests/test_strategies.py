"""Strategy correctness.

Each strategy is checked against a price path constructed so the right answer
is known in advance, then against the two properties every strategy must have:
causality, and signals confined to a sane exposure range.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtest.strategies import (
    REGISTRY,
    EmaTrend,
    MeanReversion,
    Momentum,
    SmaCrossover,
    Strategy,
    VolatilityTarget,
    get_strategy,
    list_strategies,
)
from app.data.store import load_asset

ALL = list(REGISTRY)
# Strategies that answer "in or out?". The fifth one answers "how much?", so it
# is excluded wherever a test asserts the discrete alphabet.
DISCRETE = [n for n in ALL if n != "vol_target"]


def frame_from(closes, start="2020-01-01") -> pd.DataFrame:
    closes = np.asarray(closes, dtype="float64")
    idx = pd.date_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": np.full(len(closes), 1e6),
        },
        index=idx,
    )


# ================================================================ contract


@pytest.mark.parametrize("name", DISCRETE)
def test_discrete_signals_only_contain_legal_values(name):
    """A directional strategy says in, out or short and nothing in between;
    emitting something else means it is not saying what it thinks it is."""
    df = load_asset("NVDA")
    values = set(get_strategy(name).generate_signals(df).unique())
    assert values <= {-1.0, 0.0, 1.0}, f"{name} emitted {values}"


@pytest.mark.parametrize("name", ALL)
def test_signals_are_finite_and_bounded(name):
    """Whatever a strategy asks for, the engine will size to it literally. An
    infinite or absurd target would be executed, so the contract every strategy
    shares is that the number is finite and within a defensible range."""
    df = load_asset("NVDA")
    sig = get_strategy(name, asset="NVDA").generate_signals(df)
    assert np.isfinite(sig.to_numpy()).all(), f"{name} emitted a non-finite target"
    assert sig.abs().max() <= 3.0, f"{name} asked for {sig.abs().max():.2f}x exposure"


@pytest.mark.parametrize("name", ALL)
def test_signals_align_with_the_input_index(name):
    df = load_asset("GOLD")
    sig = get_strategy(name).generate_signals(df)
    assert sig.index.equals(df.index)
    assert not sig.isna().any(), "a NaN signal is an undefined position"


@pytest.mark.parametrize("name", ALL)
def test_strategy_is_causal(name):
    """Appending future bars must not change a single past signal.

    This is the strategy-level counterpart to the Phase 2 indicator causality
    suite. Together they close the loop: causal indicators feeding causal
    strategies feeding a one-bar-lagged engine.
    """
    df = load_asset("BTC").iloc[-800:]
    cut = 500
    strat = get_strategy(name)
    on_prefix = strat.generate_signals(df.iloc[:cut])
    on_full = strat.generate_signals(df).iloc[:cut]
    pd.testing.assert_series_equal(on_prefix, on_full, check_names=False)


@pytest.mark.parametrize("name", ALL)
def test_strategy_holds_a_position_sometimes_but_not_always(name):
    """A strategy that is never in the market, or always in it, is not a
    strategy — it is a bug or a benchmark."""
    exposure = get_strategy(name).generate_signals(load_asset("NVDA")).mean()
    assert 0.01 < exposure < 0.99, f"{name} exposure {exposure:.2%} is degenerate"


@pytest.mark.parametrize("name", ALL)
def test_warmup_period_is_flat(name):
    """Before its indicators are defined a strategy must be flat, never long."""
    df = load_asset("GOLD")
    assert get_strategy(name).generate_signals(df).iloc[:10].eq(0.0).all()


# ================================================================ SMA crossover


def test_sma_crossover_is_long_in_a_sustained_uptrend():
    """A steady climb puts the fast SMA above the slow one and keeps it there."""
    sig = SmaCrossover(params={"fast": 5, "slow": 20}).generate_signals(
        frame_from(np.arange(100.0, 200.0))
    )
    assert sig.iloc[30:].eq(1.0).all()


def test_sma_crossover_is_flat_in_a_sustained_downtrend():
    sig = SmaCrossover(params={"fast": 5, "slow": 20}).generate_signals(
        frame_from(np.arange(200.0, 100.0, -1.0))
    )
    assert sig.iloc[30:].eq(0.0).all()


def test_sma_crossover_flips_when_the_trend_reverses():
    """Up for 60 bars then down for 60: long early, flat late."""
    closes = np.concatenate([np.arange(100.0, 160.0), np.arange(160.0, 100.0, -1.0)])
    sig = SmaCrossover(params={"fast": 5, "slow": 20}).generate_signals(frame_from(closes))
    assert sig.iloc[55] == 1.0
    assert sig.iloc[-1] == 0.0


def test_sma_crossover_rejects_fast_slower_than_slow():
    with pytest.raises(ValueError, match="shorter than"):
        SmaCrossover(params={"fast": 200, "slow": 50})


def test_sma_crossover_rejects_equal_periods():
    with pytest.raises(ValueError):
        SmaCrossover(params={"fast": 50, "slow": 50})


# ================================================================ EMA trend


def test_ema_trend_is_long_when_price_leads_its_ema_upward():
    sig = EmaTrend(params={"span": 10, "roc_window": 5}).generate_signals(
        frame_from(np.arange(100.0, 200.0))
    )
    assert sig.iloc[20:].eq(1.0).all()


def test_ema_trend_is_flat_when_momentum_disagrees():
    """Falling prices sit below the EMA and have negative ROC: no position."""
    sig = EmaTrend(params={"span": 10, "roc_window": 5}).generate_signals(
        frame_from(np.arange(200.0, 100.0, -1.0))
    )
    assert sig.iloc[20:].eq(0.0).all()


def test_ema_trend_requires_both_conditions():
    """The ROC filter must actually bind — removing it would change the answer
    on a path that is above its EMA while momentum is negative."""
    rng = np.random.default_rng(3)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 600)))
    df = frame_from(closes)
    strat = EmaTrend(params={"span": 20, "roc_window": 10})
    from app.analytics.indicators import ema as _ema

    above = closes > _ema(df["close"], 20).to_numpy()
    combined = strat.generate_signals(df).to_numpy().astype(bool)
    assert combined.sum() < above.sum(), "ROC confirmation never rejected anything"


def test_ema_trend_rejects_bad_params():
    with pytest.raises(ValueError):
        EmaTrend(params={"span": 1, "roc_window": 10})


# ================================================================ momentum


def test_momentum_is_long_when_trailing_return_is_positive():
    sig = Momentum(params={"window": 20, "threshold": 0.0}).generate_signals(
        frame_from(np.arange(100.0, 200.0))
    )
    assert sig.iloc[25:].eq(1.0).all()


def test_momentum_is_flat_when_trailing_return_is_negative():
    sig = Momentum(params={"window": 20, "threshold": 0.0}).generate_signals(
        frame_from(np.arange(200.0, 100.0, -1.0))
    )
    assert sig.iloc[25:].eq(0.0).all()


def test_momentum_threshold_raises_the_bar():
    """A higher threshold can only ever reduce time in the market."""
    df = load_asset("BTC")
    loose = Momentum(params={"window": 90, "threshold": 0.0}).generate_signals(df).sum()
    strict = Momentum(params={"window": 90, "threshold": 0.25}).generate_signals(df).sum()
    assert strict < loose


def test_momentum_hand_computed_threshold_boundary():
    """+10% over the window, tested with band=0 to isolate threshold semantics.

    Thresholds are chosen clear of the +10% level rather than exactly on it: a
    test sitting on the boundary passes or fails on floating-point noise
    (110/100 - 1 evaluates to 0.10000000000000009, not 0.10) rather than on the
    behaviour it claims to check.
    """
    closes = np.concatenate([np.full(20, 100.0), np.full(10, 110.0)])
    df = frame_from(closes)

    too_high = Momentum(params={"window": 20, "threshold": 0.15, "band": 0.0})
    assert too_high.generate_signals(df).iloc[-1] == 0.0, "+10% must not clear a 15% bar"

    cleared = Momentum(params={"window": 20, "threshold": 0.05, "band": 0.0})
    assert cleared.generate_signals(df).iloc[-1] == 1.0, "+10% must clear a 5% bar"


def test_momentum_band_widens_the_entry_threshold():
    """Entry needs threshold + band; the same move that clears a bare 5%
    threshold must fail against 5% + a 5% band.

    +8% is used because it sits clear of both levels (above 0.05, below 0.10).
    A +10% move would land exactly on the banded threshold and the assertion
    would then turn on floating-point representation.
    """
    closes = np.concatenate([np.full(20, 100.0), np.full(10, 108.0)])
    df = frame_from(closes)

    no_band = Momentum(params={"window": 20, "threshold": 0.05, "band": 0.0})
    with_band = Momentum(params={"window": 20, "threshold": 0.05, "band": 0.05})
    assert no_band.generate_signals(df).iloc[-1] == 1.0
    assert with_band.generate_signals(df).iloc[-1] == 0.0


def test_momentum_holds_between_the_entry_and_exit_levels():
    """The point of the band: once long, a drift back toward the threshold must
    not immediately close the position."""
    closes = np.concatenate([
        np.full(30, 100.0),
        np.full(10, 130.0),   # +30% -> clears entry at threshold+band = 0.05
        np.full(10, 103.0),   # back to +3% -> between exit (-0.05) and entry
    ])
    df = frame_from(closes)
    sig = Momentum(params={"window": 20, "threshold": 0.0, "band": 0.05}).generate_signals(df)
    assert sig.iloc[35] == 1.0, "entered on the surge"
    assert sig.iloc[-1] == 1.0, "must still hold while inside the band"


def test_ema_trend_band_is_validated():
    with pytest.raises(ValueError, match="band"):
        EmaTrend(params={"span": 50, "roc_window": 20, "band": 1.5})
    with pytest.raises(ValueError, match="band"):
        EmaTrend(params={"span": 50, "roc_window": 20, "band": -0.1})


def test_ema_trend_band_reduces_whipsaw():
    """The structural reason the band exists: fewer noise trades.

    Asserted on trade COUNT, not on returns - the band is justified by not
    trading noise, not by the backtest number it happens to produce.
    """
    df = load_asset("GOLD")
    bare = EmaTrend(params={"span": 50, "roc_window": 20, "band": 0.0})
    banded = EmaTrend(params={"span": 50, "roc_window": 20, "band": 0.01})
    flips_bare = (bare.generate_signals(df).diff().fillna(0) != 0).sum()
    flips_banded = (banded.generate_signals(df).diff().fillna(0) != 0).sum()
    assert flips_banded < flips_bare


def test_momentum_band_reduces_whipsaw():
    df = load_asset("BTC")
    bare = Momentum(params={"window": 90, "threshold": 0.0, "band": 0.0})
    banded = Momentum(params={"window": 90, "threshold": 0.0, "band": 0.05})
    flips_bare = (bare.generate_signals(df).diff().fillna(0) != 0).sum()
    flips_banded = (banded.generate_signals(df).diff().fillna(0) != 0).sum()
    assert flips_banded < flips_bare


# ================================================================ mean reversion


def test_mean_reversion_buys_the_dip_and_exits_on_recovery():
    """Flat, then a sharp drop (buy), then recovery to the mean (exit)."""
    closes = np.concatenate([
        np.full(40, 100.0),
        np.array([88.0, 86.0, 85.0]),        # stretched well below the mean
        np.linspace(86.0, 104.0, 30),        # recover through the mean
    ])
    sig = MeanReversion(params={"window": 20, "entry_z": 2.0, "exit_z": 0.0}).generate_signals(
        frame_from(closes)
    )
    assert sig.iloc[40:44].max() == 1.0, "should have entered on the drop"
    assert sig.iloc[-1] == 0.0, "should have exited once price recovered"


def test_mean_reversion_holds_between_entry_and_exit():
    """The distinguishing property: it is stateful, not a momentary condition.

    Bar 40 drops to z = -4.4 and triggers entry. From bar 43 onward z has
    recovered past -2.0, so the *entry* condition is no longer true — yet the
    position must persist, because nothing has told it to exit yet. A stateless
    implementation would drop out here. It exits at bar 56, the first bar where
    z crosses back above 0.
    """
    closes = np.concatenate([
        np.full(40, 100.0),
        np.array([85.0]),
        np.linspace(85.5, 92.0, 25),
    ])
    df = frame_from(closes)
    strat = MeanReversion(params={"window": 20, "entry_z": 2.0, "exit_z": 0.0})
    sig = strat.generate_signals(df)

    from app.analytics.indicators import bollinger

    z = bollinger(df["close"], 20)["bb_z"]

    assert sig.iloc[40] == 1.0, "entry on the dip"
    assert sig.iloc[43:56].eq(1.0).all(), "must hold while the entry trigger is inactive"
    assert (z.iloc[43:56] > -2.0).all(), "entry condition really is inactive here"
    assert (z.iloc[43:56] < 0.0).all(), "exit condition really is inactive here"
    assert sig.iloc[56] == 0.0, "exits on the first bar z crosses above exit_z"
    assert z.iloc[56] >= 0.0


def test_mean_reversion_stays_flat_without_a_dip():
    sig = MeanReversion(params={"window": 20, "entry_z": 2.0}).generate_signals(
        frame_from(np.arange(100.0, 200.0))
    )
    assert sig.eq(0.0).all()


def test_mean_reversion_wider_entry_trades_less():
    df = load_asset("NVDA")
    tight = MeanReversion(params={"window": 20, "entry_z": 1.0}).generate_signals(df).sum()
    wide = MeanReversion(params={"window": 20, "entry_z": 3.0}).generate_signals(df).sum()
    assert wide < tight


def test_mean_reversion_rejects_impossible_exit():
    with pytest.raises(ValueError, match="never close"):
        MeanReversion(params={"window": 20, "entry_z": 2.0, "exit_z": -3.0})


def test_mean_reversion_rejects_non_positive_entry_z():
    with pytest.raises(ValueError, match="positive"):
        MeanReversion(params={"window": 20, "entry_z": 0.0})


# ================================================================ registry


def test_registry_contains_the_four_required_strategies():
    """The brief asks for at least three; four directional ones ship, plus a
    fifth that sizes rather than times."""
    assert {"sma_crossover", "ema_trend", "momentum", "mean_reversion"} <= set(REGISTRY)
    assert "vol_target" in REGISTRY


def test_get_strategy_rejects_unknown_names():
    with pytest.raises(KeyError, match="Unknown strategy"):
        get_strategy("bollinger_squeeze_9000")


def test_defaults_are_applied_when_no_params_given():
    assert get_strategy("sma_crossover").params == {"fast": 50, "slow": 200}


def test_partial_params_merge_over_defaults():
    assert get_strategy("sma_crossover", {"fast": 10}).params == {"fast": 10, "slow": 200}


def test_unknown_params_are_discarded_not_silently_honoured():
    """A typo'd parameter must not look like it took effect."""
    strat = get_strategy("momentum", {"windwo": 5})
    assert "windwo" not in strat.params
    assert strat.params == Momentum.defaults


def test_list_strategies_is_api_ready():
    listed = list_strategies()
    assert len(listed) == len(REGISTRY)
    for entry in listed:
        assert set(entry) == {"name", "label", "description", "params", "defaults"}
        assert entry["description"], f"{entry['name']} has no description"


def test_base_strategy_refuses_to_generate():
    with pytest.raises(NotImplementedError):
        Strategy().generate_signals(load_asset("GOLD"))


# ======================================================== volatility target


def test_vol_target_sizes_down_when_volatility_rises():
    """The whole premise in one assertion: same price level, more turbulence,
    smaller position."""
    calm = frame_from([100 + 0.2 * (-1) ** i for i in range(120)])
    wild = frame_from([100 + 8.0 * (-1) ** i for i in range(120)])

    strat = VolatilityTarget()
    calm_size = strat.generate_signals(calm).iloc[-1]
    wild_size = strat.generate_signals(wild).iloc[-1]
    assert wild_size < calm_size


def test_vol_target_stays_flat_until_it_has_a_volatility_estimate():
    """No estimate means no defensible size, so it holds nothing rather than
    guessing. The window needs vol_window returns, i.e. vol_window + 1 bars."""
    df = frame_from(np.linspace(100, 140, 60))
    sig = VolatilityTarget(params={"vol_window": 20}).generate_signals(df)
    assert (sig.iloc[:20] == 0.0).all()
    assert sig.iloc[20] != 0.0


def test_vol_target_respects_its_cap_and_floor():
    rng = np.random.default_rng(7)
    df = frame_from(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))
    sig = VolatilityTarget(params={"cap": 1.5, "floor": 0.4}).generate_signals(df)
    live = sig[sig != 0.0]
    assert live.max() <= 1.5
    assert live.min() >= 0.4


def test_vol_target_never_asks_to_go_short():
    """It is a sizing rule, not a directional one. Exposure is never negative."""
    rng = np.random.default_rng(3)
    df = frame_from(100 * np.exp(np.cumsum(rng.normal(-0.001, 0.03, 400))))
    assert (VolatilityTarget().generate_signals(df) >= 0).all()


def test_vol_target_survives_a_flat_price_run():
    """A run of identical closes gives zero volatility, which would divide to
    infinity. Gold has 82 such bars in the snapshot, so this is reachable."""
    df = frame_from([100.0] * 80)
    sig = VolatilityTarget().generate_signals(df)
    assert np.isfinite(sig.to_numpy()).all()
    assert (sig == 0.0).all()


def test_vol_target_uses_the_assets_calendar_when_it_is_known():
    """A BTC year is 365 bars, so the same price path annualises to a higher
    volatility and therefore a smaller position than it would for an equity."""
    assert get_strategy("vol_target", asset="BTC").params["ann_factor"] == 365
    assert get_strategy("vol_target", asset="NVDA").params["ann_factor"] == 252

    rng = np.random.default_rng(11)
    df = frame_from(100 * np.exp(np.cumsum(rng.normal(0, 0.015, 400))))
    crypto = get_strategy("vol_target", asset="BTC").generate_signals(df)
    equity = get_strategy("vol_target", asset="NVDA").generate_signals(df)
    assert crypto.mean() < equity.mean()


def test_an_explicit_calendar_parameter_beats_the_asset_default():
    """The sweeps have to be able to vary it like any other parameter."""
    strat = get_strategy("vol_target", {"ann_factor": 12}, asset="BTC")
    assert strat.params["ann_factor"] == 12


def test_vol_target_rejects_impossible_parameters():
    with pytest.raises(ValueError, match="target_vol"):
        VolatilityTarget(params={"target_vol": 0.0})
    with pytest.raises(ValueError, match="cap must be at least floor"):
        VolatilityTarget(params={"cap": 0.5, "floor": 1.0})
    with pytest.raises(ValueError, match="vol_window"):
        VolatilityTarget(params={"vol_window": 1})
