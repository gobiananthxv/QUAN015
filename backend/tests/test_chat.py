"""Assistant chat proxy.

The Featherless call must never hit the network in the test suite, so every
provider interaction is monkeypatched. These tests pin the request contract
(model, temperature, system prompt, history ordering) and the error mapping.
"""
from __future__ import annotations

import json

import pytest
import requests
from fastapi.testclient import TestClient

from app import chat as chat_mod
from app.chat import ChatKeyError, ChatProviderError, chat_completion
from app.main import app

client = TestClient(app)


def _ok_response(content: str):
    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return Resp()


def _fail_response(status: int, body: str):
    class Resp:
        status_code = status
        text = body
        reason = "boom"

    return Resp()


def test_chat_rejects_a_missing_api_key(monkeypatch):
    monkeypatch.delenv("api_key", raising=False)
    with pytest.raises(ChatKeyError):
        chat_completion({}, "hello")
    assert client.post("/api/chat", json={"page_json": {}, "user_prompt": "hi"}).status_code == 503


def test_chat_sends_the_expected_request_contract(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _ok_response("**Summary**")

    monkeypatch.setattr(chat_mod.requests, "post", fake_post)
    monkeypatch.setenv("api_key", "test-key-123")

    page_json = {"page_id": "risk", "selected_asset": "GOLD", "charts": []}
    reply = chat_completion(page_json, "overall view?")

    assert reply == "**Summary**"
    assert captured["url"] == chat_mod.API_URL
    assert captured["headers"]["Authorization"] == "Bearer test-key-123"
    assert captured["headers"]["Content-Type"] == "application/json"
    body = captured["json"]
    assert body["model"] == "Qwen/Qwen3-8B"
    assert body["max_tokens"] == 4096
    assert body["temperature"] == 0.2
    assert captured["timeout"] is not None

    system = body["messages"][0]
    user = body["messages"][-1]
    assert system["role"] == "system"
    assert "Never invent or hallucinate" in system["content"]
    assert "dependency graph" in system["content"].lower()
    decoded = json.loads(user["content"])
    assert decoded["page_json"] == page_json
    assert decoded["user_prompt"] == "overall view?"


def test_chat_prepends_history_before_the_current_prompt(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(json=json)
        return _ok_response("ok")

    monkeypatch.setattr(chat_mod.requests, "post", fake_post)
    monkeypatch.setenv("api_key", "test-key-123")

    chat_completion(
        {},
        "follow-up",
        [
            {"role": "user", "content": "what is drawdown?"},
            {"role": "assistant", "content": "drawdown is..."},
        ],
    )
    roles = [m["role"] for m in captured["json"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert captured["json"]["messages"][1]["content"] == "what is drawdown?"


def test_chat_surfaces_a_provider_error(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return _fail_response(429, "rate limited")

    monkeypatch.setattr(chat_mod.requests, "post", fake_post)
    monkeypatch.setenv("api_key", "test-key-123")

    with pytest.raises(ChatProviderError) as exc:
        chat_completion({}, "hi")
    assert exc.value.status == 429

    response = client.post("/api/chat", json={"page_json": {}, "user_prompt": "hi"})
    assert response.status_code == 502
    assert "Featherless" in response.json()["detail"]


def test_chat_maps_a_network_failure(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(chat_mod.requests, "post", fake_post)
    monkeypatch.setenv("api_key", "test-key-123")

    response = client.post("/api/chat", json={"page_json": {}, "user_prompt": "hi"})
    assert response.status_code == 502
    assert "unreachable" in response.json()["detail"]


def test_chat_endpoint_returns_clean_json(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return _ok_response("## Read\n\n- bullet one\n- bullet two")

    monkeypatch.setattr(chat_mod.requests, "post", fake_post)
    monkeypatch.setenv("api_key", "test-key-123")

    body = {
        "page_json": {"page_id": "backtest", "charts": [{"id": "equity_curve"}]},
        "user_prompt": "what is the equity curve saying?",
    }
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    payload = json.loads(response.content, parse_constant=lambda t: (_ for _ in ()).throw(AssertionError(t)))
    assert payload == {
        "reply": "## Read\n\n- bullet one\n- bullet two"
    }


def test_chat_rejects_an_empty_prompt():
    assert client.post("/api/chat", json={"page_json": {}, "user_prompt": ""}).status_code == 422