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
from app.backtest.strategies import REGISTRY
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
    assert names == set(REGISTRY)
    assert {"sma_crossover", "ema_trend", "momentum", "mean_reversion", "vol_target"} <= names
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
    assert len(body["runs"]) == len(REGISTRY)
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


# ================================================================ snapshot / refresh


def test_assets_reports_snapshot_state():
    body = strict_json(client.get("/api/assets"))
    assert "snapshot" in body
    entry = {s["asset"]: s for s in body["snapshot"]}["NVDA"]
    assert entry["available"] is True
    assert entry["rows"] > 2000
    assert entry["start"] < entry["end"]


def test_reading_data_never_touches_the_network(monkeypatch):
    """The central claim of the snapshot design.

    Every read endpoint must be satisfiable from the committed CSVs. If any of
    them silently fetched, results would change under the user mid-session and
    the platform would stop working offline.
    """
    import app.data.store as store

    def explode(*_a, **_k):
        raise AssertionError("a read endpoint reached the network")

    monkeypatch.setattr(store, "fetch_ohlcv", explode)

    for path in (
        "/api/assets",
        "/api/ohlcv?asset=NVDA",
        "/api/indicators?asset=GOLD",
        "/api/metrics?asset=BTC",
        "/api/correlation",
        "/api/regime?asset=NVDA",
        "/api/panel",
    ):
        assert client.get(path).status_code == 200, path

    assert client.post("/api/backtest", json={"asset": "BTC", "strategy": "momentum"}).status_code == 200


def test_refresh_calls_the_provider_and_reports_what_changed(monkeypatch):
    """Refresh is the one endpoint allowed to fetch. Stubbed so the suite stays
    offline and fast — we assert the plumbing, not Yahoo's uptime."""
    import app.data.store as store

    calls: list[str] = []
    real = store.load_asset

    def spy(key, refresh=False):
        if refresh:
            calls.append(key)
        return real(key, refresh=False)  # never actually re-download in tests

    monkeypatch.setattr(store, "load_asset", spy)

    body = strict_json(
        client.post("/api/data/refresh", json={"assets": ["NVDA"], "force": True})
    )
    assert calls == ["NVDA"], "refresh must request exactly the asset asked for"
    assert [u["asset"] for u in body["updated"]] == ["NVDA"]
    assert body["failed"] == []
    assert len(body["snapshot"]) == 3


def test_refresh_with_no_body_updates_everything(monkeypatch):
    import app.data.store as store

    calls: list[str] = []
    real = store.load_asset

    def spy(key, refresh=False):
        if refresh:
            calls.append(key)
        return real(key, refresh=False)

    monkeypatch.setattr(store, "load_asset", spy)

    body = strict_json(client.post("/api/data/refresh", json={"force": True}))
    assert set(calls) == {"GOLD", "BTC", "NVDA"}
    assert len(body["updated"]) == 3


def test_refresh_rejects_an_unknown_asset():
    r = client.post("/api/data/refresh", json={"assets": ["DOGECOIN"]})
    assert r.status_code == 404


def test_refresh_reports_a_partial_failure_without_failing_the_whole_call(monkeypatch):
    """One unreachable ticker must not leave the caller with no information
    about the two that did update."""
    import app.data.store as store

    real = store.load_asset

    def flaky(key, refresh=False):
        if refresh and key == "BTC":
            raise RuntimeError("provider timeout")
        return real(key, refresh=False)

    monkeypatch.setattr(store, "load_asset", flaky)

    body = strict_json(client.post("/api/data/refresh", json={"force": True}))
    assert {u["asset"] for u in body["updated"]} == {"GOLD", "NVDA"}
    assert [f["asset"] for f in body["failed"]] == ["BTC"]
    assert "provider timeout" in body["failed"][0]["error"]


def test_refresh_returns_502_only_when_everything_fails(monkeypatch):
    """Plain reads still succeed here on purpose: after a failed refresh the
    endpoint reports what remains on disk, so the caller learns the provider is
    down *and* that the previous snapshot is intact."""
    import app.data.store as store

    real = store.load_asset

    def down(key, refresh=False):
        if refresh:
            raise RuntimeError("provider unreachable")
        return real(key, refresh=False)

    monkeypatch.setattr(store, "load_asset", down)

    r = client.post("/api/data/refresh", json={"force": True})
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"]


