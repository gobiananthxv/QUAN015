"""Gemini-powered financial news sentiment analysis.

One live ``google-genai`` call, driven by a single unified prompt that asks the
model to perform six stages in one pass:

1. extract the article (OCR when the input is an image),
2. map entities onto this platform's terms (Gold/Bitcoin/NVIDIA, indicators),
3. web-search causal dependencies,
4. extract numeric impact claims,
5. return a strict JSON dependency report,
6. synthesise the portfolio-level read.

The platform reads a committed market-data snapshot and this analyzer is the
only part of the app that talks to an external LLM — it goes out to Gemini
whenever an article is analysed, and it refuses loudly (HTTP 503) when no
``GEMINI_API_KEY`` is configured rather than falling back to canned answers.

The provider package is imported lazily behind a guard so the rest of the
quant layer (and the test suite) imports cleanly in a bare venv without an
LLM dependency installed.
"""
from __future__ import annotations

import json
import os
import re
import base64
import requests
from datetime import datetime, timezone
from typing import Any

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover - optional provider dependency
    genai = None
    genai_types = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional too
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv()

# Documented default model; override with GEMINI_MODEL when the deployed
# project uses a different flash line.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

MAX_TEXT_CHARS = 10_000
MAX_IMAGE_BYTES = 16 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

PLATFORM_TERMS = """\
PLATFORM TERMS & ASSETS:
- Assets (use these exact keys in every asset field): GOLD, BTC, NVDA
  - GOLD  = Gold Futures (GC=F), commodity
  - BTC   = Bitcoin (BTC-USD), crypto
  - NVDA  = NVIDIA (NVDA), equity
- Technical Indicators: SMA, EMA, Volatility, Correlation, Sharpe Ratio, Maximum Drawdown
- Strategy Types: SMA Crossover, EMA Trend, Momentum Strategy, Mean Reversion\
"""

UNIFIED_NEWS_ANALYSIS_PROMPT = f"""\
You are a quantitative financial news analyst for a multi-asset platform. Analyse the supplied news article in SIX stages, using web search to ground causal claims, and return ONE strict JSON object.

{PLATFORM_TERMS}

STAGE 1 — EXTRACT CONTENT
Identify the headline, publication date (use today's date if absent), and classify:
- sentiment: "bullish" | "bearish" | "neutral"
- color_psychology: the framing bias of the article ("green" for bullish tone, "red" for bearish tone, "neutral" otherwise)
- urgency_level: "high" | "medium" | "low"
- summary: one or two sentences of the market-relevant thesis.

STAGE 2 — EXTRACT ENTITIES
List assets (only GOLD/BTC/NVDA keys if mentioned, otherwise the asset names as written), indicators, events, and numeric_mentions as [{{"value", "context", "impact", "asset"}}].

STAGE 3 — WEB-SEARCH DEPENDENCIES
Search the web to find how this news moves our platform's assets:
- direct_dependencies: assets affected within 0-1 days. For each: index (0.0-1.0), correlation_strength (0.0-1.0), expected_change (e.g. "+5.5%"), confidence (0.0-1.0), chart_data_needed (lookback_days 5, include_current true, forecast_days 0).
- indirect_dependencies: causal chains resolving in 2-7 days. For each: source, chain as ordered strings like "Fed dovish signals -> Bond yields drop -> DXY weakens -> GOLD +0.8%", affected_assets, expected_timeline_days, confidence (0.0-1.0), chart_data_needed (lookback_days 5, include_current true, forecast_days 3).

STAGE 4 — NUMERIC EXTRACTION
Extract explicit numbers from the article and predict their market impact: predictions as [{{"mention", "asset_impact", "predicted_move", "timeframe", "probability"}}]. Example: "CPI at 4.2%" -> {{"mention": "CPI at 4.2%", "asset_impact": "GOLD", "predicted_move": "+1.5% to +2.5%", "timeframe": "2-3 days", "probability": 0.68}}.

STAGE 5 — RETURN DEPENDENCIES
Return the STRICT JSON object with exactly this shape (no extra keys, no markdown):

{{
  "article_metadata": {{
    "headline": string,
    "publication_date": string (YYYY-MM-DD),
    "sentiment": "bullish"|"bearish"|"neutral",
    "color_psychology": "green"|"red"|"neutral",
    "urgency_level": "high"|"medium"|"low",
    "summary": string
  }},
  "extracted_entities": {{
    "assets": [string],
    "indicators": [string],
    "events": [string],
    "numeric_mentions": [{{"value": string, "context": string, "impact": "high"|"medium"|"low", "asset": string}}]
  }},
  "direct_dependencies": {{
    "assets_affected": [
      {{
        "asset": "GOLD"|"BTC"|"NVDA",
        "impact": "bullish"|"bearish"|"neutral",
        "correlation_strength": 0.0-1.0,
        "expected_change": string,
        "confidence": 0.0-1.0,
        "chart_data_needed": {{"lookback_days": 5, "include_current": true, "forecast_days": 0}}
      }}
    ]
  }},
  "indirect_dependencies": {{
    "relationships": [
      {{
        "source": string,
        "chain": [string],
        "affected_assets": [string],
        "expected_timeline_days": int,
        "confidence": 0.0-1.0,
        "chart_data_needed": {{"lookback_days": 5, "include_current": true, "forecast_days": 3}}
      }}
    ]
  }},
  "numeric_predictions": {{
    "has_numeric_data": bool,
    "predictions": [
      {{"mention": string, "asset_impact": string, "predicted_move": string, "timeframe": string, "probability": 0.0-1.0}}
    ]
  }},
  "correlation_analysis": {{
    "portfolio_correlation_shift": "breakdown expected"|"strengthening"|"stable",
    "cross_asset_contagion_risk": 0.0-1.0,
    "diversification_impact": "positive"|"negative"|"neutral",
    "summary": string
  }}
}}

STAGE 6 — SYNTHESIS
The correlation_analysis.summary must be written at the portfolio level: what the article implies for cross-asset contagion and diversification, not just one ticker.

NEWS ARTICLE:
"""


