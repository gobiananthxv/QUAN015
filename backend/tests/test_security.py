"""The capability boundary.

Two things are being pinned here, and they pull in opposite directions:

1. The five effectful endpoints are guarded — they refuse without the shared
   secret, they refuse when hammered, and the mail endpoint refuses a recipient
   nobody approved.
2. The other seventeen are *not* guarded, and stay reachable. A security layer
   that quietly puts the read-only dashboard behind configuration has broken
   the product to protect the parts that were never at risk.

The second set matters as much as the first. Most of this suite exists to catch
the guard spreading.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import security
from app.main import app
from app.security import (
    BUDGETS,
    MAX_GRID_CELLS,
    TOKEN_HEADER,
    RateLimiter,
    check_grid_size,
    configured_token,
    limiter,
    recipient_allowed,
    security_status,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _contain_the_mailer(monkeypatch, tmp_path):
    """Keep the report mailer off the network and out of the repository.

    Several tests here drive ``/api/report/send-email`` far enough to check a
    guard, and any request that gets *past* the guards runs the real thing:
    it packages every file under ``backend/output``, opens an SMTP connection,
    and writes a multi-megabyte ``.eml`` audit copy back into that same folder.
    A suite that does this leaves artifacts behind and grows what the next run
    has to package.

    Redirecting the output directory keeps every code path intact — validation,
    allowlist, archive assembly — while the bytes land somewhere disposable.
    """
    monkeypatch.setattr("app.email_service.get_output_dir", lambda: tmp_path)
    monkeypatch.setattr("smtplib.SMTP", lambda *a, **k: _NullSMTP())
    monkeypatch.setattr("smtplib.SMTP_SSL", lambda *a, **k: _NullSMTP())


class _NullSMTP:
    """A transport that accepts everything and sends nothing."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, *a, **k):
        pass

    def login(self, *a, **k):
        pass

    def send_message(self, *a, **k):
        pass


# Guarded and unguarded endpoints, as a single source of truth for the tests
# that assert the boundary has not moved.
GUARDED = [
    ("POST", "/api/data/refresh"),
    ("POST", "/api/report/send-email"),
    ("POST", "/api/chat"),
    ("POST", "/api/news-sentiment/analyze-text"),
    ("POST", "/api/news-sentiment/analyze-image"),
]

UNGUARDED = [
    "/health",
    "/api/assets",
    "/api/strategies",
    "/api/ohlcv?asset=NVDA",
    "/api/metrics?asset=NVDA",
    "/api/panel",
]


def _call(method: str, path: str, headers: dict | None = None):
    """Hit an endpoint with a body good enough to reach the guards.

    The payloads are intentionally minimal: every one of these requests is
    expected to be rejected by a dependency before the route body runs, so the
    body only has to survive validation.
    """
    if method == "GET":
        return client.get(path, headers=headers)
    if path.endswith("analyze-image"):
        return client.post(
            path,
            files={"image": ("a.png", b"\x89PNG\r\n", "image/png")},
            headers=headers,
        )
    bodies = {
        "/api/data/refresh": {"assets": [], "force": False},
        "/api/report/send-email": {"email": "nobody@example.com"},
        "/api/chat": {"page_json": {}, "user_prompt": "hi"},
        "/api/news-sentiment/analyze-text": {"text": "markets rose"},
    }
    return client.post(path, json=bodies[path], headers=headers)


# ---------------------------------------------------------------- token guard


@pytest.mark.parametrize("method,path", GUARDED)
def test_no_configured_token_leaves_the_guard_inert(monkeypatch, method, path):
    """Unconfigured is unguarded, by design, and must not fail closed.

    A fresh clone has no token. If that returned 401 the platform would not run
    out of the box, which is why the default is documented rather than secret.
    """
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    # The recipient allowlist is a separate control and fails closed regardless
    # of the token; approve the address so only the token guard is under test.
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "nobody@example.com")
    assert configured_token() is None
    assert _call(method, path).status_code not in (401, 403)


@pytest.mark.parametrize("method,path", GUARDED)
def test_a_configured_token_is_required(monkeypatch, method, path):
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    response = _call(method, path)
    assert response.status_code == 401
    assert TOKEN_HEADER in response.json()["detail"]


