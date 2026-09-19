"""Chatbot API routes.

A single proxy to the Featherless AI assistant: the dashboard snapshots its
active widget state into ``page_json`` and the backend forwards that plus the
user's question to Qwen3-8B. The provider is the only network call here — the
platform itself stays offline/reproducible.

Error mapping matches the rest of the API: a missing key is a configuration
problem (503), while provider/network failures surface as 502 so the dashboard
can distinguish "set up the key" from "the model is down".
"""
from __future__ import annotations

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..chat import ChatKeyError, ChatProviderError, chat_completion

router = APIRouter(prefix="/chat", tags=["chatbot"])


# ---------------------------------------------------------------- models


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    """Dashboard state + the user's question, proxied to Featherless AI.

    ``page_json`` is assembled by the dashboard from the active widgets; the
    backend treats it as opaque context for the model.
    """

    page_json: dict = Field(default_factory=dict)
    user_prompt: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)


# ---------------------------------------------------------------- assistant


@router.post("")
def post_chat(body: ChatIn) -> dict:
    """Proxy the dashboard state + question to the Featherless AI assistant."""
    try:
        reply = chat_completion(
            body.page_json,
            body.user_prompt,
            [m.model_dump() for m in body.history],
        )
    except ChatKeyError as exc:
        raise HTTPException(503, str(exc)) from None
    except ChatProviderError as exc:
        raise HTTPException(502, f"Featherless API ({exc.status}): {exc}") from None
    except requests.RequestException as exc:
        raise HTTPException(502, f"Featherless API unreachable: {exc}") from None
    return {"reply": reply}