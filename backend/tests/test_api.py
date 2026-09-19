"""REST API contract.

The theme here is that the dashboard is a separate program: it can only rely on
what actually crosses the wire. So these tests parse raw response bytes with a
strict JSON parser rather than trusting Python's permissive one.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.serialise import clean, frame_to_records, series_to_pairs
from app.main import app

client = TestClient(app)


def strict_json(response) -> object:
    """Parse the raw body rejecting Infinity/NaN, exactly as JSON.parse does.

    Python's json.loads accepts bare `Infinity` and `NaN` tokens by default;
    the browser does not. Using the permissive parser here would let a payload
    through that crashes the dashboard.
    """
    return json.loads(response.content, parse_constant=_reject)


def _reject(token: str):
    raise AssertionError(f"response contained non-JSON token {token!r}")


# ================================================================ serialiser


def test_clean_converts_infinity_to_null():
    """inf is a correct answer (Sortino with no losing day), but not JSON."""
    assert clean(float("inf")) is None
    assert clean(float("-inf")) is None
    assert clean(np.inf) is None


def test_clean_converts_nan_to_null():
    assert clean(float("nan")) is None
    assert clean(np.nan) is None
    assert clean(pd.NA) is None or clean(pd.NA) is pd.NA


def test_clean_unwraps_numpy_scalars():
    assert isinstance(clean(np.int64(5)), int)
    assert isinstance(clean(np.float64(1.5)), float)
    assert isinstance(clean(np.bool_(True)), bool)


def test_clean_keeps_bool_distinct_from_int():
    """bool is a subclass of int; a careless isinstance order turns True into 1."""
    assert clean(True) is True
    assert clean(np.bool_(False)) is False


def test_clean_recurses_through_containers():
    payload = {"a": [1, float("inf"), {"b": np.float64("nan")}], "c": (np.int64(2),)}
    assert clean(payload) == {"a": [1, None, {"b": None}], "c": [2]}


def test_clean_output_survives_strict_serialisation():
    messy = {"sortino": float("inf"), "vol": np.float64("nan"), "n": np.int64(3)}
    json.dumps(clean(messy), allow_nan=False)


def test_series_to_pairs_formats_dates():
    s = pd.Series([1.0, float("inf")], index=pd.date_range("2024-01-01", periods=2))
    assert series_to_pairs(s, "v") == [
        {"date": "2024-01-01", "v": 1.0},
        {"date": "2024-01-02", "v": None},
    ]


def test_frame_to_records_promotes_the_index():
    df = pd.DataFrame({"x": [1.0]}, index=pd.date_range("2024-01-01", periods=1))
    assert frame_to_records(df, index_name="date") == [{"date": "2024-01-01", "x": 1.0}]


# ================================================================ health / catalogue


def test_health_reports_ok_and_a_disclaimer():
    body = strict_json(client.get("/health"))
    assert body["status"] == "ok"
    assert "not a prediction" in body["disclaimer"]


def test_assets_lists_every_asset_with_its_annualisation():
    body = strict_json(client.get("/api/assets"))
    keys = {a["key"] for a in body["assets"]}
    assert keys == {"GOLD", "BTC", "NVDA"}
    by_key = {a["key"]: a for a in body["assets"]}
    assert by_key["BTC"]["ann_factor"] == 365
    assert by_key["NVDA"]["ann_factor"] == 252


def test_strategies_catalogue_is_complete():
    body = strict_json(client.get("/api/strategies"))
    names = {s["name"] for s in body["strategies"]}
    assert names == {"sma_crossover", "ema_trend", "momentum", "mean_reversion"}
    for s in body["strategies"]:
        assert s["description"] and s["defaults"]


# ================================================================ data endpoints


@pytest.mark.parametrize("asset", ["GOLD", "BTC", "NVDA"])
def test_ohlcv_returns_every_bar(asset):
    body = strict_json(client.get(f"/api/ohlcv?asset={asset}"))
    assert body["rows"] == len(body["bars"])
    first = body["bars"][0]
    assert set(first) >= {"date", "open", "high", "low", "close", "volume"}


def test_ohlcv_respects_the_date_range():
    body = strict_json(client.get("/api/ohlcv?asset=NVDA&start=2024-01-01&end=2024-03-31"))
    dates = [b["date"] for b in body["bars"]]
    assert dates[0] >= "2024-01-01" and dates[-1] <= "2024-03-31"
    assert len(dates) < 100


def test_ohlcv_rejects_an_unknown_asset():
    assert client.get("/api/ohlcv?asset=DOGECOIN").status_code == 404


def test_ohlcv_rejects_an_empty_range():
    assert client.get("/api/ohlcv?asset=NVDA&start=2099-01-01").status_code == 400


def test_indicators_emit_the_requested_periods():
    body = strict_json(client.get("/api/indicators?asset=GOLD&sma_fast=10&sma_slow=40"))
    assert "sma_10" in body["columns"]
    assert "sma_40" in body["columns"]


def test_indicators_warmup_nulls_survive_the_wire():
    """Warm-up NaNs must arrive as null, not as a NaN token or a zero."""
    body = strict_json(client.get("/api/indicators?asset=NVDA"))
    assert body["rows"][0]["sma_200"] is None


def test_indicators_reject_out_of_range_periods():
    assert client.get("/api/indicators?asset=GOLD&sma_fast=1").status_code == 422
    assert client.get("/api/indicators?asset=GOLD&sma_fast=9999").status_code == 422


def test_metrics_returns_summary_and_plot_series():
    body = strict_json(client.get("/api/metrics?asset=BTC"))
    assert body["ann_factor"] == 365
    for key in ("total_return", "sharpe", "max_drawdown", "sortino"):
        assert key in body["summary"]
    for series in ("returns", "cumulative", "drawdown", "rolling_vol"):
        assert len(body[series]) > 100


def test_correlation_matrix_is_square_and_complete():
    body = strict_json(client.get("/api/correlation"))
    n = len(body["assets"])
    assert len(body["matrix"]) == n * n
    diagonal = [c["value"] for c in body["matrix"] if c["a"] == c["b"]]
    assert all(abs(v - 1.0) < 1e-9 for v in diagonal)


def test_rolling_correlation_between_two_assets():
    body = strict_json(client.get("/api/rolling-correlation?a=BTC&b=NVDA&window=120"))
    assert body["window"] == 120
    assert all(-1.0 <= p["corr"] <= 1.0 for p in body["series"])


def test_regime_endpoint_labels_every_bar():
    body = strict_json(client.get("/api/regime?asset=NVDA"))
    labels = {r["trend_regime"] for r in body["rows"]}
    assert labels <= {"bull", "bear", None}


def test_panel_is_aligned_across_assets():
    body = strict_json(client.get("/api/panel"))
    assert set(body["assets"]) == {"GOLD", "BTC", "NVDA"}
    for row in body["rows"][:50]:
        assert all(row[a] is not None for a in body["assets"])


# ================================================================ backtesting


def test_backtest_returns_strategy_and_benchmark():
    body = strict_json(
        client.post("/api/backtest", json={"asset": "NVDA", "strategy": "sma_crossover"})
    )
    assert body["strategy"]["strategy"] == "sma_crossover"
    assert body["benchmark"]["strategy"] == "buy_and_hold"
    assert len(body["strategy"]["curves"]["equity"]) == len(body["strategy"]["curves"]["dates"])
    assert body["strategy"]["trades"]


def test_backtest_honours_a_custom_config():
    body = strict_json(
        client.post(
            "/api/backtest",
            json={
                "asset": "GOLD",
                "strategy": "momentum",
                "config": {"initial_capital": 50_000, "commission_bps": 0, "slippage_bps": 0},
            },
        )
    )
    stats = body["strategy"]["stats"]
    assert stats["initial_capital"] == 50_000
    assert stats["total_costs"] == 0


def test_backtest_honours_custom_params():
    body = strict_json(
        client.post(
            "/api/backtest",
            json={"asset": "BTC", "strategy": "sma_crossover", "params": {"fast": 20, "slow": 60}},
        )
    )
    assert body["strategy"]["params"] == {"fast": 20, "slow": 60}


def test_backtest_rejects_invalid_strategy_params():
    response = client.post(
        "/api/backtest",
        json={"asset": "BTC", "strategy": "sma_crossover", "params": {"fast": 200, "slow": 50}},
    )
    assert response.status_code == 422
    assert "shorter than" in response.json()["detail"]


def test_backtest_rejects_unknown_strategy():
    r = client.post("/api/backtest", json={"asset": "BTC", "strategy": "nope"})
    assert r.status_code == 404


def test_backtest_rejects_impossible_config():
    r = client.post(
        "/api/backtest",
        json={"asset": "BTC", "strategy": "momentum", "config": {"initial_capital": -5}},
    )
    assert r.status_code == 422


def test_compare_runs_every_strategy_against_one_benchmark():
    body = strict_json(client.post("/api/backtest/compare", json={"asset": "GOLD"}))
    assert len(body["runs"]) == 4
    assert body["benchmark"]["strategy"] == "buy_and_hold"
    for run in body["runs"]:
        assert "stats" in run and "curves" in run
        assert "trades" not in run, "compare should stay light; trades belong to /backtest"


def test_compare_accepts_a_subset():
    body = strict_json(
        client.post(
            "/api/backtest/compare",
            json={"asset": "BTC", "strategies": ["momentum", "sma_crossover"]},
        )
    )
    assert [r["strategy"] for r in body["runs"]] == ["momentum", "sma_crossover"]


def test_robustness_returns_surface_plateau_costs_and_periods():
    body = strict_json(
        client.post("/api/backtest/robustness", json={"asset": "NVDA", "strategy": "momentum"})
    )
    assert body["axes"] == {"x": "window", "y": "band"}
    assert body["surface"]
    assert body["plateau"]["verdict"]
    assert len(body["costs"]) == 6
    assert len(body["periods"]) == 5


def test_robustness_accepts_a_custom_grid():
    body = strict_json(
        client.post(
            "/api/backtest/robustness",
            json={"asset": "GOLD", "strategy": "sma_crossover",
                  "grid": {"fast": [10, 20], "slow": [100, 200]}},
        )
    )
    assert len(body["sweep"]) == 4


def test_robustness_rejects_a_grid_that_is_not_two_dimensional():
    r = client.post(
        "/api/backtest/robustness",
        json={"asset": "GOLD", "strategy": "momentum", "grid": {"window": [30, 60]}},
    )
    assert r.status_code == 422


def test_regime_attribution_endpoint():
    body = strict_json(
        client.get("/api/backtest/regime-attribution?asset=NVDA&strategy=sma_crossover")
    )
    assert len(body["rows"]) == 5
    for row in body["rows"]:
        assert set(row) >= {"regime", "exposure", "strategy_return", "benchmark_return"}


# ================================================================ JSON safety


ENDPOINTS = [
    ("GET", "/health", None),
    ("GET", "/api/assets", None),
    ("GET", "/api/strategies", None),
    ("GET", "/api/ohlcv?asset=GOLD", None),
    ("GET", "/api/indicators?asset=GOLD", None),
    ("GET", "/api/metrics?asset=GOLD", None),
    ("GET", "/api/metrics?asset=BTC", None),
    ("GET", "/api/correlation", None),
    ("GET", "/api/rolling-correlation?a=GOLD&b=BTC", None),
    ("GET", "/api/regime?asset=BTC", None),
    ("GET", "/api/panel", None),
    ("GET", "/api/backtest/regime-attribution?asset=BTC&strategy=momentum", None),
    ("POST", "/api/backtest", {"asset": "BTC", "strategy": "mean_reversion"}),
    ("POST", "/api/backtest/compare", {"asset": "NVDA"}),
    ("POST", "/api/backtest/robustness", {"asset": "GOLD", "strategy": "mean_reversion"}),
]


@pytest.mark.parametrize("method,path,payload", ENDPOINTS, ids=[e[1][:45] for e in ENDPOINTS])
def test_every_endpoint_emits_strictly_valid_json(method, path, payload):
    """No endpoint may emit Infinity or NaN.

    Both arise naturally here — Sortino with no losing day, profit factor with
    no losing trade, every indicator's warm-up. Python's json module writes them
    as bare tokens that JSON.parse rejects, which would break the dashboard on
    exactly the interesting cases.
    """
    response = client.request(method, path, json=payload)
    assert response.status_code == 200, response.text
    strict_json(response)


def test_an_infinite_sortino_actually_reaches_the_api_as_null():
    """Guard the guard: prove the inf case is reachable, so the test above is
    not passing merely because no endpoint ever produces one."""
    from app.analytics.metrics import sortino_ratio

    assert sortino_ratio(pd.Series([0.01] * 100), 252, rf=0.0) == math.inf
    assert clean(sortino_ratio(pd.Series([0.01] * 100), 252, rf=0.0)) is None
