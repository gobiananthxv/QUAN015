"""FastAPI application entry point.

    uvicorn app.main:app --reload --port 8000

One process, no gateway, no service mesh. The quant layer underneath does not
import FastAPI, so every calculation in this platform remains usable and
testable without a running server.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat_routes import router as chat_router
from .api.news_sentiment_routes import router as news_sentiment_router
from .api.routes import router
from .config import ASSETS

DISCLAIMER = (
    "Research and historical analysis only. Backtested performance is computed "
    "from past data and is not a prediction of future returns."
)

app = FastAPI(
    title="QMAFIB",
    description=(
        "Quantitative Multi-Asset Financial Intelligence & Backtesting Platform.\n\n"
        f"**{DISCLAIMER}**"
    ),
    version="1.0.0",
)

# The dashboard is served by Vite on a different port in development. Origins are
# listed explicitly rather than using "*", which would be a habit worth not
# forming even on a local-only tool.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(news_sentiment_router, prefix="/api")
app.include_router(chat_router, prefix="/api")


@app.get("/health")
def health() -> dict:
    """Liveness check, plus enough context to confirm the cache is warm."""
    return {"status": "ok", "assets": list(ASSETS), "disclaimer": DISCLAIMER}
