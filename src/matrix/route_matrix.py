"""운영 검증에 주입할 indexed 이동시간 행렬 서비스."""

from __future__ import annotations

import os
from pathlib import Path

from src.data.models import POI, Settings, VRPTWPlace
from src.utils.geo import haversine_km
from src.validation.kakao_matrix import KakaoMobilityMatrix
from src.validation.vrptw_engine import HaversineMatrix, TimeMatrix


class RouteMatrixService:
    """Kakao Mobility를 우선 사용하고 보정된 Haversine으로 폴백한다."""

    def __init__(self, provider: TimeMatrix, mode: str | None = None):
        self.provider = provider
        self._mode = mode or (
            "kakao" if isinstance(provider, KakaoMobilityMatrix) else "haversine_fallback"
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        cache_path: str | Path | None = None,
    ) -> RouteMatrixService:
        settings = settings or Settings()
        api_key = settings.kakao_mobility_key or settings.kakao_rest_api_key
        if not api_key:
            return cls(HaversineMatrix())

        if cache_path is None:
            cache_path = (
                Path("/tmp/qtrip/route_cache.json")
                if os.getenv("VERCEL") == "1"
                else Path(__file__).resolve().parents[2] / "data" / "route_cache.json"
            )
        return cls(KakaoMobilityMatrix(api_key=api_key, cache_path=cache_path))

    @property
    def uses_kakao(self) -> bool:
        return isinstance(self.provider, KakaoMobilityMatrix)

    @staticmethod
    def _to_vrptw_place(poi: POI) -> VRPTWPlace:
        return VRPTWPlace(
            name=poi.name,
            lat=poi.lat,
            lng=poi.lng,
            open=poi.open_start,
            close=poi.open_end,
            stay_duration=poi.duration_min,
        )

    async def prepare(self, pois: list[POI]) -> None:
        """현재 요청의 모든 장소 쌍을 API/캐시에 미리 적재한다."""
        places = [self._to_vrptw_place(poi) for poi in pois]
        if hasattr(self.provider, "aprefetch_matrix") and len(places) > 1:
            await self.provider.aprefetch_matrix(places)  # type: ignore[attr-defined]

    def get_travel_time(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int:
        """VRPTWEngine이 사용하는 초 단위 이동시간."""
        return self.provider.get_travel_time(origin, destination)

    def get_travel_min(self, origin: POI, destination: POI) -> float:
        """기존 dict 기반 검증기가 사용하는 분 단위 이동시간."""
        return (
            self.provider.get_travel_time(
                self._to_vrptw_place(origin),
                self._to_vrptw_place(destination),
            )
            / 60.0
        )

    async def build(self, pois: list[POI]) -> dict[int, dict[int, dict[str, float | str]]]:
        places = [self._to_vrptw_place(poi) for poi in pois]
        await self.prepare(pois)

        mode = self._mode
        matrix: dict[int, dict[int, dict[str, float | str]]] = {}
        for i, origin in enumerate(places):
            for j, destination in enumerate(places):
                if i == j:
                    continue
                seconds = self.provider.get_travel_time(origin, destination)
                matrix.setdefault(i, {})[j] = {
                    "travel_min": seconds / 60.0,
                    "distance_km": haversine_km(
                        origin.lat,
                        origin.lng,
                        destination.lat,
                        destination.lng,
                    ),
                    "mode": mode,
                }
        return matrix
