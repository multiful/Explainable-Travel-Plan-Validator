"""FastAPI 앱 진입점."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.router import router

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Travel Plan Validator",
    version="1.0.0",
    description="여행 계획 QA 검증 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> str:
    html_file = _STATIC_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Travel Plan Validator</h1><p><a href='/docs'>API Docs</a></p>"


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}
