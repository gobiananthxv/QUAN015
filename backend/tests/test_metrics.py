"""Risk and performance metric correctness, against closed-form cases."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.metrics import (
    cagr,
    calmar_ratio,
    cumulative_returns,
    daily_returns,
    drawdown_series,
    max_drawdown,
    max_drawdown_duration,
    rolling_returns,
    rolling_volatility,
    sharpe_ratio,
    sortino_ratio,
    summarise,
    total_return,
    volatility,
)


# ---------------------------------------------------------------- returns


def test_daily_returns_hand_computed():
    prices = pd.Series([100.0, 110.0, 99.0])
    out = daily_returns(prices)
    assert out.iloc[0] == pytest.approx(0.10)
    assert out.iloc[1] == pytest.approx(-0.10)
    assert len(out) == 2, "the first bar has no prior close and must be dropped"


def test_total_return_compounds_not_sums():
    """+10% then +10% is +21%, not +20%. Getting this wrong is a classic."""
    assert total_return(pd.Series([0.1, 0.1])) == pytest.approx(0.21)


def test_total_return_of_offsetting_moves_is_negative():
    """+50% then -50% loses money."""
    assert total_return(pd.Series([0.5, -0.5])) == pytest.approx(-0.25)


def test_cumulative_returns_path():
    out = cumulative_returns(pd.Series([0.1, 0.1]))
    assert out.iloc[0] == pytest.approx(0.10)
    assert out.iloc[1] == pytest.approx(0.21)


def test_total_return_of_empty_is_zero():
    assert total_return(pd.Series([], dtype="float64")) == 0.0


def test_rolling_returns_hand_computed():
    prices = pd.Series([100.0, 105.0, 110.0, 121.0])
    assert rolling_returns(prices, 2).iloc[2] == pytest.approx(0.10)  # 110/100
    assert rolling_returns(prices, 2).iloc[3] == pytest.approx(121 / 105 - 1)


# ---------------------------------------------------------------- CAGR


def test_cagr_doubling_in_exactly_one_year_is_100pct():
    r = 2 ** (1 / 252) - 1
    returns = pd.Series([r] * 252)
    assert cagr(returns, 252) == pytest.approx(1.0)


def test_cagr_doubling_in_two_years_is_sqrt2_minus_1():
    r = 2 ** (1 / 504) - 1
    returns = pd.Series([r] * 504)
    assert cagr(returns, 252) == pytest.approx(np.sqrt(2) - 1)


def test_cagr_of_flat_series_is_zero():
    assert cagr(pd.Series([0.0] * 252), 252) == pytest.approx(0.0)


def test_cagr_survives_total_wipeout():
    """A -100% bar makes growth zero; must return 0.0, not raise or produce nan."""
    assert cagr(pd.Series([0.1, -1.0, 0.1]), 252) == 0.0


# ---------------------------------------------------------------- volatility


def test_volatility_annualises_by_sqrt_time():
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0, 0.01, 1000))
    daily = volatility(returns, 252, annualise=False)
    annual = volatility(returns, 252, annualise=True)
    assert annual == pytest.approx(daily * np.sqrt(252))


def test_volatility_of_constant_returns_is_zero():
    assert volatility(pd.Series([0.01] * 100), 252) == pytest.approx(0.0)


def test_annualisation_factor_is_respected():
    """The crypto-vs-equity distinction. Same returns, different calendars."""
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0, 0.02, 500))
    crypto = volatility(returns, 365)
    equity = volatility(returns, 252)
    assert crypto > equity
    assert crypto / equity == pytest.approx(np.sqrt(365 / 252))


def test_rolling_volatility_warmup_and_length(noisy):
    rv = rolling_volatility(daily_returns(noisy), 30, 252)
    assert rv.iloc[:29].isna().all()
    assert rv.dropna().gt(0).all()


# ---------------------------------------------------------------- Sharpe


def test_sharpe_hand_computed_with_zero_risk_free():
    """mean/std * sqrt(ann) with rf=0."""
    returns = pd.Series([0.01, -0.005, 0.02, 0.0, -0.01])
    expected = returns.mean() / returns.std(ddof=1) * np.sqrt(252)
    assert sharpe_ratio(returns, 252, rf=0.0) == pytest.approx(expected)


def test_sharpe_of_zero_volatility_is_zero():
    """Constant returns give zero denominator; must not divide by zero."""
    assert sharpe_ratio(pd.Series([0.01] * 100), 252) == 0.0


def test_sharpe_penalises_the_risk_free_rate():
    returns = pd.Series([0.0005] * 200 + [-0.0002] * 100)
    assert sharpe_ratio(returns, 252, rf=0.0) > sharpe_ratio(returns, 252, rf=0.05)


def test_sharpe_is_negative_for_losing_series():
    rng = np.random.default_rng(3)
    assert sharpe_ratio(pd.Series(rng.normal(-0.001, 0.01, 500)), 252, rf=0.0) < 0


# ---------------------------------------------------------------- Sortino


def test_sortino_exceeds_sharpe_when_downside_is_mild():
    """Upside vol is not punished by Sortino, so it should read higher here."""
    returns = pd.Series([0.05, 0.04, -0.001, 0.06, -0.002] * 40)
    assert sortino_ratio(returns, 252, rf=0.0) > sharpe_ratio(returns, 252, rf=0.0)


def test_sortino_with_no_losing_days_is_infinite():
    """Regression: returned 0.0 before the Phase 2 audit, which reads as
    'no risk-adjusted return' — the opposite of the truth."""
    assert sortino_ratio(pd.Series([0.01] * 100), 252, rf=0.0) == float("inf")


def test_sortino_is_negative_when_everything_loses():
    out = sortino_ratio(pd.Series([-0.01] * 100), 252, rf=0.0)
    assert out < 0 and np.isfinite(out)


# ---------------------------------------------------------------- drawdown


HAND_PATH = pd.Series([0.5, -0.5, 0.2])
# equity 1.5 -> 0.75 -> 0.90 ; running peak 1.5 ; dd 0 -> -0.50 -> -0.40


def test_drawdown_series_hand_computed():
    dd = drawdown_series(HAND_PATH)
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(-0.5)
    assert dd.iloc[2] == pytest.approx(-0.4)


def test_max_drawdown_hand_computed():
    assert max_drawdown(HAND_PATH) == pytest.approx(-0.5)


def test_max_drawdown_duration_hand_computed():
    """Bars 1 and 2 are below the peak -> longest underwater run is 2."""
    assert max_drawdown_duration(HAND_PATH) == 2


def test_max_drawdown_of_monotonic_gains_is_zero():
    assert max_drawdown(pd.Series([0.01] * 50)) == pytest.approx(0.0)
    assert max_drawdown_duration(pd.Series([0.01] * 50)) == 0


def test_drawdown_is_never_positive(noisy):
    assert drawdown_series(daily_returns(noisy)).le(1e-12).all()


def test_max_drawdown_of_empty_is_zero():
    assert max_drawdown(pd.Series([], dtype="float64")) == 0.0


# ---------------------------------------------------------------- Calmar


def test_calmar_is_cagr_over_max_drawdown(noisy):
    returns = daily_returns(noisy)
    expected = cagr(returns, 252) / abs(max_drawdown(returns))
    assert calmar_ratio(returns, 252) == pytest.approx(expected)


def test_calmar_with_no_drawdown_is_zero_not_inf():
    """Guarded division: no drawdown means the ratio is undefined."""
    assert calmar_ratio(pd.Series([0.01] * 50), 252) == 0.0


# ---------------------------------------------------------------- summarise


def test_summarise_emits_every_required_field(noisy):
    out = summarise(daily_returns(noisy), 252)
    required = [
        "total_return", "cagr", "volatility", "sharpe", "sortino", "calmar",
        "max_drawdown", "max_drawdown_duration", "best_day", "worst_day",
        "positive_days",
    ]
    missing = [k for k in required if k not in out]
    assert not missing, f"summarise missing: {missing}"


def test_summarise_values_are_internally_consistent(noisy):
    returns = daily_returns(noisy)
    out = summarise(returns, 252)
    assert out["total_return"] == pytest.approx(total_return(returns))
    assert out["max_drawdown"] == pytest.approx(max_drawdown(returns))
    assert out["best_day"] >= out["worst_day"]
    assert 0.0 <= out["positive_days"] <= 1.0


def test_summarise_handles_empty_input():
    out = summarise(pd.Series([], dtype="float64"), 252)
    assert all(v == 0.0 for v in out.values())
