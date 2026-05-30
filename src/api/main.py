"""FastAPI 앱 진입점."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from src.api.router import router

# .env → os.environ 로드 (uvicorn 직접 실행 시 환경변수 자동 주입)
_dotenv_path = Path(__file__).parent.parent.parent / ".env"
if _dotenv_path.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
    for line in _dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

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


@app.get("/manifest.json", include_in_schema=False)
async def manifest() -> Response:
    f = _STATIC_DIR / "manifest.json"
    if f.exists():
        return Response(f.read_text(encoding="utf-8"), media_type="application/json")
    return Response("{}", media_type="application/json")


@app.get("/service-worker.js", include_in_schema=False)
async def service_worker() -> Response:
    f = _STATIC_DIR / "service-worker.js"
    if f.exists():
        return Response(
            f.read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )
    return Response("", media_type="application/javascript")


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}