@pytest.mark.parametrize("method,path", GUARDED)
def test_a_wrong_token_is_rejected_as_401_not_403(monkeypatch, method, path):
    """A bad credential is 401. 403 is kept exclusively for the recipient
    policy, so the dashboard can tell the two apart without guessing."""
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    response = _call(method, path, headers={TOKEN_HEADER: "not-the-secret"})
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", GUARDED)
def test_the_right_token_passes_the_guard(monkeypatch, method, path):
    """Past the fence the route may still fail — on a missing provider key, an
    unapproved recipient, an unreachable network. Any of those is fine; what
    must not happen is 401 or 403."""
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    monkeypatch.delenv("api_key", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = _call(method, path, headers={TOKEN_HEADER: "s3cret-value"})
    assert response.status_code != 401


def test_a_token_of_the_wrong_length_is_rejected_not_crashed(monkeypatch):
    """``compare_digest`` raises on non-ASCII; the guard must answer, not 500."""
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    response = _call("POST", "/api/chat", headers={TOKEN_HEADER: "x"})
    assert response.status_code == 401


def test_failed_token_attempts_consume_the_budget(monkeypatch):
    """Guessing must cost the guesser something.

    Dependencies resolve in order and the first to raise wins, so a route that
    checked the token first would hand out unlimited 401s for free. The rate
    limit is listed first precisely so a brute-force attempt runs out of
    requests rather than running forever.
    """
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    limit, _ = BUDGETS["chat"]
    codes = [
        _call("POST", "/api/chat", headers={TOKEN_HEADER: f"guess-{i}"}).status_code
        for i in range(limit + 3)
    ]
    assert codes[:limit] == [401] * limit
    assert codes[limit:] == [429, 429, 429]


def test_the_two_refusals_are_distinguishable(monkeypatch):
    """The whole point of the split: one endpoint, two reasons, two codes."""
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "approved@mine.com")
    bad_token = client.post(
        "/api/report/send-email",
        json={"email": "approved@mine.com"},
        headers={TOKEN_HEADER: "wrong"},
    )
    bad_recipient = client.post(
        "/api/report/send-email",
        json={"email": "attacker@evil.com"},
        headers={TOKEN_HEADER: "s3cret-value"},
    )
    assert bad_token.status_code == 401
    assert bad_recipient.status_code == 403


@pytest.mark.parametrize("path", UNGUARDED)
def test_read_only_endpoints_never_require_a_token(monkeypatch, path):
    """The whole dashboard stays browsable with the strictest configuration."""
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    assert client.get(path).status_code == 200


# ---------------------------------------------------------------- rate limiting


def test_the_bucket_allows_exactly_the_budget_then_blocks():
    """Time is injected rather than slept, so the test is fast and exact."""
    rl = RateLimiter()
    limit, _ = BUDGETS["chat"]
    for _ in range(limit):
        assert rl.check("chat", "1.2.3.4", now=1000.0) == 0.0
    assert rl.check("chat", "1.2.3.4", now=1000.0) > 0.0


def test_the_bucket_refills_over_time():
    rl = RateLimiter()
    limit, window = BUDGETS["chat"]
    for _ in range(limit):
        rl.check("chat", "1.2.3.4", now=1000.0)
    assert rl.check("chat", "1.2.3.4", now=1000.0) > 0.0
    # One full window later the bucket is back to capacity.
    for _ in range(limit):
        assert rl.check("chat", "1.2.3.4", now=1000.0 + window) == 0.0


def test_the_wait_hint_is_the_time_until_one_token():
    rl = RateLimiter()
    limit, window = BUDGETS["chat"]
    for _ in range(limit):
        rl.check("chat", "1.2.3.4", now=1000.0)
    wait = rl.check("chat", "1.2.3.4", now=1000.0)
    assert wait == pytest.approx(window / limit)


def test_clients_have_independent_budgets():
    rl = RateLimiter()
    limit, _ = BUDGETS["chat"]
    for _ in range(limit):
        rl.check("chat", "1.2.3.4", now=1000.0)
    assert rl.check("chat", "1.2.3.4", now=1000.0) > 0.0
    assert rl.check("chat", "5.6.7.8", now=1000.0) == 0.0


def test_routes_have_independent_budgets():
    """Spending the email budget must not lock a user out of the assistant."""
    rl = RateLimiter()
    limit, _ = BUDGETS["email"]
    for _ in range(limit):
        rl.check("email", "1.2.3.4", now=1000.0)
    assert rl.check("email", "1.2.3.4", now=1000.0) > 0.0
    assert rl.check("chat", "1.2.3.4", now=1000.0) == 0.0


def test_the_bucket_table_stays_bounded(monkeypatch):
    """A spray of distinct clients must not grow memory without limit."""
    monkeypatch.setattr(security, "MAX_TRACKED_CLIENTS", 16)
    rl = RateLimiter()
    for i in range(200):
        rl.check("chat", f"10.0.0.{i}", now=1000.0 + i)
    assert len(rl._buckets) <= 16


