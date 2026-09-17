"""API 요청 보호: 환경 기반 인증과 프로세스 로컬 레이트리밋."""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse

from src.data.models import Settings


class InMemoryRateLimiter:
    """단일 프로세스 개발/소규모 배포용 sliding-window 제한기."""

    def __init__(self) -> None:
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


_LIMITER = InMemoryRateLimiter()
_PROTECTED_PATHS = {"/api/parse/text", "/api/parse/document", "/api/validate"}


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def security_middleware(request: Request, call_next):
    """비용이 큰 API를 인증하고, 모든 API 요청에 기본 레이트리밋을 적용한다."""
    path = request.url.path
    if path.startswith("/api/") and request.method != "OPTIONS":
        settings = Settings()
        protected = path in _PROTECTED_PATHS
        token = settings.api_auth_token.strip()
        if settings.environment.lower() == "production" and not token:
            return JSONResponse(
                {"detail": "API_AUTH_TOKEN must be configured in production"},
                status_code=503,
            )
        token_required = settings.environment.lower() == "production" and bool(token)
        if protected and token_required:
            authorization = request.headers.get("Authorization", "")
            supplied = authorization.removeprefix("Bearer ").strip()
            expected = token
            if not expected or not secrets.compare_digest(supplied, expected):
                return JSONResponse({"detail": "인증이 필요합니다."}, status_code=401)

        limit = 5 if path == "/api/parse/document" else 30 if protected else 60
        if not _LIMITER.allow(f"{_client_key(request)}:{path}", limit):
            return JSONResponse(
                {"detail": "요청이 너무 많습니다. 잠시 후 다시 시도하세요."},
                status_code=429,
                headers={"Retry-After": "60"},
            )
    return await call_next(request)
