"""The capability boundary.

Most of this API is pure: it reads the committed snapshot, does arithmetic, and
returns numbers. Abusing those endpoints costs CPU and nothing else. A handful
are different -- they spend money on a metered provider key, send mail through
an authenticated account, or overwrite the snapshot that makes every published
figure reproducible. Those are the ones worth a fence, and this module is that
fence.

The controls are deliberately asymmetric, because the failure modes are:

``require_token``
    Opt-in. With no ``QMAFIB_TOKEN`` in the environment the guard is inert and
    ``/health`` says so out loud. The server binds ``127.0.0.1`` by default, so
    an unconfigured checkout is not exposed; forcing a secret on ``git clone``
    would buy nothing and cost every new run.

``rate_limit``
    Always on. It needs no configuration to be useful, and the cases it defends
    against -- draining a provider balance, hammering SMTP -- are exactly the
    ones nobody thinks to configure for.

    It is listed *before* ``require_token`` on every guarded route, which is the
    opposite of the obvious order and is deliberate. Dependencies resolve in
    sequence and the first to raise wins, so checking the token first would let
    a caller make unlimited *failed* attempts without ever touching their
    budget. Rate-limiting first means a guesser runs out of requests.

``recipient_allowed``
    Always on, and fails *closed*. Unconfigured, it permits only the mailbox the
    reports are sent *from*, i.e. you may mail the archive to yourself. That
    default removes the exfiltration primitive outright rather than leaving it
    one unset variable away.

What this is not: authentication. The token ships to the browser as a Vite
environment variable and is visible in devtools to anyone sitting at the
dashboard. It stops drive-by and scripted abuse of a tool bound to localhost.
It does not stop someone with access to the machine, and nothing here should be
read as claiming otherwise.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

# ---------------------------------------------------------------- configuration

TOKEN_HEADER = "X-QMAFIB-Token"
TOKEN_ENV = "QMAFIB_TOKEN"

# Per-route budgets: (requests, window seconds). Tuned to the cost of the thing
# being protected rather than to a uniform number -- a provider call costs real
# money, a robustness sweep costs 300ms of CPU, and an email costs SMTP standing.
BUDGETS: dict[str, tuple[int, float]] = {
    "refresh": (3, 300.0),       # snapshot rewrites: rare and deliberate
    "email": (3, 3600.0),        # SMTP reputation is not a renewable resource
    "chat": (20, 60.0),          # metered tokens, one per user question
    "sentiment": (10, 60.0),     # metered tokens, larger payloads
    "robustness": (30, 60.0),    # CPU only, so the budget is generous
}

# A robustness grid is a cartesian product, so its cost is multiplicative. The
# route validates two axes; without a cell cap a single request carrying
# 500x500 asks for 250,000 backtests.
MAX_GRID_CELLS = 400

# Concurrent heavy sweeps. Two keeps a demo responsive while one is running;
# more would simply queue on the GIL.
MAX_CONCURRENT_SWEEPS = 2
SWEEP_WAIT_SECONDS = 10.0

# Distinct rate-limit keys held in memory. Bounded so a spray of forged
# addresses cannot grow the table without limit.
MAX_TRACKED_CLIENTS = 4096


def configured_token() -> str | None:
    """The shared secret, or ``None`` when the token guard is disabled."""
    value = os.environ.get(TOKEN_ENV, "").strip()
    return value or None


# ---------------------------------------------------------------- token guard


def require_token(
    x_qmafib_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> None:
    """Reject the request unless it carries the configured shared secret.

    A no-op when no token is configured. Compared with ``compare_digest`` so the
    check does not leak the prefix of the secret through its timing.

    Both failures answer **401**, never 403. A wrong token is a bad credential,
    and retrying with the right one would succeed — which is what 401 means.
    403 is reserved here for a caller who got past this guard and is still not
    allowed to do the specific thing they asked for, i.e. mailing the archive to
    an unapproved address. Keeping them distinct is what lets the dashboard say
    "check your token" or "that address is not approved" instead of guessing.
    """
    expected = configured_token()
    if expected is None:
        return
    if x_qmafib_token is None:
        raise HTTPException(
            401,
            f"This endpoint has side effects and requires the {TOKEN_HEADER} "
            f"header. Set {TOKEN_ENV} in .env and VITE_QMAFIB_TOKEN to the "
            "same value.",
        )
    if not secrets.compare_digest(x_qmafib_token, expected):
        raise HTTPException(401, f"Invalid {TOKEN_HEADER}.")


# ---------------------------------------------------------------- rate limiting


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """Token bucket, keyed by route name and client address.

    A bucket rather than a fixed window because the burst behaviour is the
    point: a judge clicking Refresh twice in a row should work, and a script
    calling it two hundred times should not. Fixed windows allow a double-rate
    burst across the boundary; a bucket does not.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, name: str, client: str, now: float | None = None) -> float:
        """Consume one token. Returns 0.0 when allowed, else seconds to wait."""
        limit, window = BUDGETS[name]
        rate = limit / window
        now = time.monotonic() if now is None else now
        key = (name, client)

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= MAX_TRACKED_CLIENTS:
                    self._evict(now)
                bucket = _Bucket(tokens=float(limit), updated=now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated)
                bucket.tokens = min(float(limit), bucket.tokens + elapsed * rate)
                bucket.updated = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return 0.0
            return (1.0 - bucket.tokens) / rate

    def _evict(self, now: float) -> None:
        """Drop buckets that have refilled -- they carry no state worth keeping.

        Called with the lock held. A full bucket is indistinguishable from one
        that never existed, so forgetting it changes no decision.
        """
        stale = []
        for key, bucket in self._buckets.items():
            limit, window = BUDGETS[key[0]]
            refilled = bucket.tokens + (now - bucket.updated) * (limit / window)
            if refilled >= limit:
                stale.append(key)
        for key in stale:
            del self._buckets[key]
        if not stale:  # every bucket is live; drop the oldest to stay bounded
            oldest = min(self._buckets, key=lambda k: self._buckets[k].updated)
            del self._buckets[oldest]

    def reset(self) -> None:
        """Clear all state. For tests, which must not inherit a spent budget."""
        with self._lock:
            self._buckets.clear()


