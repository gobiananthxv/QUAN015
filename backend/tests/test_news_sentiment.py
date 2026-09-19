"""News-sentiment API contract.

The analyze endpoints are live Gemini calls, so nothing here may reach the
provider. The tests pin the parts that must hold regardless: the health shape,
the loud 503 when no API key is configured, input validation, the JSON-parser
tolerance, and — the part that genuinely runs — ``chart-data`` reading the same
committed snapshot as every other endpoint.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.news_sentiment_backend import (
    NewsSentimentAnalyzer,
    _as_json,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    """Force the analyzer into its unconfigured state for the test suite."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.api.news_sentiment_routes as routes

    monkeypatch.setattr(routes, "_analyzer", NewsSentimentAnalyzer(api_key=None))
    return routes


def strict_json(response) -> object:
    return json.loads(response.content, parse_constant=_reject)


def _reject(token: str):
    raise AssertionError(f"response contained non-JSON token {token!r}")


# ================================================================ JSON parser


def test_as_json_strips_code_fence():
    assert _as_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _as_json('{"a": 1}') == {"a": 1}


def test_as_json_rejects_non_json():
    from app.news_sentiment_backend import AnalysisError

    with pytest.raises(AnalysisError):
        _as_json("sorry, no JSON here")


def test_as_json_rejects_non_object():
    from app.news_sentiment_backend import AnalysisError

    with pytest.raises(AnalysisError):
        _as_json("[1, 2, 3]")


# ================================================================ health


def test_health_reports_unconfigured_without_key():
    r = client.get("/api/news-sentiment/health")
    assert r.status_code == 200
    body = strict_json(r)
    assert body["status"] == "ok"
    assert body["api_key_configured"] is False


def test_health_reports_configured_with_key(monkeypatch):
    import app.api.news_sentiment_routes as routes

    monkeypatch.setattr(routes, "_analyzer", NewsSentimentAnalyzer(api_key="dummy"))
    r = client.get("/api/news-sentiment/health")
    assert r.status_code == 200
    assert strict_json(r)["api_key_configured"] is True


# ================================================================ analysis


def test_analyze_text_503_without_key():
    r = client.post("/api/news-sentiment/analyze-text", json={"text": "Bitcoin surges on Fed cut"})
    assert r.status_code == 503
    assert "GEMINI_API_KEY" in r.json()["detail"]


def test_analyze_text_422_when_empty():
    r = client.post("/api/news-sentiment/analyze-text", json={"text": ""})
    assert r.status_code == 422


def test_analyze_text_422_when_too_long():
    r = client.post("/api/news-sentiment/analyze-text", json={"text": "x" * 10_001})
    assert r.status_code == 422


def test_analyze_image_503_without_key_png():
    r = client.post(
        "/api/news-sentiment/analyze-image",
        files={"image": ("news.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
    )
    assert r.status_code == 503


def test_analyze_image_400_on_bad_media_type():
    r = client.post(
        "/api/news-sentiment/analyze-image",
        files={"image": ("news.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 400


def test_analyze_image_413_on_oversized(monkeypatch):
    from app.api import news_sentiment_routes as routes

    monkeypatch.setattr(routes, "MAX_IMAGE_BYTES", 16)
    r = client.post(
        "/api/news-sentiment/analyze-image",
        files={"image": ("news.png", b"\x89PNG\r\n\x1a\n" + b"0" * 256, "image/png")},
    )
    assert r.status_code == 413


# ================================================================ chart-data


def test_chart_data_reads_the_snapshot():
    r = client.post(
        "/api/news-sentiment/chart-data",
        json={"asset": "GOLD", "lookback_days": 5},
    )
    assert r.status_code == 200
    body = strict_json(r)
    assert body["asset"] == "GOLD"
    assert len(body["dates"]) == 5
    assert len(body["prices"]) == 5
    assert len(body["sma_20"]) == 5
    assert len(body["ema_12"]) == 5
    assert body["forecast"] == []


def test_chart_data_accepts_lowercase_asset():
    r = client.post(
        "/api/news-sentiment/chart-data",
        json={"asset": "btc", "lookback_days": 3},
    )
    assert r.status_code == 200
    assert strict_json(r)["asset"] == "BTC"


def test_chart_data_404_on_unknown_asset():
    r = client.post(
        "/api/news-sentiment/chart-data",
        json={"asset": "DOGE", "lookback_days": 5},
    )
    assert r.status_code == 404


def test_chart_data_422_on_bad_lookback():
    r = client.post(
        "/api/news-sentiment/chart-data",
        json={"asset": "GOLD", "lookback_days": 0},
    )
    assert r.status_code == 422


# ================================================================ history


def test_sentiment_history_empty_container():
    r = client.get("/api/news-sentiment/sentiment-history")
    assert r.status_code == 200
    body = strict_json(r)
    assert body == {"analyses": [], "total": 0}


# ================================================================ stable model & retry logic


def test_analyzer_default_model():
    analyzer = NewsSentimentAnalyzer(api_key="test_key")
    assert analyzer.model == "gemini-3.5-flash-lite"


def test_analyzer_retry_logic_on_rate_limit(monkeypatch):
    calls_count = 0

    class MockModelClient:
        def generate_content(self, model, contents, config):
            nonlocal calls_count
            calls_count += 1
            if calls_count <= 2:
                # Simulate rate limit error
                raise Exception("Resource has been exhausted (e.g. 429).")
            
            # Successful response on 3rd call
            class MockResponse:
                text = '{"article_metadata": {"headline": "Bitcoin surges"}}'
            return MockResponse()

    analyzer = NewsSentimentAnalyzer(api_key="test_key")
    # Mock client and sleep to make the test run instantly
    monkeypatch.setattr(analyzer, "_client_or_raise", lambda: type("Client", (), {"models": MockModelClient()})())
    monkeypatch.setattr("time.sleep", lambda x: None)

    res = analyzer.analyze_news_text("test article")
    assert res["article_metadata"]["headline"] == "Bitcoin surges"
    assert calls_count == 3


def test_analyzer_search_grounding_fallback(monkeypatch):
    calls_count = 0
    search_enabled_during_calls = []

    class MockModelClient:
        def generate_content(self, model, contents, config):
            nonlocal calls_count
            calls_count += 1
            search_enabled_during_calls.append(config.tools is not None and len(config.tools) > 0)
            if calls_count == 1:
                # First call fails on quota with search enabled
                raise Exception("Search quota limits exceeded.")
            
            # Second call succeeds
            class MockResponse:
                text = '{"article_metadata": {"headline": "Gold drops"}}'
            return MockResponse()

    analyzer = NewsSentimentAnalyzer(api_key="test_key")
    monkeypatch.setattr(analyzer, "_client_or_raise", lambda: type("Client", (), {"models": MockModelClient()})())
    monkeypatch.setenv("GEMINI_SEARCH_GROUNDING", "true")

    res = analyzer.analyze_news_text("test article")
    assert res["article_metadata"]["headline"] == "Gold drops"
    assert calls_count == 2
    assert search_enabled_during_calls == [True, False]