def test_a_failed_refresh_leaves_the_snapshot_usable(monkeypatch):
    """A provider outage must not take the platform down with it."""
    import app.data.store as store

    real = store.load_asset

    def down(key, refresh=False):
        if refresh:
            raise RuntimeError("provider unreachable")
        return real(key, refresh=False)

    monkeypatch.setattr(store, "load_asset", down)

    client.post("/api/data/refresh", json={"force": True})
    assert client.get("/api/ohlcv?asset=NVDA").status_code == 200
    assert client.post("/api/backtest", json={"asset": "NVDA", "strategy": "momentum"}).status_code == 200


def test_refresh_skips_assets_fetched_within_the_last_day(monkeypatch):
    """Bars are daily, so a second fetch inside 24h rewrites identical rows.

    Skipping is reported explicitly rather than folded into "updated" — pressing
    Refresh twice should say "already current", not pretend to have worked.
    """
    import app.data.store as store

    def explode(*_a, **_k):
        raise AssertionError("refresh fetched despite a fresh snapshot")

    monkeypatch.setattr(store, "fetch_ohlcv", explode)

    body = strict_json(client.post("/api/data/refresh", json={"assets": ["NVDA"]}))
    assert body["updated"] == []
    assert [s["asset"] for s in body["skipped"]] == ["NVDA"]
    assert body["skipped"][0]["age_hours"] < 24
    assert "daily" in body["skipped"][0]["reason"]


def test_refresh_force_overrides_the_daily_skip(monkeypatch):
    import app.data.store as store

    calls: list[str] = []
    real = store.load_asset

    def spy(key, refresh=False):
        if refresh:
            calls.append(key)
        return real(key, refresh=False)

    monkeypatch.setattr(store, "load_asset", spy)

    body = strict_json(
        client.post("/api/data/refresh", json={"assets": ["NVDA"], "force": True})
    )
    assert calls == ["NVDA"]
    assert body["skipped"] == []


def test_an_all_skipped_refresh_is_not_an_error():
    """Nothing to do is a success, not a 502."""
    r = client.post("/api/data/refresh", json={})
    assert r.status_code == 200
    body = strict_json(r)
    assert len(body["skipped"]) == 3
    assert body["failed"] == []


# ================================================================ backtest period


def test_backtest_accepts_a_date_window():
    body = strict_json(
        client.post(
            "/api/backtest",
            json={
                "asset": "NVDA",
                "strategy": "sma_crossover",
                "start": "2020-01-01",
                "end": "2022-12-31",
            },
        )
    )
    dates = body["strategy"]["curves"]["dates"]
    assert dates[0] >= "2020-01-01" and dates[-1] <= "2022-12-31"
    assert body["period"] == {"start": "2020-01-01", "end": "2022-12-31"}


def test_windowed_backtest_is_shorter_than_the_full_history():
    full = strict_json(
        client.post("/api/backtest", json={"asset": "NVDA", "strategy": "momentum"})
    )
    win = strict_json(
        client.post(
            "/api/backtest",
            json={"asset": "NVDA", "strategy": "momentum", "start": "2022-01-01"},
        )
    )
    assert len(win["strategy"]["curves"]["dates"]) < len(full["strategy"]["curves"]["dates"])


def test_benchmark_is_restricted_to_the_same_window():
    """Comparing a windowed strategy against a full-history benchmark would be
    comparing two different periods — the single worst thing this feature could
    silently do."""
    body = strict_json(
        client.post(
            "/api/backtest",
            json={
                "asset": "NVDA",
                "strategy": "sma_crossover",
                "start": "2021-01-01",
                "end": "2021-12-31",
            },
        )
    )
    assert body["strategy"]["curves"]["dates"] == body["benchmark"]["curves"]["dates"]


def test_signals_are_regenerated_inside_the_window_not_trimmed():
    """A sub-period must be a genuine out-of-sample run.

    Slicing a full-history signal series would let indicator values at the start
    of the window carry information from before it. Regenerating inside the
    window means the warm-up happens again, so the windowed run holds a position
    on strictly fewer of its early bars.
    """
    win = strict_json(
        client.post(
            "/api/backtest",
            json={"asset": "NVDA", "strategy": "sma_crossover", "start": "2021-01-01"},
        )
    )
    # 50/200 crossover needs 200 bars of warm-up, so the window opens flat.
    assert sum(win["strategy"]["curves"]["position"][:150]) == 0


