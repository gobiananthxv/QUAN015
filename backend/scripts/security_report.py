"""Phase 9 verification: the capability boundary.

    .venv/bin/python scripts/security_report.py          (macOS / Linux)
    .venv/Scripts/python.exe scripts/security_report.py  (Windows)

The test suite proves each control works. This gate asks a different and, as the
platform grows, more important question: **is every endpoint still classified?**

It reads the guards off the live application rather than restating them. Adding
a route that spends a provider key, mails something, or writes to disk without
deciding which side of the boundary it belongs on fails here — the failure mode
a passing test suite is blind to, because there is no test for an endpoint
nobody has thought about yet.

Runs entirely in-process against ``TestClient``. No server, no network, no
provider calls, consistent with every other gate in ``verify.sh``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import security
from app.main import app

TOKEN = "gate-token-not-a-real-secret"

# The classification. Every POST route must appear in exactly one of these, and
# an unlisted one is the failure this gate exists to produce.
#
# EFFECTFUL  reaches outside the process: spends a metered key, sends mail, or
#            overwrites the snapshot. Requires the shared secret AND a budget.
# METERED    pure computation, but unbounded enough to be worth a budget.
# PURE       reads the snapshot and returns arithmetic. Needs no guard.
EFFECTFUL = {
    "/api/data/refresh",
    "/api/report/send-email",
    "/api/chat",
    "/api/news-sentiment/analyze-text",
    "/api/news-sentiment/analyze-image",
}
METERED = {"/api/backtest/robustness"}
PURE = {
    "/api/backtest",
    "/api/backtest/compare",
    "/api/news-sentiment/chart-data",
}


def guards_on(route) -> tuple[bool, str | None]:
    """Read a route's declared guards straight off its dependency graph."""
    has_token = False
    budget = None
    for dep in getattr(route, "dependant", None).dependencies if route else []:
        call = getattr(dep, "call", None)
        if call is security.require_token:
            has_token = True
        tag = getattr(call, "_qmafib_budget", None)
        if tag is not None:
            budget = tag
    return has_token, budget