def test_exceeding_the_budget_returns_429_with_a_retry_hint(monkeypatch):
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    monkeypatch.delenv("api_key", raising=False)
    limit, _ = BUDGETS["chat"]
    for _ in range(limit):
        _call("POST", "/api/chat")
    response = _call("POST", "/api/chat")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) >= 1


def test_the_rate_limit_applies_before_the_work(monkeypatch):
    """A 429 must be cheap. If the budget were checked after the provider call
    the limit would protect nothing it exists to protect."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    calls = []
    monkeypatch.setattr(
        "app.api.chat_routes.chat_completion",
        lambda *a, **k: calls.append(1) or "ok",
    )
    limit, _ = BUDGETS["chat"]
    for _ in range(limit + 5):
        _call("POST", "/api/chat")
    assert len(calls) == limit


def test_forwarded_headers_cannot_buy_a_fresh_budget(monkeypatch):
    """Honouring X-Forwarded-For with no trusted proxy would let any caller
    rotate their own identity and opt out of the limit entirely."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    monkeypatch.delenv("api_key", raising=False)
    limit, _ = BUDGETS["chat"]
    for i in range(limit):
        _call("POST", "/api/chat", headers={"X-Forwarded-For": f"9.9.9.{i}"})
    blocked = _call("POST", "/api/chat", headers={"X-Forwarded-For": "9.9.9.99"})
    assert blocked.status_code == 429


def test_read_only_endpoints_are_not_rate_limited(monkeypatch):
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    for _ in range(60):
        assert client.get("/api/assets").status_code == 200


# ---------------------------------------------------------------- grid cap


def test_a_grid_within_the_cap_is_accepted():
    check_grid_size({"a": list(range(10)), "b": list(range(10))})


def test_an_oversized_grid_is_rejected():
    with pytest.raises(HTTPException) as exc:
        check_grid_size({"a": list(range(100)), "b": list(range(100))})
    assert exc.value.status_code == 422
    assert "10000" in exc.value.detail


def test_the_cap_counts_cells_not_axes():
    """Two short axes are cheap; two long ones are not. The cost is the product,
    which is the whole reason a per-axis limit would not do."""
    check_grid_size({"a": list(range(MAX_GRID_CELLS)), "b": [1]})
    with pytest.raises(HTTPException):
        check_grid_size({"a": list(range(MAX_GRID_CELLS)), "b": [1, 2]})


def test_the_robustness_endpoint_rejects_an_oversized_grid(monkeypatch):
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    response = client.post(
        "/api/backtest/robustness",
        json={
            "asset": "NVDA",
            "strategy": "sma_crossover",
            "grid": {"fast": list(range(1, 101)), "slow": list(range(1, 101))},
        },
    )
    assert response.status_code == 422
    assert "limit is" in response.json()["detail"]


def test_a_normal_robustness_request_still_works(monkeypatch):
    """The cap must sit above anything the dashboard actually sends."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    response = client.post(
        "/api/backtest/robustness",
        json={"asset": "NVDA", "strategy": "sma_crossover"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------- recipients


def test_an_explicit_allowlist_is_honoured(monkeypatch):
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "a@x.com, b@y.com")
    assert recipient_allowed("a@x.com")
    assert recipient_allowed("b@y.com")
    assert not recipient_allowed("c@z.com")


def test_recipient_matching_ignores_case_and_padding(monkeypatch):
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "Analyst@Example.COM")
    assert recipient_allowed("  analyst@example.com  ")


def test_a_domain_entry_matches_the_whole_domain(monkeypatch):
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "@myteam.org")
    assert recipient_allowed("anyone@myteam.org")
    assert not recipient_allowed("anyone@othert.eam")


def test_an_unset_allowlist_falls_back_to_the_sender(monkeypatch):
    """The feature keeps working for its intended use — mailing yourself the run
    output — while the exfiltration path is closed."""
    monkeypatch.delenv("REPORT_EMAIL_ALLOWLIST", raising=False)
    monkeypatch.setenv("SMTP_FROM", "me@mine.com")
    assert recipient_allowed("me@mine.com")
    assert not recipient_allowed("attacker@evil.com")


def test_the_fallback_prefers_smtp_from_then_smtp_user(monkeypatch):
    monkeypatch.delenv("REPORT_EMAIL_ALLOWLIST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.setenv("SMTP_USER", "user@mine.com")
    assert recipient_allowed("user@mine.com")


def test_nothing_configured_allows_nobody(monkeypatch):
    """Fails closed. An empty allowlist is a restriction, never a wildcard."""
    for name in ("REPORT_EMAIL_ALLOWLIST", "SMTP_FROM", "SMTP_USER"):
        monkeypatch.delenv(name, raising=False)
    assert not recipient_allowed("anyone@anywhere.com")
    assert not recipient_allowed("")


def test_the_endpoint_refuses_an_unapproved_recipient(monkeypatch):
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "approved@mine.com")
    response = client.post(
        "/api/report/send-email", json={"email": "attacker@evil.com"}
    )
    assert response.status_code == 403
    assert "not an approved report recipient" in response.json()["detail"]


def test_a_malformed_address_is_a_400_not_a_403(monkeypatch):
    """Shape is checked before permission: a typo is the caller's mistake, an
    unapproved address is a policy decision, and the codes should say which."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    response = client.post("/api/report/send-email", json={"email": "not-an-email"})
    assert response.status_code == 400


