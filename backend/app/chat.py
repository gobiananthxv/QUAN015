"""Featherless AI chat client backing the dashboard's assistant.

Kept import-free of FastAPI so it stays testable without a running server,
matching the layering rule the rest of the platform follows. The API key is read
from the environment (loaded from ``backend/.env`` by ``config``) under the
existing ``api_key`` name.
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests

API_URL = "https://api.featherless.ai/v1/chat/completions"
MODEL = "Qwen/Qwen3-8B"
MAX_TOKENS = 4096
TEMPERATURE = 0.2
TIMEOUT_SECONDS = 90

KEY_NAME = "api_key"

SYSTEM_PROMPT = (
    "You are an expert Quantitative Multi-Asset Financial Intelligence Assistant. "
    "You receive a JSON payload containing the user's active dashboard state "
    "(`page_json`) and their question (`user_prompt`).\n\n"
    "RULES:\n"
    "1. Never invent or hallucinate live market prices or unsupplied financial values — "
    "if a figure is not present in `page_json`, say so.\n"
    "2. Trace mathematical dependencies explicitly using the dependency graph when requested.\n"
    "3. Format your final answer using clear markdown with headings and structured bullet points.\n"
    "4. Resolve references like 'this chart', 'the graph above', 'drawdown', or metric "
    "queries against `page_json.charts`. Each chart has an `id`, `title`, `chart_type`, "
    "`formula` and a `result` object of computed metrics.\n\n"
    "DEPENDENCY GRAPH (signal-level DAG, as implemented in the platform):\n"
    "- Raw asset prices (open/high/low/close/volume) are the ONLY inputs. Nothing feeds back into them.\n"
    "- SMA(n): rolling mean of close over n bars. Direct consumers: crossover signals "
    "(signals = 1 while SMA_fast > SMA_slow), which drive positions. Positions drive "
    "portfolio returns and all return-based metrics.\n"
    "- EMA(span)/ROC/Bollinger z-score: indicator -> filter term inside a strategy's signal rule, "
    "same downstream chain (signals -> positions -> returns -> volatility/Sharpe/Sortino/drawdown).\n"
    "- Strategy parameters (fast/slow, span, band, window, threshold, entry_z/exit_z) affect ONLY "
    "which bars produce signals; they never change raw asset prices.\n"
    "- Portfolio metrics (total_return, CAGR, volatility, Sharpe, Sortino, Calmar, max_drawdown, "
    "exposure, win_rate, profit_factor) are all derived from the position-adjusted return stream.\n"
    "- Dates may carry a `period` (`start`/`end`) that restricts every figure — answer windowed "
    "metrics with respect to that window, not the full history.\n"
    "Answer dependency questions as: Direct = indicators/signals/positions; "
    "Indirect = portfolio return, volatility, Sharpe, drawdown; Unaffected = raw asset prices.\n\n"
    "QUERY HANDLING:\n"
    "- 'Based on this page, give the overall view' -> Summarise the status across every widget "
    "in `page_json.charts`. List each active chart with its key metric results and a one-line read.\n"
    "- 'Based on current {chart_name} chart, what is it trying to say?' -> Match the chart by "
    "`id`/`title`/`chart_type`. Return: Chart Meaning, Formula Interpretation, and a Current Status indicator.\n"
    "- 'What is {metric/term}?' -> Conceptual definition, the standard formula, and financial context "
    "using the value from `page_json` when present.\n"
    "- 'If SMA is increased by x, what happens to others?' -> Trace the DAG: Direct "
    "(signals/positions), Indirect (portfolio return, volatility, Sharpe), Unaffected (raw asset prices).\n"
    "- 'What are the dependencies of SMA?' -> Bulleted direct and indirect dependency tree.\n"
)


class ChatKeyError(Exception):
    """Raised when the Featherless API key is not configured."""


class ChatProviderError(Exception):
    """Raised when the upstream provider returns an error response."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def get_api_key() -> str | None:
    return os.environ.get(KEY_NAME)


def _user_content(page_json: dict, prompt: str) -> str:
    return json.dumps(
        {"page_json": page_json, "user_prompt": prompt},
        ensure_ascii=False,
        default=str,
    )


def chat_completion(
    page_json: dict[str, Any],
    prompt: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Send the dashboard state plus the user's question to Featherless.

    Returns the assistant's markdown reply. Raises :class:`ChatKeyError` when no
    API key is configured and :class:`ChatProviderError` (and
    ``requests.RequestException``) on upstream failures.
    """
    key = get_api_key()
    if not key:
        raise ChatKeyError(
            "Chatbot is not configured: no Featherless API key found. "
            f"Set `{KEY_NAME}=...` in backend/.env."
        )

    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        role = turn.get("role")
        if role in ("system", "user", "assistant"):
            messages.append({"role": role, "content": str(turn.get("content", ""))})
    messages.append({"role": "user", "content": _user_content(page_json, prompt)})

    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "messages": messages,
        },
        timeout=TIMEOUT_SECONDS,
    )

    if response.status_code != 200:
        detail = response.text[:500] or response.reason or "unknown error"
        raise ChatProviderError(response.status_code, detail)

    try:
        return response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ChatProviderError(502, "Provider returned an unparseable response") from None