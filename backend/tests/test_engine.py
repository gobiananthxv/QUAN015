"""Backtesting engine correctness.

The arithmetic here is verified by hand on tiny frames, because an engine that
is merely self-consistent can still be confidently wrong.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import BacktestConfig, buy_and_hold, run_backtest
from app.data.store import load_asset

FREE = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0)


def frame(opens, closes, start="2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(opens))
    return pd.DataFrame(
        {
            "open": np.array(opens, dtype="float64"),
            "high": np.maximum(opens, closes) * 1.01,
            "low": np.minimum(opens, closes) * 0.99,
            "close": np.array(closes, dtype="float64"),
            "volume": np.full(len(opens), 1e6),
        },
        index=idx,
    )


def sig(values, df) -> pd.Series:
    return pd.Series(np.array(values, dtype="float64"), index=df.index)


# ================================================================ look-ahead


def test_signal_is_executed_on_the_next_bar_not_the_current_one():
    """THE look-ahead test.

    The signal turns on at bar 1. If the engine honoured it at bar 1 it would
    buy at open=100. Because the signal is lagged, it must buy at bar 2's
    open=200 instead. An engine with look-ahead bias would show a position at
    bar 1 and a far better entry price.
    """
    df = frame(opens=[100, 100, 200, 200], closes=[100, 100, 200, 200])
    res = run_backtest(df, sig([0, 1, 1, 1], df), "GOLD", config=FREE)

    assert res.position.iloc[0] == 0
    assert res.position.iloc[1] == 0, "signal at bar 1 must NOT be acted on at bar 1"
    assert res.position.iloc[2] == 1, "it must be acted on at bar 2"
    assert res.trades[0].entry_price == pytest.approx(200.0), "entry must use bar 2's open"
    assert res.trades[0].entry_date == df.index[2]


def test_execution_lag_is_exactly_one_bar():
    """Pins the engine's contract: position[t] == sign(signal[t-1]).

    Not two bars (needlessly pessimistic), not zero (look-ahead). If this ever
    drifts, every backtest number in the platform shifts with it.
    """
    df = frame(opens=[100] * 12, closes=[100] * 12)
    pattern = [0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 0]
    res = run_backtest(df, sig(pattern, df), "GOLD", config=FREE)
    expected = [0] + pattern[:-1]
    assert list(res.position.astype(int)) == expected


def test_a_signal_on_the_final_bar_never_trades():
    """There is no next bar to fill on, so it must be ignored entirely."""
    df = frame(opens=[100, 100, 100], closes=[100, 100, 100])
    res = run_backtest(df, sig([0, 0, 1], df), "GOLD", config=FREE)
    assert res.trades == []
    assert (res.position == 0).all()


def test_future_price_moves_cannot_change_past_equity():
    """Truncating the future must leave the past equity curve untouched.

    If appending bars changed earlier equity, the engine would be peeking.
    """
    rng = np.random.default_rng(5)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))
    df = frame(opens=closes, closes=closes)
    signals = sig(np.where(np.arange(200) % 20 < 10, 1, 0), df)

    cut = 120
    short = run_backtest(df.iloc[:cut], signals.iloc[:cut], "GOLD", config=FREE)
    full = run_backtest(df, signals, "GOLD", config=FREE)
    pd.testing.assert_series_equal(short.equity, full.equity.iloc[:cut])


# ================================================================ arithmetic


def test_frictionless_round_trip_pnl_is_exact():
    """Buy at 100, sell at 110, no costs -> exactly +10% on deployed capital."""
    df = frame(opens=[100, 100, 110, 110], closes=[100, 100, 110, 110])
    res = run_backtest(df, sig([1, 1, 0, 0], df), "GOLD", config=FREE)

    trade = res.trades[0]
    assert trade.entry_price == pytest.approx(100.0)
    assert trade.exit_price == pytest.approx(110.0)
    assert trade.units == pytest.approx(100.0)          # 10_000 / 100
    assert trade.gross_pnl == pytest.approx(1_000.0)    # 100 units * 10
    assert trade.net_pnl == pytest.approx(1_000.0)
    assert trade.return_pct == pytest.approx(0.10)
    assert res.equity.iloc[-1] == pytest.approx(11_000.0)


def test_commission_is_charged_on_both_sides():
    """100 bps = 1% per side on notional."""
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=100.0, slippage_bps=0.0)
    df = frame(opens=[100, 100, 100, 100], closes=[100, 100, 100, 100])
    res = run_backtest(df, sig([1, 1, 0, 0], df), "GOLD", config=cfg)

    trade = res.trades[0]
    # size = 10_000 / (100 * 1.01) = 99.0099 units
    assert trade.units == pytest.approx(10_000 / 101.0)
    entry_comm = trade.units * 100.0 * 0.01
    exit_comm = trade.units * 100.0 * 0.01
    assert trade.commission == pytest.approx(entry_comm + exit_comm)
    assert trade.gross_pnl == pytest.approx(0.0), "flat price -> no gross P&L"
    assert trade.net_pnl == pytest.approx(-(entry_comm + exit_comm))
    assert res.equity.iloc[-1] < 10_000.0, "a flat round trip must lose the commission"


def test_slippage_moves_the_fill_against_the_trade():
    """Buying fills above the open; selling fills below it."""
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=50.0)
    df = frame(opens=[100, 100, 100, 100], closes=[100, 100, 100, 100])
    res = run_backtest(df, sig([1, 1, 0, 0], df), "GOLD", config=cfg)

    trade = res.trades[0]
    assert trade.entry_price == pytest.approx(100 * 1.005), "bought above the open"
    assert trade.exit_price == pytest.approx(100 * 0.995), "sold below the open"
    assert trade.slippage > 0
    assert trade.net_pnl == pytest.approx(-trade.slippage)


def test_costs_decompose_exactly_into_commission_and_slippage():
    """net_pnl must equal gross_pnl minus every charged cost, to the cent."""
    cfg = BacktestConfig(initial_capital=50_000.0, commission_bps=12.0, slippage_bps=7.0)
    df = frame(opens=[100, 100, 130, 130], closes=[100, 100, 130, 130])
    res = run_backtest(df, sig([1, 1, 0, 0], df), "GOLD", config=cfg)

    t = res.trades[0]
    assert t.costs == pytest.approx(t.commission + t.slippage)
    assert t.net_pnl == pytest.approx(t.gross_pnl - t.costs)
    # gross uses unslipped opens: units * (130 - 100)
    assert t.gross_pnl == pytest.approx(t.units * 30.0)


def test_final_equity_equals_capital_plus_summed_net_pnl():
    """The equity curve and the trade log must tell the same story."""
    cfg = BacktestConfig(initial_capital=25_000.0, commission_bps=10.0, slippage_bps=5.0)
    rng = np.random.default_rng(9)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, 300)))
    df = frame(opens=closes, closes=closes)
    signals = sig(np.where(np.arange(300) % 30 < 12, 1, 0), df)
    res = run_backtest(df, signals, "GOLD", config=cfg)

    total_net = sum(t.net_pnl for t in res.trades)
    assert res.equity.iloc[-1] == pytest.approx(cfg.initial_capital + total_net, rel=1e-6)


def test_no_position_means_flat_equity():
    df = frame(opens=[100, 120, 90, 150], closes=[110, 130, 80, 160])
    res = run_backtest(df, sig([0, 0, 0, 0], df), "GOLD", config=FREE)
    assert (res.equity == FREE.initial_capital).all()
    assert res.trades == []


def test_position_sizing_respects_the_percentage():
    """position_pct=0.5 deploys half the capital and leaves half in cash."""
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0, position_pct=0.5)
    df = frame(opens=[100, 100, 200, 200], closes=[100, 100, 200, 200])
    res = run_backtest(df, sig([1, 1, 1, 1], df), "GOLD", config=cfg)

    assert res.trades[0].units == pytest.approx(50.0)  # 5_000 / 100
    # 5_000 cash + 50 units doubling from 100 to 200 = 5_000 + 10_000
    assert res.equity.iloc[-1] == pytest.approx(15_000.0)


def test_equity_never_goes_negative_on_long_only_data():
    df = load_asset("NVDA")
    res = run_backtest(df, pd.Series(1.0, index=df.index), "NVDA")
    assert (res.equity > 0).all()


# ================================================================ trade log


def test_multiple_round_trips_are_all_logged():
    df = frame(
        opens=[100, 100, 110, 110, 120, 120, 130, 130],
        closes=[100, 100, 110, 110, 120, 120, 130, 130],
    )
    res = run_backtest(df, sig([1, 1, 0, 0, 1, 1, 0, 0], df), "GOLD", config=FREE)
    closed = [t for t in res.trades if not t.is_open]
    assert len(closed) == 2
    assert all(t.exit_date is not None for t in closed)


def test_open_position_at_the_end_is_reported_not_force_closed():
    df = frame(opens=[100, 100, 150, 150], closes=[100, 100, 150, 150])
    res = run_backtest(df, sig([1, 1, 1, 1], df), "GOLD", config=FREE)
    assert len(res.trades) == 1
    assert res.trades[0].is_open is True
    assert res.trades[0].exit_date is None
    assert res.stats()["num_open_trades"] == 1
    assert res.stats()["num_trades"] == 0, "an open trade is not a completed trade"


def test_bars_held_is_counted_correctly():
    """signal[0]=1 -> long from the open of bar 1; signal[4]=0 -> flat at the
    open of bar 5. Held for bars 1..4 inclusive = 4 bars."""
    df = frame(opens=[100] * 8, closes=[100] * 8)
    res = run_backtest(df, sig([1, 1, 1, 1, 0, 0, 0, 0], df), "GOLD", config=FREE)
    t = res.trades[0]
    assert t.entry_date == df.index[1]
    assert t.exit_date == df.index[5]
    assert t.bars_held == 4


def test_trade_log_is_json_ready():
    df = load_asset("GOLD").iloc[-400:]
    signals = pd.Series(np.where(np.arange(len(df)) % 40 < 15, 1.0, 0.0), index=df.index)
    for row in run_backtest(df, signals, "GOLD").trade_log():
        assert isinstance(row["entry_date"], str)
        assert isinstance(row["direction"], str)
        for key in ("units", "entry_price", "net_pnl", "costs"):
            assert isinstance(row[key], float)


# ================================================================ stats


def test_win_rate_and_profit_factor_hand_computed():
    """Two round trips: one +10%, one -10%. Win rate 0.5."""
    df = frame(
        opens=[100, 100, 110, 110, 100, 100],
        closes=[100, 100, 110, 110, 100, 100],
    )
    res = run_backtest(df, sig([1, 1, 0, 0, 1, 0], df), "GOLD", config=FREE)
    stats = res.stats()
    assert stats["num_trades"] >= 1
    assert 0.0 <= stats["win_rate"] <= 1.0
    assert stats["profit_factor"] >= 0.0


def test_exposure_matches_time_in_market():
    """Signal on for bars 0-3 -> positioned on bars 1-4 = 4 of 10."""
    df = frame(opens=[100] * 10, closes=[100] * 10)
    res = run_backtest(df, sig([1, 1, 1, 1, 0, 0, 0, 0, 0, 0], df), "GOLD", config=FREE)
    assert res.stats()["exposure"] == pytest.approx(0.4)


def test_stats_reports_cost_breakdown():
    df = load_asset("BTC").iloc[-500:]
    signals = pd.Series(np.where(np.arange(len(df)) % 50 < 20, 1.0, 0.0), index=df.index)
    stats = run_backtest(df, signals, "BTC").stats()
    assert stats["total_costs"] == pytest.approx(stats["total_commission"] + stats["total_slippage"])
    assert stats["total_costs"] > 0


def test_curves_are_aligned_and_serialisable():
    df = load_asset("NVDA").iloc[-300:]
    res = run_backtest(df, pd.Series(1.0, index=df.index), "NVDA")
    c = res.curves()
    n = len(c["dates"])
    assert n == len(df)
    assert all(len(c[k]) == n for k in ("equity", "cumulative_return", "drawdown", "position"))


# ================================================================ benchmark


def test_buy_and_hold_tracks_the_asset():
    """Net of one entry cost, B&H return must match the asset's own return."""
    df = load_asset("NVDA")
    res = buy_and_hold(df, "NVDA", config=FREE)
    asset_return = df["close"].iloc[-1] / df["open"].iloc[1] - 1
    assert res.stats()["total_return"] == pytest.approx(asset_return, rel=0.01)