def test_the_recipient_check_runs_before_anything_is_packaged(monkeypatch):
    """A refused request must not read backend/output, build a ZIP, or write an
    .eml log. Otherwise the endpoint is still a disk-filling primitive."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "approved@mine.com")
    called = []
    monkeypatch.setattr(
        "app.email_service.collect_output_files", lambda *a: called.append(1) or []
    )
    client.post("/api/report/send-email", json={"email": "attacker@evil.com"})
    assert called == []


# ---------------------------------------------------------------- introspection


def test_health_reports_whether_the_guard_is_active(monkeypatch):
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    body = client.get("/health").json()
    assert body["security"]["token_required"] is True

    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    assert client.get("/health").json()["security"]["token_required"] is False


def test_the_status_never_contains_the_token(monkeypatch):
    """Publishing the guard's state must not publish the secret it guards with."""
    monkeypatch.setenv(security.TOKEN_ENV, "s3cret-value")
    assert "s3cret-value" not in str(security_status())
    assert "s3cret-value" not in client.get("/health").text


def test_the_status_lists_every_budget():
    """If a route gains a budget, it shows up in /health without further work."""
    assert set(security_status()["rate_limits"]) == set(BUDGETS)


# ---------------------------------------------------------------- sweep capacity


def test_sweep_slots_are_bounded(monkeypatch):
    """With every slot taken, a further sweep is refused rather than queued
    behind a ten-second wait that looks like a hung server."""
    monkeypatch.setattr(security, "SWEEP_WAIT_SECONDS", 0.05)
    held = [security.sweep_slot() for _ in range(security.MAX_CONCURRENT_SWEEPS)]
    for slot in held:
        slot.__enter__()
    try:
        with pytest.raises(HTTPException) as exc:
            with security.sweep_slot():
                pass
        assert exc.value.status_code == 503
    finally:
        for slot in held:
            slot.__exit__()


def test_a_released_slot_is_reusable(monkeypatch):
    """The semaphore must be released on the failure path too, or one error
    permanently reduces the server's capacity."""
    monkeypatch.setattr(security, "SWEEP_WAIT_SECONDS", 0.05)
    for _ in range(security.MAX_CONCURRENT_SWEEPS + 3):
        with security.sweep_slot():
            pass
    with security.sweep_slot():
        pass


def test_the_limiter_reset_clears_every_route():
    rl = limiter
    rl.check("chat", "1.1.1.1")
    rl.check("email", "1.1.1.1")
    rl.reset()
    assert rl._buckets == {}


def test_the_service_refuses_an_unapproved_recipient_directly(monkeypatch):
    """Defence in depth: the guard must not live only in the route.

    ``send_report_email`` is exported and attaches everything under
    backend/output. A script that imports it gets the same refusal the API does.
    """
    import pytest

    from app.email_service import send_report_email

    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "approved@mine.com")
    with pytest.raises(PermissionError):
        send_report_email("attacker@evil.com")


