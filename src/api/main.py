"""FastAPI 앱 진입점."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

# .env → os.environ 로드 (uvicorn 직접 실행 시 환경변수 자동 주입)
# router import보다 먼저 실행해야 한다 — router.py는 모듈 로드 시점에
# GraphRetriever.from_env() 등으로 즉시 환경변수를 읽는 싱글턴을 생성한다.
_dotenv_path = Path(__file__).parent.parent.parent / ".env"
if _dotenv_path.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
    for line in _dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

from src.api.router import router  # noqa: E402 — .env 로드 이후에 import해야 함

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
    """라이브니스 + 구성 진단.

    시크릿 값은 절대 노출하지 않고, 키 설정 여부(bool)와
    로딩된 데이터 건수만 반환한다. 심사 시 외부 API 연동 및
    데이터 적재 상태를 한 번에 확인하는 용도.
    """

    def _is_set(name: str) -> bool:
        return bool(os.environ.get(name, "").strip())

    apis_configured = {
        "anthropic": _is_set("ANTHROPIC_API_KEY"),
        "tour_api": _is_set("TOUR_API_KEY"),
        "kakao_rest": _is_set("KAKAO_REST_API_KEY"),
        "kakao_mobility": _is_set("KAKAO_MOBILITY_KEY"),
        "seoul_data": _is_set("SEOUL_DATA_API_KEY"),
        "naver": _is_set("NAVER_API_KEY"),
    }

    data_loaded: dict[str, int] = {}
    try:
        from src.api import router as _r

        data_loaded = {
            "places": len(_r._PLACE_LIST),
            "full_places": len(_r._FULL_PLACE_LIST),
            "congestion_places": len(_r._MONTHLY_CONG),
        }
    except Exception:  # pragma: no cover - 진단용, 실패해도 health 는 200
        data_loaded = {}

    return {
        "status": "ok",
        "version": app.version,
        "apis_configured": apis_configured,
        "data_loaded": data_loaded,
    }