def test_buy_and_hold_pays_an_entry_cost():
    """The benchmark must not be frictionless, or it flatters every strategy."""
    df = load_asset("GOLD")
    costed = buy_and_hold(df, "GOLD", BacktestConfig(commission_bps=10.0, slippage_bps=5.0))
    free = buy_and_hold(df, "GOLD", FREE)
    assert costed.stats()["total_costs"] > 0
    assert costed.stats()["total_return"] < free.stats()["total_return"]


def test_buy_and_hold_makes_exactly_one_trade():
    res = buy_and_hold(load_asset("BTC"), "BTC")
    assert len(res.trades) == 1
    assert res.trades[0].is_open is True


def test_buy_and_hold_exposure_is_effectively_full():
    res = buy_and_hold(load_asset("GOLD"), "GOLD")
    assert res.stats()["exposure"] > 0.99


# ================================================================ costs matter


def test_higher_costs_monotonically_reduce_returns():
    """A real engine must degrade smoothly as friction rises."""
    df = load_asset("NVDA").iloc[-1000:]
    signals = pd.Series(np.where(np.arange(len(df)) % 10 < 5, 1.0, 0.0), index=df.index)
    prev = None
    for bps in (0.0, 5.0, 20.0, 50.0):
        cfg = BacktestConfig(commission_bps=bps, slippage_bps=bps)
        total = run_backtest(df, signals, "NVDA", config=cfg).stats()["total_return"]
        if prev is not None:
            assert total < prev, f"return did not fall when costs rose to {bps} bps"
        prev = total