def test_backtest_rejects_an_empty_window():
    r = client.post(
        "/api/backtest",
        json={"asset": "NVDA", "strategy": "momentum", "start": "2099-01-01"},
    )
    assert r.status_code == 422
    assert "no bars" in r.json()["detail"]


def test_compare_accepts_a_date_window():
    body = strict_json(
        client.post(
            "/api/backtest/compare",
            json={"asset": "GOLD", "start": "2021-01-01", "end": "2023-12-31"},
        )
    )
    assert body["period"]["start"] == "2021-01-01"
    for run in body["runs"]:
        assert run["curves"]["dates"][0] >= "2021-01-01"
    assert body["benchmark"]["curves"]["dates"] == body["runs"][0]["curves"]["dates"]


def test_compare_rejects_an_empty_window():
    r = client.post("/api/backtest/compare", json={"asset": "GOLD", "start": "2099-01-01"})
    assert r.status_code == 422


def test_windowed_results_are_strictly_valid_json():
    r = client.post(
        "/api/backtest/compare",
        json={"asset": "BTC", "start": "2024-01-01", "end": "2024-06-30"},
    )
    assert r.status_code == 200
    strict_json(r)


def test_metrics_includes_rolling_returns():
    """The brief lists rolling returns as a required indicator. It was computed
    in metrics.py but surfaced nowhere — a requirement met on paper only."""
    body = strict_json(client.get("/api/metrics?asset=NVDA"))
    assert body["return_window"] == 252
    values = [p["ret"] for p in body["rolling_returns"]]
    assert len(values) > 2000
    # Entry date matters enormously; a single total return hides that.
    assert max(values) > 1.0 and min(values) < 0.0


def test_rolling_return_window_is_configurable():
    short = strict_json(client.get("/api/metrics?asset=GOLD&return_window=63"))
    long_ = strict_json(client.get("/api/metrics?asset=GOLD&return_window=504"))
    assert short["return_window"] == 63
    assert len(short["rolling_returns"]) > len(long_["rolling_returns"])


def test_indicators_expose_ema_for_the_price_chart():
    body = strict_json(client.get("/api/indicators?asset=NVDA&ema_fast=20&ema_slow=50"))
    assert "ema_20" in body["columns"] and "ema_50" in body["columns"]


# ================================================================ windowed metrics


def test_metrics_accepts_a_window():
    body = strict_json(client.get("/api/metrics?asset=NVDA&start=2022-01-01&end=2022-12-31"))
    assert body["bars"] == 251
    assert body["period"]["start"] >= "2022-01-01"
    assert body["period"]["end"] <= "2022-12-31"


def test_windowed_metrics_differ_from_the_full_history():
    """The Overview chart recomputes every figure for the zoomed window; if the
    range were ignored the panel would silently show full-history numbers."""
    full = strict_json(client.get("/api/metrics?asset=NVDA"))["summary"]
    bear = strict_json(
        client.get("/api/metrics?asset=NVDA&start=2022-01-01&end=2022-12-31")
    )["summary"]
    assert full["total_return"] > 100      # a decade of NVDA
    assert bear["total_return"] < 0        # 2022 alone was brutal
    assert bear["sharpe"] < 0 < full["sharpe"]


def test_windowed_metrics_series_are_confined_to_the_window():
    body = strict_json(client.get("/api/metrics?asset=GOLD&start=2020-01-01&end=2020-12-31"))
    for key in ("cumulative", "drawdown"):
        dates = [p["date"] for p in body[key]]
        assert dates[0] >= "2020-01-01" and dates[-1] <= "2020-12-31"


def test_windowed_metrics_take_returns_after_slicing():
    """The window is applied to prices, then returns are taken — so the first
    bar has no return. Slicing the return series instead would carry in one
    return computed against a close from outside the window."""
    body = strict_json(client.get("/api/metrics?asset=BTC&start=2023-01-01&end=2023-03-31"))
    assert len(body["returns"]) == body["bars"] - 1


def test_metrics_rejects_an_empty_window():
    r = client.get("/api/metrics?asset=NVDA&start=2099-01-01")
    assert r.status_code == 422
    assert "no bars" in r.json()["detail"]


def test_windowed_metrics_are_strictly_valid_json():
    r = client.get("/api/metrics?asset=GOLD&start=2019-06-01&end=2019-09-30")
    assert r.status_code == 200
    strict_json(r)


# ================================================================ global period


WINDOW = "start=2022-01-01&end=2023-12-31"


