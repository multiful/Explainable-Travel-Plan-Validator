"""FastAPI 앱 진입점."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from src.api.router import router
from src.api.security import security_middleware
from src.data.models import Settings

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Travel Plan Validator",
    version="1.0.0",
    description="여행 계획 QA 검증 API",
)

_settings = Settings()
_cors_origins = [
    origin.strip() for origin in _settings.cors_allowed_origins.split(",") if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.middleware("http")(security_middleware)

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

    apis_configured = {
        "anthropic": bool(_settings.anthropic_api_key.strip()),
        "tour_api": bool(_settings.tour_api_key.strip()),
        "kakao_rest": bool(_settings.kakao_rest_api_key.strip()),
        "kakao_mobility": bool(_settings.kakao_mobility_key.strip()),
        "seoul_data": bool(_settings.seoul_data_api_key.strip()),
        "naver": bool(_settings.naver_api_key.strip()),
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

    ready = data_loaded.get("places", 0) > 0 and data_loaded.get("congestion_places", 0) > 0
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "version": app.version,
        "apis_configured": apis_configured,
        "data_loaded": data_loaded,
    }