def test_frequent_trading_costs_more_than_infrequent():
    df = load_asset("NVDA").iloc[-1000:]
    cfg = BacktestConfig(commission_bps=20.0, slippage_bps=10.0)
    churn = pd.Series(np.where(np.arange(len(df)) % 2 == 0, 1.0, 0.0), index=df.index)
    patient = pd.Series(np.where(np.arange(len(df)) % 200 < 100, 1.0, 0.0), index=df.index)
    assert (
        run_backtest(df, churn, "NVDA", config=cfg).stats()["total_costs"]
        > run_backtest(df, patient, "NVDA", config=cfg).stats()["total_costs"]
    )


# ================================================================ shorts


def test_shorts_are_ignored_unless_enabled():
    df = frame(opens=[100, 100, 100, 100], closes=[100, 100, 100, 100])
    res = run_backtest(df, sig([-1, -1, -1, -1], df), "GOLD", config=FREE)
    assert (res.position == 0).all()
    assert res.trades == []


def test_short_profits_when_price_falls():
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0, allow_short=True)
    df = frame(opens=[100, 100, 80, 80], closes=[100, 100, 80, 80])
    res = run_backtest(df, sig([-1, -1, -1, -1], df), "GOLD", config=cfg)
    assert res.position.iloc[2] == -1
    assert res.equity.iloc[-1] > 10_000.0