class ApiKeyError(RuntimeError):
    """GEMINI_API_KEY is missing or the provider package is not installed."""


class AnalysisError(RuntimeError):
    """The provider call succeeded but produced unusable output."""


class NewsSentimentAnalyzer:
    """Analyse financial news through Gemini, text or image.

    The client is built lazily so constructing an analyzer never fails on the
    provider being configured; only an actual analysis does.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model or DEFAULT_MODEL
        self._client: Any = None

    @property
    def configured(self) -> bool:
        """True when a live analysis would reach the provider."""
        return bool(self.api_key) and genai is not None

    def _client_or_raise(self) -> Any:
        if not self.api_key:
            raise ApiKeyError(
                "GEMINI_API_KEY is not set. Add it to backend/.env or the environment."
            )
        if genai is None or genai_types is None:
            raise ApiKeyError("google-genai is not installed (pip install -r backend/requirements.txt)")
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    # ------------------------------------------------------------ analysis

    def analyze_news_text(self, text: str, provider: str = "google") -> dict:
        """Analyse a pasted article (≤ MAX_TEXT_CHARS characters)."""
        text = (text or "").strip()
        if not text:
            raise ValueError("Text is empty.")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(
                f"Text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}."
            )
        raw = self._generate(UNIFIED_NEWS_ANALYSIS_PROMPT + text + "\n\nAnalyse the article above.", provider=provider)
        return self._finalise(raw)

    def analyze_news_image(self, image_bytes: bytes, mime_type: str, provider: str = "google") -> dict:
        """Analyse a news screenshot (newspaper page, terminal, website).

        The image travels inline to Gemini — no intermediate file or upload.
        """
        if not image_bytes:
            raise ValueError("Image is empty.")
        if mime_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(
                f"Unsupported media type '{mime_type}'. Allowed: "
                f"{', '.join(sorted(ALLOWED_IMAGE_TYPES))}."
            )
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image is {len(image_bytes) // (1024 * 1024)}MB; the limit is "
                f"{MAX_IMAGE_BYTES // (1024 * 1024)}MB."
            )
        raw = self._generate(
            UNIFIED_NEWS_ANALYSIS_PROMPT
            + "\nAnalyse the news text visible in this image (OCR it first).",
            image_bytes=image_bytes,
            mime_type=mime_type,
            provider=provider,
        )
        return self._finalise(raw)

    # ------------------------------------------------------------ plumbing

    def _generate(
        self,
        prompt: str,
        image_bytes: bytes | None = None,
        mime_type: str | None = None,
        provider: str = "google",
    ) -> str:
        max_retries = 3
        backoff_factor = 2.0
        delay = 2.0

        enable_search = os.environ.get("GEMINI_SEARCH_GROUNDING", "false").lower() in ("true", "1", "yes")

        for attempt in range(max_retries + 1):
            try:
                if provider == "feather":
                    return self._call_feather(prompt, image_bytes, mime_type)
                
                # Pass the effective search state to _call_google
                return self._call_google(prompt, image_bytes, mime_type, enable_search=enable_search)
            except ApiKeyError:
                raise
            except Exception as exc:  # noqa: BLE001
                exc_str = str(exc)
                is_rate_limit = (
                    "429" in exc_str
                    or "RESOURCE_EXHAUSTED" in exc_str
                    or getattr(exc, "code", None) == 429
                    or getattr(exc, "status_code", None) == 429
                )

                if is_rate_limit and attempt < max_retries:
                    import time
                    time.sleep(delay)
                    delay *= backoff_factor
                    continue

                # Fallback: if search was enabled for Google and failed, try again without it (once)
                if provider == "google" and enable_search:
                    enable_search = False
                    continue

                raise AnalysisError(f"{provider.title()} request failed: {exc}") from None

    def _call_google(self, prompt: str, image_bytes: bytes | None, mime_type: str | None, enable_search: bool = False) -> str:
        client = self._client_or_raise()
        parts: list[Any] = [genai_types.Part(text=prompt)]
        if image_bytes is not None:
            parts.append(
                genai_types.Part(
                    inline_data=genai_types.Blob(data=image_bytes, mime_type=mime_type)
                )
            )

        tools = []
        if enable_search:
            tools.append(genai_types.Tool(google_search=genai_types.GoogleSearch()))

        config = genai_types.GenerateContentConfig(
            tools=tools if tools else None,
            response_mime_type="application/json",
            temperature=0.2,
        )

        response = client.models.generate_content(
            model=self.model,
            contents=[genai_types.Content(role="user", parts=parts)],
            config=config,
        )
        text = getattr(response, "text", None)
        if not text:
            raise AnalysisError("Gemini returned no content.")
        return text

    def _call_feather(self, prompt: str, image_bytes: bytes | None, mime_type: str | None) -> str:
        api_key = os.environ.get("api_key") or os.environ.get("FEATHERLESS_API_KEY")
        if not api_key:
            raise ApiKeyError("FEATHERLESS_API_KEY or api_key is not set.")

        model = os.environ.get("FEATHERLESS_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
        
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        if image_bytes:
            encoded = base64.b64encode(image_bytes).decode("utf-8")
            image_url = f"data:{mime_type};base64,{encoded}"
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {"url": image_url}
            })

        response = requests.post(
            "https://api.featherless.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": 0.2},
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        text = result["choices"][0]["message"]["content"]
        if not text:
            raise AnalysisError("Featherless returned no content.")
        return text

    def _finalise(self, raw: str) -> dict:
        payload = _as_json(raw)
        payload["_metadata"] = {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "gemini_model": self.model,
            "api_status": "success",
        }
        return payload


def _as_json(raw: str) -> dict:
    """Parse Gemini's reply as JSON, tolerating a ```json fence.

    Providers occasionally wrap their JSON in markdown even when asked not to;
    stripping a fence keeps one malformed wrapper from failing the whole call.
    """
    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisError(
            f"Gemini returned text that is not JSON (first 200 chars: {text[:200]!r})."
        ) from None
    if not isinstance(parsed, dict):
        raise AnalysisError("Gemini returned JSON that is not an object.")
    return parsed