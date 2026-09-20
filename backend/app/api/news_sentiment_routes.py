"""News-sentiment API routes.

Three of the four endpoints are live LLM calls and therefore need
``GEMINI_API_KEY``. ``chart-data`` deliberately does **not**: it reads the same
committed market-data snapshot every other endpoint reads, so the dependency
charts in the dashboard are real price history, not model output, and work
offline.

``sentiment-history`` keeps an in-memory ring buffer of what has been analysed
in this process — the platform has no database, and the brief for this module
only asks for a history list, not persistence.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..analytics.indicators import ema, sma
from ..config import get_asset
from ..data.store import load_asset
from ..security import rate_limit, require_token
from ..news_sentiment_backend import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    MAX_TEXT_CHARS,
    AnalysisError,
    ApiKeyError,
    NewsSentimentAnalyzer,
)
from .serialise import clean

router = APIRouter(prefix="/news-sentiment", tags=["news sentiment"])

_analyzer = NewsSentimentAnalyzer()

_MAX_HISTORY = 100
_history: deque[dict] = deque(maxlen=_MAX_HISTORY)
_history_lock = threading.Lock()


# ---------------------------------------------------------------- models


class AnalyzeTextIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    provider: str = "google"


class ChartDataIn(BaseModel):
    asset: str
    lookback_days: int = Field(5, ge=1, le=365)
    include_current: bool = True
    forecast_days: int = Field(0, ge=0, le=30)


# ---------------------------------------------------------------- health


@router.get("/health")
def news_sentiment_health() -> dict:
    """Liveness plus whether a live analysis would be able to reach Gemini."""
    return clean(
        {
            "status": "ok",
            "api_key_configured": _analyzer.configured,
            "model": _analyzer.model,
        }
    )


# ---------------------------------------------------------------- analysis


@router.post(
    "/analyze-text",
    dependencies=[Depends(rate_limit("sentiment")), Depends(require_token)],
)
def analyze_text(body: AnalyzeTextIn) -> dict:
    """Analyse a pasted financial news article via Gemini.

    Guarded for the same reason as the chat proxy: every call spends a metered
    key that belongs to whoever is running the platform.
    """
    try:
        result = _analyzer.analyze_news_text(body.text, provider=body.provider)
    except ApiKeyError as exc:
        raise HTTPException(503, str(exc)) from None
    except AnalysisError as exc:
        raise HTTPException(502, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    _record(result)
    return clean(result)


@router.post(
    "/analyze-image",
    dependencies=[Depends(rate_limit("sentiment")), Depends(require_token)],
)
def analyze_image(
    image: UploadFile = File(...),
    provider: str = Query("google"),
) -> dict:
    """Analyse a news screenshot (newspaper, terminal, website) via Gemini OCR.

    The content-type allowlist and size cap below predate the capability
    boundary and stay where they are: they bound what reaches the provider,
    while the token and rate budget bound how often anything does.
    """
    content_type = image.content_type or "application/octet-stream"
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            400,
            f"Unsupported media type '{content_type}'. Allowed: "
            f"{', '.join(sorted(ALLOWED_IMAGE_TYPES))}.",
        )
    data = image.file.read()
    if not data:
        raise HTTPException(422, "Image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            413, f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit."
        )
    try:
        result = _analyzer.analyze_news_image(data, content_type, provider=provider)
    except ApiKeyError as exc:
        raise HTTPException(503, str(exc)) from None
    except AnalysisError as exc:
        raise HTTPException(502, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    _record(result)
    return clean(result)


# ---------------------------------------------------------------- chart data


@router.post("/chart-data")
def chart_data(body: ChartDataIn) -> dict:
    """Recent price history for an identified dependency asset.

    Sourced from the committed snapshot — SMA 20 and EMA 12 computed by the
    same analytics layer the rest of the platform uses, so the dependency
    charts and the Overview tab cannot disagree. ``forecast`` is always empty:
    this platform has no price-forecasting model, so it reports none rather
    than inventing one.
    """
    try:
        key = get_asset(body.asset).key
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None

    df = load_asset(key).tail(body.lookback_days)
    rows = [{"date": str(i.date()), "price": c} for i, c in df["close"].items()]
    sma_20 = sma(df["close"], 20).tail(len(df))
    ema_12 = ema(df["close"], 12).tail(len(df))
    return clean(
        {
            "asset": key,
            "dates": [r["date"] for r in rows],
            "prices": [r["price"] for r in rows],
            "sma_20": [None if _is_nan(v) else float(v) for v in sma_20.tolist()],
            "ema_12": [None if _is_nan(v) else float(v) for v in ema_12.tolist()],
            "forecast": [],
        }
    )


# ---------------------------------------------------------------- history


@router.get("/sentiment-history")
def sentiment_history(
    limit: int = Query(10, ge=1, le=100),
    asset: str | None = None,
) -> dict:
    """Recently analysed articles in this process (oldest first)."""
    with _history_lock:
        entries = list(_history)
    if asset:
        wanted = asset.upper()
        entries = [
            e
            for e in entries
            if any(a.upper() == wanted for a in (e.get("assets_mentioned") or []))
        ]
    return clean({"analyses": entries[-limit:], "total": len(entries)})


# ---------------------------------------------------------------- internal


def _is_nan(value: Any) -> bool:
    try:
        return value != value  # NaN inequality trick, avoids importing math
    except TypeError:
        return False


def _record(result: dict) -> None:
    meta = result.get("article_metadata") or {}
    entities = result.get("extracted_entities") or {}
    corr = result.get("correlation_analysis") or {}
    with _history_lock:
        _history.append(
            {
                "id": f"analysis_{int(time.time() * 1000)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "headline": meta.get("headline"),
                "sentiment": meta.get("sentiment"),
                "assets_mentioned": list(entities.get("assets") or []),
                "correlation_shift": corr.get("portfolio_correlation_shift"),
            }
        )