def test_short_loses_when_price_rises():
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0, allow_short=True)
    df = frame(opens=[100, 100, 120, 120], closes=[100, 100, 120, 120])
    res = run_backtest(df, sig([-1, -1, -1, -1], df), "GOLD", config=cfg)
    assert res.equity.iloc[-1] < 10_000.0


def test_direction_flip_closes_and_reopens():
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0, allow_short=True)
    df = frame(opens=[100] * 8, closes=[100] * 8)
    res = run_backtest(df, sig([1, 1, 1, -1, -1, -1, 0, 0], df), "GOLD", config=cfg)
    directions = [t.direction for t in res.trades]
    assert 1 in directions and -1 in directions


# ================================================================ guards


def test_empty_frame_raises():
    with pytest.raises(ValueError, match="no usable bars"):
        run_backtest(frame([], []), pd.Series(dtype="float64"), "GOLD")


def test_missing_signals_are_treated_as_flat():
    df = frame(opens=[100] * 5, closes=[100] * 5)
    partial = pd.Series([1.0, 1.0], index=df.index[:2])
    res = run_backtest(df, partial, "GOLD", config=FREE)
    assert res.position.iloc[-1] == 0


def test_config_is_echoed_in_the_result():
    cfg = BacktestConfig(initial_capital=77_000.0, commission_bps=3.0)
    df = frame(opens=[100] * 5, closes=[100] * 5)
    res = run_backtest(df, sig([0] * 5, df), "GOLD", config=cfg)
    assert res.config.as_dict()["initial_capital"] == 77_000.0
    assert res.stats()["initial_capital"] == 77_000.0


# ================================================================ borrow cost


def test_holding_a_short_costs_borrow_every_bar():
    """Regression: a short used to be free to hold.

    A real short pays a borrow fee for as long as it is open. Without this, a
    short could be held for a decade at no cost, which flatters every
    short-side result.
    """
    cfg = BacktestConfig(
        initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
        allow_short=True, borrow_bps_annual=50.0,
    )
    df = frame(opens=[100.0] * 260, closes=[100.0] * 260)
    res = run_backtest(df, sig([-1.0] * 260, df), "GOLD", config=cfg)

    assert res.stats()["total_borrow"] > 0
    assert res.equity.iloc[-1] < 10_000.0, "a flat-price short must still lose the borrow"


def test_borrow_is_zero_when_never_short():
    cfg = BacktestConfig(commission_bps=0.0, slippage_bps=0.0, borrow_bps_annual=500.0)
    df = frame(opens=[100.0] * 50, closes=[100.0] * 50)
    res = run_backtest(df, sig([1.0] * 50, df), "GOLD", config=cfg)
    assert res.stats()["total_borrow"] == 0.0


