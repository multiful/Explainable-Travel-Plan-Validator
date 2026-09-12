"""Redis 기반 TimeMatrix — REDIS_URL 환경변수로 자동 활성화.

KakaoMobilityMatrix의 drop-in 대체재:
  - REDIS_URL이 설정되어 있으면 Redis에서 캐시 읽기/쓰기
  - REDIS_URL이 없으면 `from_env()` 호출 시 None 반환 (활성화 안 됨)
  - redis-py 미설치 시에도 임포트 오류 없이 None 반환

키 형식: "travel:{lng1:.4f},{lat1:.4f}|{lng2:.4f},{lat2:.4f}" → TTL 없음 (영구 저장)
양방향 캐시: A→B 저장 시 B→A도 동일 값으로 저장.

사용 예:
    matrix = RedisTimeMatrix.from_env()
    if matrix is None:
        matrix = KakaoMobilityMatrix.from_env(cache_path="data/route_cache.json")
"""

from __future__ import annotations

import os
from pathlib import Path

from src.data.models import VRPTWPlace
from src.validation.vrptw_engine import HaversineMatrix, TimeMatrix

try:
    import redis as _redis_lib

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


_KEY_PREFIX = "travel:"


class RedisTimeMatrix(TimeMatrix):
    """Redis 기반 TimeMatrix.

    redis-py가 설치되어 있고 REDIS_URL이 유효할 때만 동작.
    get_travel_time은 항상 동기 (VRPTWEngine/OR-Tools 호환).
    Redis 장애 시 HaversineMatrix 자동 폴백.
    """

    def __init__(self, redis_url: str) -> None:
        if not _REDIS_AVAILABLE:
            raise RuntimeError("redis-py 미설치. `pip install redis` 후 사용하세요.")
        self._client = _redis_lib.from_url(redis_url, decode_responses=True)
        self._fallback = HaversineMatrix()
        self._stats: dict[str, int] = {
            "cache_hit": 0,
            "cache_miss": 0,
            "fallback": 0,
            "write": 0,
        }

    # ── 팩토리 ───────────────────────────────────────────────────────────
    @classmethod
    def from_env(
        cls,
        env_path: str | Path | None = None,
    ) -> RedisTimeMatrix | None:
        """REDIS_URL 환경변수가 있으면 인스턴스 반환, 없으면 None."""
        if env_path:
            cls._load_dotenv(Path(env_path))
        else:
            project_root = Path(__file__).resolve().parents[2]
            env_default = project_root / ".env"
            if env_default.exists():
                cls._load_dotenv(env_default)

        url = os.environ.get("REDIS_URL", "").strip()
        if not url:
            return None
        if not _REDIS_AVAILABLE:
            return None
        try:
            instance = cls(redis_url=url)
            instance._client.ping()
            return instance
        except Exception:
            return None

    @staticmethod
    def _load_dotenv(env_path: Path) -> None:
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    # ── TimeMatrix 인터페이스 ────────────────────────────────────────────
    def get_travel_time(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int:
        if origin.lat == destination.lat and origin.lng == destination.lng:
            return 0

        key_fwd = self._make_key(origin, destination)
        key_rev = self._make_key(destination, origin)

        try:
            val = self._client.get(key_fwd) or self._client.get(key_rev)
            if val is not None:
                self._stats["cache_hit"] += 1
                return int(val)
        except Exception:
            pass

        self._stats["fallback"] += 1
        return self._fallback.get_travel_time(origin, destination)

    def set_travel_time(
        self,
        origin: VRPTWPlace,
        destination: VRPTWPlace,
        seconds: int,
        bidirectional: bool = True,
    ) -> None:
        """캐시에 이동시간 저장 (초 단위)."""
        key_fwd = self._make_key(origin, destination)
        try:
            self._client.set(key_fwd, seconds)
            if bidirectional:
                key_rev = self._make_key(destination, origin)
                self._client.set(key_rev, seconds)
            self._stats["write"] += 1
        except Exception:
            pass

    # ── 유틸 ─────────────────────────────────────────────────────────────
    @staticmethod
    def _make_key(origin: VRPTWPlace, destination: VRPTWPlace) -> str:
        return (
            f"{_KEY_PREFIX}"
            f"{origin.lng:.4f},{origin.lat:.4f}"
            f"|{destination.lng:.4f},{destination.lat:.4f}"
        )

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def is_available(self) -> bool:
        try:
            self._client.ping()
            return True
        except Exception:
            return False