def main() -> int:
    warnings: list[str] = []
    client = TestClient(app)

    print("=" * 100)
    print("PHASE 9 - CAPABILITY BOUNDARY")
    print("=" * 100)

    # ------------------------------------------------ 1. classification
    print("\nEndpoint classification (read from the application, not restated)\n")
    print(f"  {'METHOD':7}{'PATH':46}{'CLASS':11}{'TOKEN':7}BUDGET")
    print("  " + "-" * 92)

    seen: set[str] = set()
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        if "POST" not in methods:
            continue
        seen.add(path)
        has_token, budget = guards_on(route)

        if path in EFFECTFUL:
            label = "effectful"
            if not has_token:
                warnings.append(f"{path} is effectful but carries no token guard")
            if budget is None:
                warnings.append(f"{path} is effectful but carries no rate budget")
        elif path in METERED:
            label = "metered"
            if budget is None:
                warnings.append(f"{path} is metered but carries no rate budget")
        elif path in PURE:
            label = "pure"
            if has_token or budget:
                warnings.append(
                    f"{path} is classified pure but carries a guard — the fence "
                    "is spreading onto endpoints that hold nothing"
                )
        else:
            label = "UNCLASSIFIED"
            warnings.append(
                f"{path} is a POST endpoint nobody has classified. Decide whether "
                "it reaches outside the process and add it to EFFECTFUL, METERED "
                "or PURE in this script."
            )

        print(
            f"  {'POST':7}{path:46}{label:11}"
            f"{('yes' if has_token else '-'):7}{budget or '-'}"
        )

    for path in (EFFECTFUL | METERED | PURE) - seen:
        warnings.append(f"{path} is classified here but no longer exists in the API")

    # ------------------------------------------------ 2. the guards bite
    print("\nRefusals, with a token configured\n")
    os.environ[security.TOKEN_ENV] = TOKEN
    security.limiter.reset()
    try:
        for path in sorted(EFFECTFUL):
            no_header = _post(client, path)
            wrong = _post(client, path, {security.TOKEN_HEADER: "wrong"})
            print(f"  {path:46}no header -> {no_header:<5}wrong token -> {wrong}")
            if no_header != 401:
                warnings.append(f"{path} answered {no_header} without a token, not 401")
            if wrong != 401:
                warnings.append(f"{path} answered {wrong} for a bad token, not 401")

        print("\nReads stay open with the strictest configuration\n")
        for path in (
            "/health",
            "/api/assets",
            "/api/strategies",
            "/api/ohlcv?asset=NVDA",
            "/api/metrics?asset=NVDA",
            "/api/panel",
        ):
            code = client.get(path).status_code
            print(f"  GET {path:44}{code}")
            if code != 200:
                warnings.append(
                    f"GET {path} answered {code} with a token set — the guard has "
                    "spread onto a read endpoint"
                )
    finally:
        os.environ.pop(security.TOKEN_ENV, None)

    # ------------------------------------------------ 3. the other controls
    print("\nRemaining controls\n")
    security.limiter.reset()

    budget, _ = security.BUDGETS["chat"]
    codes = [_post(client, "/api/chat", body={"bad": 1}) for _ in range(budget + 2)]
    throttled = codes[-1]
    print(f"  rate limit        {budget} allowed, then -> {throttled}")
    if throttled != 429:
        warnings.append(f"chat budget of {budget} did not throttle; got {throttled}")

    security.limiter.reset()
    grid = client.post(
        "/api/backtest/robustness",
        json={
            "asset": "NVDA",
            "strategy": "sma_crossover",
            "grid": {"fast": list(range(60)), "slow": list(range(60))},
        },
    ).status_code
    print(f"  grid cap          3600 cells (limit {security.MAX_GRID_CELLS}) -> {grid}")
    if grid != 422:
        warnings.append(f"an oversized grid answered {grid}, not 422")

    os.environ["REPORT_EMAIL_ALLOWLIST"] = "approved@example.com"
    try:
        security.limiter.reset()
        stranger = _post(
            client, "/api/report/send-email", body={"email": "attacker@evil.com"}
        )
        print(f"  mail allowlist    unapproved recipient -> {stranger}")
        if stranger != 403:
            warnings.append(f"an unapproved recipient answered {stranger}, not 403")
    finally:
        os.environ.pop("REPORT_EMAIL_ALLOWLIST", None)

    for name in ("REPORT_EMAIL_ALLOWLIST", "SMTP_FROM", "SMTP_USER"):
        os.environ.pop(name, None)
    if security.allowed_recipients():
        warnings.append("the recipient allowlist is not empty with nothing configured")
    print("  fail-closed       nothing configured -> 0 permitted recipients")

    security.limiter.reset()
    fat = b'{"user_prompt":"' + b"x" * (security.MAX_JSON_BODY_BYTES + 512) + b'"}'
    over = client.post(
        "/api/chat", content=fat, headers={"Content-Type": "application/json"}
    ).status_code
    undeclared = client.post(
        "/api/chat",
        content=(c for c in [b'{"user_prompt":"hi"}']),
        headers={"Content-Type": "application/json"},
    ).status_code
    print(f"  body cap          oversized -> {over}   undeclared length -> {undeclared}")
    if over != 413:
        warnings.append(f"an oversized body answered {over}, not 413")
    if undeclared != 411:
        warnings.append(f"an undeclared body answered {undeclared}, not 411")

    # ------------------------------------------------ 4. no secret leaks
    os.environ[security.TOKEN_ENV] = TOKEN
    try:
        leaked = TOKEN in client.get("/health").text
    finally:
        os.environ.pop(security.TOKEN_ENV, None)
    print(f"  /health           publishes guard state, token present in body -> {leaked}")
    if leaked:
        warnings.append("/health leaked the configured token")

    print("\n" + "=" * 100)
    if warnings:
        print(f"PHASE 9 - {len(warnings)} INVARIANT FAILURE(S):")
        for w in warnings:
            print(f"  ! {w}")
        return 1
    print(
        "PHASE 9 PASSED - every endpoint classified, guards refuse, reads stay open."
    )
    print("=" * 100)
    return 0


def _post(client: TestClient, path: str, headers: dict | None = None, body=None) -> int:
    """Send the smallest request that still reaches the guards."""
    if path.endswith("analyze-image"):
        return client.post(
            path,
            files={"image": ("a.png", b"\x89PNG\r\n", "image/png")},
            headers=headers,
        ).status_code
    payloads = {
        "/api/data/refresh": {"assets": [], "force": False},
        "/api/report/send-email": {"email": "nobody@example.com"},
        "/api/chat": {"page_json": {}, "user_prompt": "hi"},
        "/api/news-sentiment/analyze-text": {"text": "markets rose"},
    }
    return client.post(
        path, json=body if body is not None else payloads[path], headers=headers
    ).status_code


if __name__ == "__main__":
    raise SystemExit(main())