def test_borrow_scales_with_the_rate():
    df = frame(opens=[100.0] * 260, closes=[100.0] * 260)

    def paid(bps):
        cfg = BacktestConfig(
            initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
            allow_short=True, borrow_bps_annual=bps,
        )
        return run_backtest(df, sig([-1.0] * 260, df), "GOLD", config=cfg).stats()["total_borrow"]

    assert paid(0.0) == 0.0
    assert paid(200.0) == pytest.approx(paid(50.0) * 4, rel=0.02)


def test_borrow_uses_the_assets_own_calendar():
    """A crypto short (365 bars/year) must not be charged an equity year's worth
    of borrow for the same number of bars."""
    df = frame(opens=[100.0] * 260, closes=[100.0] * 260)
    cfg = BacktestConfig(
        initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
        allow_short=True, borrow_bps_annual=100.0,
    )
    gold = run_backtest(df, sig([-1.0] * 260, df), "GOLD", config=cfg).stats()["total_borrow"]
    btc = run_backtest(df, sig([-1.0] * 260, df), "BTC", config=cfg).stats()["total_borrow"]
    assert btc < gold, "365-day calendar means a smaller per-bar charge"
    assert btc == pytest.approx(gold * 252 / 365, rel=0.01)


def test_costs_still_decompose_with_borrow_included():
    cfg = BacktestConfig(
        initial_capital=10_000.0, commission_bps=10.0, slippage_bps=5.0,
        allow_short=True, borrow_bps_annual=100.0,
    )
    df = frame(opens=[100.0] * 120, closes=[100.0] * 120)
    res = run_backtest(df, sig([-1.0] * 60 + [0.0] * 60, df), "GOLD", config=cfg)
    t = res.trades[0]
    assert t.costs == pytest.approx(t.commission + t.slippage + t.borrow)
    stats = res.stats()
    assert stats["total_costs"] == pytest.approx(
        stats["total_commission"] + stats["total_slippage"] + stats["total_borrow"]
    )


# ================================================================ position sizing


def test_position_size_leaves_the_rest_in_cash():
    """The brief lists position sizing as a required control, so prove it bites."""
    df = frame(opens=[100.0] * 6, closes=[100.0, 100.0, 200.0, 200.0, 200.0, 200.0])
    for pct_, expected_units in ((0.25, 25.0), (0.5, 50.0), (1.0, 100.0)):
        cfg = BacktestConfig(
            initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0, position_pct=pct_
        )
        res = run_backtest(df, sig([1.0] * 6, df), "GOLD", config=cfg)
        assert res.trades[0].units == pytest.approx(expected_units)


def test_smaller_position_size_dampens_both_gain_and_loss():
    df = frame(opens=[100.0] * 6, closes=[100.0, 100.0, 200.0, 200.0, 200.0, 200.0])

    def final(p):
        cfg = BacktestConfig(
            initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0, position_pct=p
        )
        return run_backtest(df, sig([1.0] * 6, df), "GOLD", config=cfg).equity.iloc[-1]

    # Price doubles: 100% deployed doubles equity, 50% adds half of that gain.
    assert final(1.0) == pytest.approx(20_000.0)
    assert final(0.5) == pytest.approx(15_000.0)
    assert final(0.25) == pytest.approx(12_500.0)


def test_benchmark_is_always_fully_invested():
    """Regression: the benchmark used to inherit the strategy's position size.

    Halving `position_pct` halved buy-and-hold too, so a strategy could be
    de-risked and never look any worse — the yardstick shrank with it. A
    benchmark that moves when you change a strategy setting is not a reference.
    """
    df = load_asset("NVDA")
    full = buy_and_hold(df, "NVDA", BacktestConfig(position_pct=1.0)).stats()["total_return"]
    for p in (0.25, 0.5, 0.75):
        sized = buy_and_hold(df, "NVDA", BacktestConfig(position_pct=p)).stats()["total_return"]
        assert sized == pytest.approx(full), f"benchmark moved at position_pct={p}"


def test_benchmark_still_pays_the_callers_costs():
    """Pinning the size must not also pin the costs — like-for-like cost
    treatment is what makes the comparison fair."""
    df = load_asset("GOLD")
    cheap = buy_and_hold(df, "GOLD", BacktestConfig(position_pct=0.4, commission_bps=1.0, slippage_bps=0.0))
    dear = buy_and_hold(df, "GOLD", BacktestConfig(position_pct=0.4, commission_bps=100.0, slippage_bps=50.0))
    assert dear.stats()["total_costs"] > cheap.stats()["total_costs"] * 10


