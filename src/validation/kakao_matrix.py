"""카카오 모빌리티 길찾기 API → TimeMatrix 어댑터 (httpx 기반).

VRPTW 엔진의 TimeMatrix 인터페이스를 구현해 즉시 swap-in 가능:

    from src.validation.kakao_matrix import KakaoMobilityMatrix
    from src.validation.vrptw_engine import VRPTWEngine

    matrix = KakaoMobilityMatrix.from_env(cache_path="data/route_cache.json")
    # 비동기 사전 로드 (FastAPI 라이프스팬 등에서 호출)
    await matrix.aprefetch_matrix(places)
    engine = VRPTWEngine(matrix=matrix)
    result = engine.validate(plan)

기능
----
1. 좌표쌍 캐시 (JSON 파일) — 동일 origin/destination 재호출 방지
2. 양방향 캐시 매칭 — A→B와 B→A 동일 거리로 처리
3. 일일 한도(429/quota) 자동 감지 → Haversine 폴백
4. 호출 통계 (hit/miss/api_call/fallback) 추적
5. 환경변수 KAKAO_MOBILITY_KEY (없으면 KAKAO_REST_API_KEY 폴백)
6. async aprefetch_matrix: httpx.AsyncClient로 N×N 쌍 비동기 사전 로드
   (get_travel_time은 동기 유지 — VRPTWEngine/OR-Tools 호환)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from src.data.models import Settings, VRPTWPlace
from src.validation.vrptw_engine import HaversineMatrix, TimeMatrix

KAKAO_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"

DEFAULT_TIMEOUT_SEC: float = 5.0
DEFAULT_SLEEP_BETWEEN: float = 0.05  # 초당 ~20회
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BACKOFF: float = 2.0


class KakaoMobilityMatrix(TimeMatrix):
    """카카오 모빌리티 길찾기 API 기반 TimeMatrix.

    캐시 키: 'lng1,lat1|lng2,lat2' (소수점 4자리 = 약 11m 정밀도).
    is_quota_exhausted=True 가 되면 이후 모든 호출은 Haversine 폴백.
    cache_path=None 이면 메모리만 사용 (일회성 검증).

    동기 get_travel_time은 캐시 조회 + Haversine 폴백만 수행.
    실제 API 호출은 비동기 aprefetch_matrix / _acall_kakao를 통해서만 발생.
    """

    def __init__(
        self,
        api_key: str,
        cache_path: str | Path | None = None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        sleep_between: float = DEFAULT_SLEEP_BETWEEN,
        max_retries: int = DEFAULT_MAX_RETRIES,
        save_every: int = 50,
    ) -> None:
        if not api_key:
            raise ValueError(
                "Kakao API key 누락. .env에 KAKAO_MOBILITY_KEY 또는 "
                "KAKAO_REST_API_KEY를 설정하세요."
            )
        self._api_key = api_key
        self._cache_path = Path(cache_path) if cache_path else None
        self._timeout = timeout_sec
        self._sleep = sleep_between
        self._max_retries = max_retries
        self._save_every = save_every

        self._cache: dict[str, int] = self._load_cache()
        self._fallback = HaversineMatrix()
        self._quota_exhausted = False
        self._stats: dict[str, int] = {
            "cache_hit": 0,
            "api_success": 0,
            "api_fail": 0,
            "fallback": 0,
        }
        self._dirty_count = 0

    # ── 팩토리 ───────────────────────────────────────────────────────────
    @classmethod
    def from_env(
        cls,
        cache_path: str | Path | None = None,
        env_path: str | Path | None = None,
        **kwargs: Any,
    ) -> KakaoMobilityMatrix:
        """`.env`에서 KAKAO_MOBILITY_KEY (없으면 KAKAO_REST_API_KEY) 로드."""
        settings = Settings(_env_file=env_path) if env_path else Settings()
        key = settings.kakao_mobility_key or settings.kakao_rest_api_key
        return cls(api_key=key, cache_path=cache_path, **kwargs)

    # ── TimeMatrix 인터페이스 (동기) ──────────────────────────────────────
    def get_travel_time(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int:
        """캐시 조회 + Haversine 폴백. API 직접 호출 없음."""
        if origin.lat == destination.lat and origin.lng == destination.lng:
            return 0

        key_fwd = self._make_key(origin, destination)
        key_rev = self._make_key(destination, origin)
        if key_fwd in self._cache:
            self._stats["cache_hit"] += 1
            return self._cache[key_fwd]
        if key_rev in self._cache:
            self._stats["cache_hit"] += 1
            return self._cache[key_rev]

        self._stats["fallback"] += 1
        return self._fallback.get_travel_time(origin, destination)

    # ── 비동기 사전 로드 ─────────────────────────────────────────────────
    async def aprefetch_matrix(
        self,
        places: list[VRPTWPlace],
        concurrency: int = 5,
    ) -> None:
        """모든 POI 쌍의 이동시간을 비동기로 사전 로드한다.

        VRPTWEngine.validate() 호출 전에 await 해두면 get_travel_time이
        항상 캐시 히트되어 레이턴시 없이 동작한다.
        """
        pairs = [
            (places[i], places[j]) for i in range(len(places)) for j in range(len(places)) if i != j
        ]

        sem = asyncio.Semaphore(concurrency)

        async def fetch_one(origin: VRPTWPlace, dest: VRPTWPlace) -> None:
            async with sem:
                key_fwd = self._make_key(origin, dest)
                key_rev = self._make_key(dest, origin)
                if key_fwd in self._cache or key_rev in self._cache:
                    return
                if self._quota_exhausted:
                    return
                duration = await self._acall_kakao(origin, dest)
                if duration is not None:
                    self._cache[key_fwd] = duration
                    self._stats["api_success"] += 1
                    self._maybe_save_cache()

        await asyncio.gather(*[fetch_one(o, d) for o, d in pairs])
        if self._cache_path and self._dirty_count > 0:
            self.save_cache()

    # ── 비동기 API 호출 ──────────────────────────────────────────────────
    async def _acall_kakao(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int | None:
        """카카오 모빌리티 비동기 호출 (httpx.AsyncClient)."""
        headers = {"Authorization": f"KakaoAK {self._api_key}"}
        params = {
            "origin": f"{origin.lng},{origin.lat}",
            "destination": f"{destination.lng},{destination.lat}",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(1, self._max_retries + 1):
                try:
                    r = await client.get(KAKAO_DIRECTIONS_URL, headers=headers, params=params)
                    if r.status_code == 200:
                        return self._parse_duration(r.json())
                    if r.status_code == 429:
                        print("  [kakao-mobility] 429 — quota exhausted")
                        self._quota_exhausted = True
                        return None
                    if r.status_code in (401, 403):
                        raise RuntimeError(f"인증 오류 {r.status_code}")
                    await asyncio.sleep(DEFAULT_RETRY_BACKOFF**attempt)
                except httpx.RequestError as e:
                    if attempt < self._max_retries:
                        await asyncio.sleep(DEFAULT_RETRY_BACKOFF**attempt)
                    else:
                        print(f"  [kakao-mobility] 실패: {e}")

        self._stats["api_fail"] += 1
        return None

    # ── 동기 API 호출 (캐시 워밍업 스크립트용) ──────────────────────────
    def _call_kakao_sync(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int | None:
        """동기 API 호출 + 캐시 저장 + 통계 업데이트 (httpx.Client).

        캐시에 이미 있으면 API 호출 없이 캐시 값 반환.
        """
        key_fwd = self._make_key(origin, destination)
        key_rev = self._make_key(destination, origin)
        if key_fwd in self._cache:
            self._stats["cache_hit"] += 1
            return self._cache[key_fwd]
        if key_rev in self._cache:
            self._stats["cache_hit"] += 1
            return self._cache[key_rev]

        if self._quota_exhausted:
            return None

        headers = {"Authorization": f"KakaoAK {self._api_key}"}
        params = {
            "origin": f"{origin.lng},{origin.lat}",
            "destination": f"{destination.lng},{destination.lat}",
        }

        for attempt in range(1, self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    r = client.get(KAKAO_DIRECTIONS_URL, headers=headers, params=params)
                if r.status_code == 200:
                    duration = self._parse_duration(r.json())
                    if duration is not None:
                        self._cache[key_fwd] = duration
                        self._stats["api_success"] += 1
                        self._maybe_save_cache()
                    return duration
                if r.status_code == 429:
                    print("  [kakao-mobility] 429 — quota exhausted")
                    self._quota_exhausted = True
                    return None
                if r.status_code in (401, 403):
                    raise RuntimeError(f"인증 오류 {r.status_code}")
                time.sleep(DEFAULT_RETRY_BACKOFF**attempt)
            except httpx.RequestError as e:
                if attempt < self._max_retries:
                    time.sleep(DEFAULT_RETRY_BACKOFF**attempt)
                else:
                    print(f"  [kakao-mobility] 실패: {e}")

        self._stats["api_fail"] += 1
        return None

    @staticmethod
    def _parse_duration(data: dict) -> int | None:
        routes = data.get("routes", [])
        if not routes:
            return None
        sections = routes[0].get("sections", [])
        summary = routes[0].get("summary", {})
        if "duration" in summary:
            return int(summary["duration"])
        if sections:
            return int(sections[0].get("duration", 0))
        return None

    # ── 캐시 입출력 ──────────────────────────────────────────────────────
    def _make_key(self, origin: VRPTWPlace, destination: VRPTWPlace) -> str:
        return f"{origin.lng:.4f},{origin.lat:.4f}|{destination.lng:.4f},{destination.lat:.4f}"

    def _load_cache(self) -> dict[str, int]:
        if not self._cache_path or not self._cache_path.exists():
            return {}
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return {k: int(v) for k, v in data.items() if v is not None}
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  [warn] 캐시 로드 실패 ({self._cache_path}): {e}")
            return {}

    def _maybe_save_cache(self) -> None:
        self._dirty_count += 1
        if self._cache_path and self._dirty_count >= self._save_every:
            self.save_cache()

    def save_cache(self) -> None:
        if not self._cache_path:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        self._dirty_count = 0

    # ── 진단 ─────────────────────────────────────────────────────────────
    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @property
    def is_quota_exhausted(self) -> bool:
        return self._quota_exhausted