@pytest.mark.parametrize(
    "path",
    [
        f"/api/ohlcv?asset=NVDA&{WINDOW}",
        f"/api/indicators?asset=NVDA&{WINDOW}",
        f"/api/metrics?asset=NVDA&{WINDOW}",
        f"/api/correlation?{WINDOW}",
        f"/api/rolling-correlation?a=BTC&b=NVDA&{WINDOW}",
        f"/api/regime?asset=NVDA&{WINDOW}",
        f"/api/backtest/regime-attribution?asset=NVDA&strategy=momentum&{WINDOW}",
    ],
    ids=lambda p: p.split("?")[0],
)
def test_every_get_endpoint_accepts_the_shared_period(path):
    """The dashboard sets one period for the whole platform; an endpoint that
    silently ignored it would show full-history numbers under a window label."""
    r = client.request("GET", path)
    assert r.status_code == 200, r.text
    strict_json(r)


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/backtest", {"asset": "NVDA", "strategy": "momentum"}),
        ("/api/backtest/compare", {"asset": "NVDA"}),
        ("/api/backtest/robustness", {"asset": "NVDA", "strategy": "momentum"}),
    ],
    ids=["backtest", "compare", "robustness"],
)
def test_every_post_endpoint_accepts_the_shared_period(path, body):
    r = client.post(path, json={**body, "start": "2022-01-01", "end": "2023-12-31"})
    assert r.status_code == 200, r.text
    assert strict_json(r)["period"] == {"start": "2022-01-01", "end": "2023-12-31"}


def test_windowed_correlation_differs_from_the_full_sample():
    """The point of scoping correlation: GOLD and NVIDIA look unrelated across
    the decade and considerably less so through 2020."""
    full = strict_json(client.get("/api/correlation"))
    y2020 = strict_json(client.get("/api/correlation?start=2020-01-01&end=2020-12-31"))

    def pair(body, a, b):
        return next(c["value"] for c in body["matrix"] if c["a"] == a and c["b"] == b)

    assert y2020["observations"] < full["observations"]
    assert pair(y2020, "GOLD", "NVDA") > pair(full, "GOLD", "NVDA") + 0.1


def test_windowed_correlation_matrix_stays_well_formed():
    body = strict_json(client.get("/api/correlation?start=2021-01-01&end=2021-12-31"))
    for c in body["matrix"]:
        if c["a"] == c["b"]:
            assert abs(c["value"] - 1.0) < 1e-9
        assert -1.0 <= c["value"] <= 1.0


def test_windowed_robustness_reruns_the_whole_sweep():
    """Surface, cost decay and period stability must all be confined to the
    window — not just the headline."""
    body = strict_json(
        client.post(
            "/api/backtest/robustness",
            json={"asset": "NVDA", "strategy": "momentum", "start": "2022-01-01", "end": "2023-12-31"},
        )
    )
    assert body["sweep"] and body["surface"]
    for row in body["periods"]:
        assert row["start"] >= "2022-01-01" and row["end"] <= "2023-12-31"


def test_windowed_regime_labels_stay_inside_the_window():
    body = strict_json(client.get("/api/regime?asset=BTC&start=2021-06-01&end=2021-12-31"))
    dates = [r["date"] for r in body["rows"]]
    assert dates[0] >= "2021-06-01" and dates[-1] <= "2021-12-31"


@pytest.mark.parametrize(
    "path",
    [
        "/api/correlation?start=2099-01-01",
        "/api/regime?asset=NVDA&start=2099-01-01",
        "/api/metrics?asset=NVDA&start=2099-01-01",
        "/api/rolling-correlation?a=BTC&b=NVDA&start=2099-01-01",
    ],
    ids=lambda p: p.split("?")[0],
)
def test_an_empty_window_is_rejected_everywhere(path):
    """Consistently 422 rather than an empty chart or a stack trace."""
    assert client.get(path).status_code == 422


def test_regime_forecast_returns_valid_structure():
    r = client.get("/api/forecast/regime?asset=NVDA&days=30")
    assert r.status_code == 200, r.text
    body = strict_json(r)
    assert body["asset"] == "NVDA"
    assert body["days"] == 30
    assert len(body["rows"]) == 30
    assert "conservative" in body["horizon"]
    assert len(body["regimes"]) > 0
    for row in body["rows"]:
        assert "day" in row
        prob_sum = sum(row[reg] for reg in body["regimes"])
        assert 0.99 <= prob_sum <= 1.01