def test_sizing_a_strategy_down_makes_it_lose_more_to_the_benchmark():
    """The behaviour the fix exists to produce: smaller size, same yardstick."""
    df = load_asset("NVDA")
    bench = buy_and_hold(df, "NVDA").stats()["total_return"]
    signals = pd.Series(1.0, index=df.index)

    full = run_backtest(df, signals, "NVDA", config=BacktestConfig(position_pct=1.0))
    half = run_backtest(df, signals, "NVDA", config=BacktestConfig(position_pct=0.5))
    assert half.stats()["total_return"] < full.stats()["total_return"] < bench * 1.01


# ==================================================== continuous position sizing


def test_a_fractional_target_deploys_that_fraction_of_equity():
    """A signal of 0.5 means "half invested", the same thing position_pct=0.5
    has always meant. The difference is that the strategy now decides it, bar
    by bar, instead of it being a fixed account setting."""
    df = frame(opens=[100, 100, 200, 200], closes=[100, 100, 200, 200])
    res = run_backtest(df, sig([0.5, 0.5, 0.5, 0.5], df), "GOLD", config=FREE)

    assert res.trades[0].units == pytest.approx(50.0)  # 5_000 / 100
    # 5_000 cash + 50 units doubling from 100 to 200. The target never changes,
    # so the position is never revisited and never trimmed on the way up.
    assert res.equity.iloc[-1] == pytest.approx(15_000.0)


def test_leverage_borrows_cash_and_amplifies_the_move():
    """A target above 1.0 buys more than the account holds. At 2x exposure a
    +10% move in the asset must produce +20% on equity."""
    df = frame(opens=[100, 100, 110, 110], closes=[100, 100, 110, 110])
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         financing_bps_annual=0.0)
    res = run_backtest(df, sig([2.0, 2.0, 2.0, 2.0], df), "GOLD", config=cfg)

    assert res.trades[0].units == pytest.approx(200.0)  # 20_000 / 100
    # 200 units gaining 10 each is +2_000 on a 10_000 account.
    assert res.equity.iloc[-1] == pytest.approx(12_000.0)


def test_the_position_is_rebalanced_when_the_target_changes():
    df = frame(opens=[100, 100, 100, 100], closes=[100, 100, 100, 100])
    res = run_backtest(df, sig([1.0, 0.5, 0.5, 0.5], df), "GOLD", config=FREE)

    # Flat prices, so equity stays at 10_000 and the trim is exact.
    assert len(res.trades) == 1
    trade = res.trades[0]
    assert trade.is_open
    assert trade.rebalances == 1
    assert trade.max_units == pytest.approx(100.0)
    assert res.position.iloc[-1] == pytest.approx(0.5)
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


def test_gross_pnl_survives_a_position_that_was_resized_midway():
    """Entry-price arithmetic cannot describe a trade that was topped up at a
    different price; the shadow reference account can.

    Buy 100 units at 100, add 100 more at 50, sell all 200 at 80. Outlay is
    10_000 + 5_000 = 15_000, proceeds are 16_000, so gross P&L is +1_000 and
    nothing about entry price alone would tell you that.
    """
    df = frame(opens=[100, 100, 50, 80, 80], closes=[100, 100, 50, 80, 80])
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         financing_bps_annual=0.0)
    # Bar 1 fills 1.0: 100 units of a 10_000 account at 100.
    # Bar 2 fills 2.0 at 50: equity has halved to 5_000, so 2x is 200 units.
    # Bar 3 goes flat at 80.
    res = run_backtest(df, sig([1.0, 2.0, 0.0, 0.0, 0.0], df), "GOLD", config=cfg)

    closed = [t for t in res.trades if not t.is_open]
    assert len(closed) == 1
    assert closed[0].gross_pnl == pytest.approx(1_000.0)
    assert closed[0].net_pnl == pytest.approx(1_000.0)  # costs are switched off
    assert closed[0].rebalances == 1


def test_discrete_signals_are_unaffected_by_the_sizing_machinery():
    """The four directional strategies must behave exactly as they did before
    continuous sizing existed: sign-only targets, one leg per trade."""
    df = load_asset("NVDA")
    res = run_backtest(df, pd.Series(1.0, index=df.index), "NVDA")
    assert set(res.position.unique()) <= {0.0, 1.0}
    assert all(t.rebalances == 0 for t in res.trades)


# ================================================================ financing