limiter = RateLimiter()


def client_key(request: Request) -> str:
    """Identify the caller for rate-limiting purposes.

    ``X-Forwarded-For`` is deliberately ignored. There is no trusted proxy in
    front of this server, so honouring it would let any caller pick their own
    bucket and opt out of the limit entirely.
    """
    return request.client.host if request.client else "unknown"


def rate_limit(name: str):
    """Build a dependency enforcing the named budget."""

    def dependency(request: Request) -> None:
        wait = limiter.check(name, client_key(request))
        if wait > 0.0:
            limit, window = BUDGETS[name]
            raise HTTPException(
                429,
                f"Rate limit exceeded: {limit} requests per {int(window)}s for "
                f"this endpoint. Retry in {wait:.0f}s.",
                headers={"Retry-After": str(max(1, int(wait + 0.5)))},
            )

    return dependency


# ---------------------------------------------------------------- sweep capacity

_sweep_slots = threading.BoundedSemaphore(MAX_CONCURRENT_SWEEPS)


class sweep_slot:
    """Context manager bounding concurrent parameter sweeps.

    Backtests are CPU-bound and synchronous, so FastAPI runs them in a worker
    thread. Without a bound, enough simultaneous sweeps starve every other
    endpoint -- including ``/health``, which is how a demo looks dead rather
    than busy.
    """

    def __enter__(self) -> None:
        if not _sweep_slots.acquire(timeout=SWEEP_WAIT_SECONDS):
            raise HTTPException(
                503,
                "Server busy: too many parameter sweeps in flight. Try again shortly.",
                headers={"Retry-After": "5"},
            )

    def __exit__(self, *exc: object) -> None:
        _sweep_slots.release()


def check_grid_size(grid: dict[str, list]) -> None:
    """Reject a grid whose cartesian product is larger than the cap."""
    cells = 1
    for values in grid.values():
        cells *= max(1, len(values))
    if cells > MAX_GRID_CELLS:
        raise HTTPException(
            422,
            f"Grid requests {cells} cells; the limit is {MAX_GRID_CELLS}. "
            "Each cell is a full backtest -- narrow the axes.",
        )


# ---------------------------------------------------------------- mail recipients


def allowed_recipients() -> set[str]:
    """Addresses the report may be sent to, lowercased.

    ``REPORT_EMAIL_ALLOWLIST`` is a comma-separated list. Unset, it falls back
    to the sending mailbox, so the feature keeps working for its intended use --
    mailing yourself the run output -- without being usable to mail it anywhere
    else.
    """
    raw = os.environ.get("REPORT_EMAIL_ALLOWLIST", "").strip()
    if raw:
        return {part.strip().lower() for part in raw.split(",") if part.strip()}
    fallback = (
        os.environ.get("SMTP_FROM", "").strip()
        or os.environ.get("SMTP_USER", "").strip()
    )
    return {fallback.lower()} if fallback else set()


def recipient_allowed(address: str) -> bool:
    """Whether the report may be mailed to ``address``.

    An entry beginning with ``@`` matches a whole domain; anything else must
    match the address exactly.
    """
    candidate = address.strip().lower()
    if not candidate:
        return False
    allowed = allowed_recipients()
    if candidate in allowed:
        return True
    domain = candidate.rpartition("@")[2]
    return bool(domain) and f"@{domain}" in allowed


# ---------------------------------------------------------------- introspection


def security_status() -> dict:
    """What is actually switched on, for ``/health``.

    The value of the token never appears here; only whether one is set. A status
    endpoint that quietly reports "secure" while the guard is inert is worse
    than no status endpoint at all.
    """
    recipients = allowed_recipients()
    return {
        "token_required": configured_token() is not None,
        "token_header": TOKEN_HEADER,
        "rate_limits": {name: f"{n}/{int(w)}s" for name, (n, w) in BUDGETS.items()},
        "max_grid_cells": MAX_GRID_CELLS,
        "report_recipients_configured": len(recipients),
    }