def test_the_service_refusal_maps_to_403(monkeypatch):
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "approved@mine.com")
    # Bypass the route's own pre-check to prove the service-level guard is what
    # produces the 403 here, not the dependency in front of it.
    monkeypatch.setattr("app.api.routes.recipient_allowed", lambda _addr: True)
    response = client.post(
        "/api/report/send-email", json={"email": "attacker@evil.com"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------- body size


def test_a_normal_payload_is_unaffected(monkeypatch):
    """The cap must sit far above anything the dashboard actually sends."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        "app.api.chat_routes.chat_completion", lambda *a, **k: "fine"
    )
    page = {"charts": [{"id": f"c{i}", "result": {"sharpe": 1.2}} for i in range(200)]}
    response = client.post(
        "/api/chat", json={"page_json": page, "user_prompt": "summarise"}
    )
    assert response.status_code == 200


def test_an_oversized_declared_body_is_refused(monkeypatch):
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    fat = b'{"user_prompt":"' + b"x" * (security.MAX_JSON_BODY_BYTES + 1024) + b'"}'
    response = client.post(
        "/api/chat", content=fat, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert "limit" in response.json()["detail"]


def test_an_oversized_body_never_reaches_the_provider(monkeypatch):
    """The point of the cap. A refused request must cost nothing downstream."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    calls = []
    monkeypatch.setattr(
        "app.api.chat_routes.chat_completion",
        lambda *a, **k: calls.append(1) or "ok",
    )
    fat = b'{"user_prompt":"' + b"x" * (security.MAX_JSON_BODY_BYTES + 1024) + b'"}'
    client.post("/api/chat", content=fat, headers={"Content-Type": "application/json"})
    assert calls == []


def test_an_undeclared_body_is_refused_with_411(monkeypatch):
    """The case an honest implementation forgets.

    A chunked body declares no Content-Length, so the size cannot be checked
    before reading it — and failing mid-upload has no clean answer, because the
    client is still writing when the server wants to reply. Requiring the
    declaration turns the whole problem into arithmetic on a header.
    """
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)

    def chunks():
        yield b'{"user_prompt":"hello"}'

    response = client.post(
        "/api/chat", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 411
    assert "Content-Length" in response.json()["detail"]


def test_the_streaming_backstop_catches_a_lying_content_length():
    """A declared length that undercounts the actual body.

    This is the case the header check cannot catch — a client that declares
    100 bytes and sends megabytes, or a proxy that rewrote the header. The
    middleware counts what it actually receives and fails when the real total
    goes over, independent of what was promised.

    Driven as raw ASGI rather than through a client, because provoking a
    mid-upload rejection over a real connection is exactly what produces the
    protocol error the 411 check exists to avoid.
    """
    chunk = b"x" * 8192
    delivered = 0

    async def receive():
        nonlocal delivered
        delivered += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def app(scope, receive_, send_):
        while True:  # a route reading its body, as Starlette would
            await receive_()

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat",
        "headers": [(b"content-length", b"100")],  # the lie
    }

    async def send(_message):  # pragma: no cover - never reached
        raise AssertionError("the application should not have produced a response")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(security.BodySizeLimitMiddleware(app)(scope, receive, send))

    assert exc.value.status_code == 413
    # Refused promptly, not after absorbing an unbounded upload.
    assert delivered <= security.MAX_JSON_BODY_BYTES + len(chunk)


def test_the_upload_path_gets_the_larger_ceiling():
    """Sized just above the image endpoint's own cap, so the transport limit
    never fires first and reports the wrong reason."""
    assert security.body_limit_for("/api/news-sentiment/analyze-image") > (
        security.MAX_JSON_BODY_BYTES
    )
    assert security.body_limit_for("/api/chat") == security.MAX_JSON_BODY_BYTES


def test_an_image_within_its_own_cap_passes_the_transport_limit(monkeypatch):
    """A 2MB upload is far over the JSON ceiling and must still be accepted, or
    the cap has broken the feature it was meant to leave alone."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    big_but_legal = b"\x89PNG\r\n" + b"\x00" * (2 * 1024 * 1024)
    response = client.post(
        "/api/news-sentiment/analyze-image",
        files={"image": ("big.png", big_but_legal, "image/png")},
    )
    # 503 (no provider key) or 502 both mean it got past the transport limit.
    assert response.status_code != 413


def test_reads_are_not_inspected(monkeypatch):
    """Only methods that carry a body are checked; a GET passes straight through."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    assert client.get("/api/assets").status_code == 200


def test_a_malformed_content_length_does_not_crash(monkeypatch):
    """An unparseable header falls back to counting rather than raising."""
    monkeypatch.delenv(security.TOKEN_ENV, raising=False)
    assert security._content_length({"headers": [(b"content-length", b"abc")]}) is None


def test_health_publishes_the_body_ceilings():
    status = security_status()
    assert status["max_body_bytes"] == security.MAX_JSON_BODY_BYTES
    assert status["max_upload_bytes"] == security.MAX_UPLOAD_BODY_BYTES