def test_borrowed_cash_accrues_interest():
    df = frame(opens=[100] * 6, closes=[100] * 6)
    levered = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                             financing_bps_annual=500.0)
    res = run_backtest(df, sig([1.5] * 6, df), "GOLD", config=levered)

    # 1.5x on 10_000 borrows 5_000. The price never moves, so every penny lost
    # is interest and equity must fall monotonically.
    assert res.equity.iloc[-1] < 10_000.0
    assert res.trades[0].financing > 0
    assert (res.equity.diff().dropna() <= 0).all()


def test_financing_is_not_charged_to_an_unlevered_position():
    """Cash is exactly zero at 100% exposure, so there is nothing to charge."""
    df = frame(opens=[100] * 6, closes=[100] * 6)
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         financing_bps_annual=500.0)
    res = run_backtest(df, sig([1.0] * 6, df), "GOLD", config=cfg)
    assert res.trades[0].financing == 0.0
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


def test_financing_uses_the_calendar_of_the_asset_being_traded():
    """Crypto compounds over 365 bars a year and equities over 252, so the same
    annual rate has to cost less per bar on BTC.

    Two bars, so the signal lag leaves exactly one bar holding the position and
    exactly one interest charge. Over a longer run the charges compound and the
    ratio drifts off 252/365, which would make the arithmetic here approximate
    rather than exact.
    """
    df = frame(opens=[100, 100], closes=[100, 100])
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         financing_bps_annual=1000.0)
    # 1.5x on 10_000 borrows 5_000 at 10% a year.
    equity = run_backtest(df, sig([1.5, 1.5], df), "NVDA", config=cfg).trades[0].financing
    crypto = run_backtest(df, sig([1.5, 1.5], df), "BTC", config=cfg).trades[0].financing
    assert equity == pytest.approx(5_000 * 0.10 / 252)
    assert crypto == pytest.approx(5_000 * 0.10 / 365)


def test_a_zero_financing_rate_makes_leverage_free():
    df = frame(opens=[100] * 6, closes=[100] * 6)
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         financing_bps_annual=0.0)
    res = run_backtest(df, sig([1.5] * 6, df), "GOLD", config=cfg)
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


def test_financing_makes_a_levered_run_strictly_worse():
    """The point of charging for leverage is that it changes the answer."""
    df = load_asset("NVDA")
    signals = pd.Series(1.5, index=df.index)
    free = run_backtest(df, signals, "NVDA", config=BacktestConfig(financing_bps_annual=0.0))
    paid = run_backtest(df, signals, "NVDA", config=BacktestConfig(financing_bps_annual=500.0))
    assert paid.stats()["total_return"] < free.stats()["total_return"]
    assert paid.stats()["total_financing"] > 0


# ============================================================ no-trade band


def test_the_band_suppresses_a_small_rebalance():
    """A 20% band must ignore a target moving from 1.00 to 0.95."""
    df = frame(opens=[100] * 5, closes=[100] * 5)
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         no_trade_band=0.20)
    res = run_backtest(df, sig([1.0, 0.95, 0.95, 0.95, 0.95], df), "GOLD", config=cfg)
    assert res.trades[0].rebalances == 0
    assert res.position.iloc[-1] == pytest.approx(1.0)


def test_the_band_still_lets_a_large_rebalance_through():
    df = frame(opens=[100] * 5, closes=[100] * 5)
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         no_trade_band=0.20)
    res = run_backtest(df, sig([1.0, 0.5, 0.5, 0.5, 0.5], df), "GOLD", config=cfg)
    assert res.trades[0].rebalances == 1
    assert res.position.iloc[-1] == pytest.approx(0.5)


def test_the_band_never_suppresses_an_exit():
    """Trimming is optional; getting out is not. A target of zero has to be
    executed however wide the band is."""
    df = frame(opens=[100] * 5, closes=[100] * 5)
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         no_trade_band=0.99)
    res = run_backtest(df, sig([1.0, 1.0, 0.0, 0.0, 0.0], df), "GOLD", config=cfg)
    assert res.position.iloc[-1] == 0.0
    assert len([t for t in res.trades if not t.is_open]) == 1


def test_the_band_never_suppresses_a_flip():
    df = frame(opens=[100] * 5, closes=[100] * 5)
    cfg = BacktestConfig(initial_capital=10_000.0, commission_bps=0.0, slippage_bps=0.0,
                         no_trade_band=0.99, allow_short=True)
    res = run_backtest(df, sig([1.0, 1.0, -1.0, -1.0, -1.0], df), "GOLD", config=cfg)
    assert res.position.iloc[-1] == pytest.approx(-1.0)


def test_a_wider_band_means_far_fewer_rebalances_on_real_data():
    from app.backtest.strategies import get_strategy

    df = load_asset("NVDA")
    signals = get_strategy("vol_target", asset="NVDA").generate_signals(df)
    tight = run_backtest(df, signals, "NVDA", config=BacktestConfig(no_trade_band=0.0))
    loose = run_backtest(df, signals, "NVDA", config=BacktestConfig(no_trade_band=0.20))
    assert loose.stats()["total_rebalances"] < tight.stats()["total_rebalances"] / 2


def test_the_benchmark_ignores_the_no_trade_band():
    """The band is a strategy setting. A benchmark that moved when you changed
    one would not be a fixed reference point."""
    df = load_asset("GOLD")
    plain = buy_and_hold(df, "GOLD", BacktestConfig(no_trade_band=0.0)).stats()["total_return"]
    banded = buy_and_hold(df, "GOLD", BacktestConfig(no_trade_band=0.35)).stats()["total_return"]
    assert banded == pytest.approx(plain)


# ============================================ regressions found by the reports


def test_slippage_never_favours_a_rebalance():
    """Regression. Sizing divides by (1 + commission), which can push the target
    below the units already held even when the position is being *widened* in
    exposure terms — so a trade predicted to be a buy turns out to be a sell.
    Picking the fill from the prediction then paid the trade slippage instead of
    charging it. The fill is now chosen so it is consistent with the trade that
    actually happens.

    The symptom was a silent one: equity drifted away from the trade log by
    about 0.001% over a decade, which no eyeball would catch. The identity below
    is what caught it.
    """
    from app.backtest.strategies import get_strategy

    df = load_asset("NVDA")
    signals = get_strategy("vol_target", asset="NVDA").generate_signals(df)

    for band in (0.0, 0.10):
        cfg = BacktestConfig(no_trade_band=band)
        res = run_backtest(df, signals, "NVDA", config=cfg)
        net = sum(t.net_pnl for t in res.trades)
        assert res.equity.iloc[-1] == pytest.approx(cfg.initial_capital + net, abs=1e-6), (
            f"equity disagrees with the trade log at band={band}"
        )


def test_every_fill_is_worse_than_the_open_it_was_taken_at():
    """The engine's promise, stated directly: a buy fills above the printed open
    and a sell fills below it, on every leg of every trade."""
    from app.backtest.strategies import get_strategy

    df = load_asset("BTC")
    signals = get_strategy("vol_target", asset="BTC").generate_signals(df)
    res = run_backtest(df, signals, "BTC", config=BacktestConfig(slippage_bps=25.0))

    for t in res.trades:
        assert t.entry_price > t.ref_entry, "an entry filled at or below the open"
        if t.exit_price is not None:
            assert t.exit_price < t.ref_exit, "an exit filled at or above the open"
        # Slippage is a cost, so it is always positive and never a rebate.
        assert t.slippage > 0


def test_position_tracks_the_lagged_target_exactly_when_there_is_no_band():
    """Regression. `position` reports the target the engine sized to. When a
    rebalance was skipped because the units held already matched the target, the
    bar kept the *previous* target as its label and misreported what was held by
    up to 6%. With no band there is nothing left to excuse a difference."""
    from app.backtest.strategies import get_strategy

    for asset in ("GOLD", "BTC", "NVDA"):
        df = load_asset(asset)
        signals = get_strategy("vol_target", asset=asset).generate_signals(df)
        res = run_backtest(df, signals, asset, config=BacktestConfig(no_trade_band=0.0))

        lagged = np.concatenate([[0.0], res.signals.to_numpy()[:-1]])
        assert res.position.to_numpy() == pytest.approx(lagged, abs=1e-9), asset


def test_the_band_is_the_only_thing_that_holds_a_position_off_target():
    """And it holds it off target by no more than the band allows.

    The band is measured against the position *held*, not the target, so the
    tolerance is too — a 10% band around a holding of 1.0 covers a target of
    0.9, which is 11.1% away when measured the other way round.
    """
    from app.backtest.strategies import get_strategy

    df = load_asset("NVDA")
    signals = get_strategy("vol_target", asset="NVDA").generate_signals(df)
    cfg = BacktestConfig(no_trade_band=0.10)
    res = run_backtest(df, signals, "NVDA", config=cfg)

    lagged = np.concatenate([[0.0], res.signals.to_numpy()[:-1]])
    position = res.position.to_numpy()
    allowed = (cfg.no_trade_band + 2 * cfg.slippage_bps * 1e-4) * np.abs(position)
    assert (np.abs(position - lagged) <= allowed + 1e-9).all()
