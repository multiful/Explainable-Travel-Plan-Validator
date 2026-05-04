"""가산점 엔진 — 웰니스·무장애 여행지 방문 보너스."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.data.models import POI
from src.utils.geo import haversine_km

WELLNESS_BONUS_PER_PLACE: int = 3
ACCESSIBILITY_BONUS_PER_PLACE: int = 5
BONUS_CAP: int = 20

ACCESSIBLE_PARTY_TYPES: frozenset[str] = frozenset({"아기동반", "어르신동반", "가족"})

# 좌표 매칭 반경 (km)
MATCH_RADIUS_KM: float = 0.3


@dataclass(frozen=True)
class BonusResult:
    wellness_bonus: int
    accessibility_bonus: int
    total_bonus: int
    wellness_matched: list[str]        # 매칭된 POI 이름 목록
    accessibility_matched: list[str]   # 매칭된 POI 이름 목록


@dataclass(frozen=True)
class _PlaceCoord:
    lat: float
    lng: float


class BonusEngine:
    """웰니스·무장애 장소 데이터셋 기반 가산점 계산기.

    from_dataset() 로 JSON 데이터셋을 로드하여 인스턴스 생성.
    External I/O 없음 (데이터셋은 build_poi_dataset.py로 사전 생성).
    """

    def __init__(
        self,
        wellness_coords: list[_PlaceCoord],
        barrier_free_coords: list[_PlaceCoord],
    ) -> None:
        self._wellness = wellness_coords
        self._barrier_free = barrier_free_coords

    @classmethod
    def from_dataset(
        cls,
        wellness_path: Path | str = "data/wellness_places.json",
        barrier_free_path: Path | str = "data/barrier_free_places.json",
    ) -> "BonusEngine":
        """로컬 JSON 데이터셋에서 로드. 파일 없으면 빈 엔진 반환."""
        wellness: list[_PlaceCoord] = []
        barrier_free: list[_PlaceCoord] = []

        wp = Path(wellness_path)
        if wp.exists():
            for item in json.loads(wp.read_text(encoding="utf-8")):
                lat = item.get("lat", 0.0)
                lng = item.get("lng", 0.0)
                if lat and lng:
                    wellness.append(_PlaceCoord(lat=float(lat), lng=float(lng)))

        bp = Path(barrier_free_path)
        if bp.exists():
            for item in json.loads(bp.read_text(encoding="utf-8")):
                lat = item.get("lat", 0.0)
                lng = item.get("lng", 0.0)
                if lat and lng:
                    barrier_free.append(_PlaceCoord(lat=float(lat), lng=float(lng)))

        return cls(wellness_coords=wellness, barrier_free_coords=barrier_free)

    def compute(
        self,
        pois: list[POI],
        party_type: str,
    ) -> BonusResult:
        """POI 목록에서 가산점 계산.

        - 웰니스 장소: 모든 party_type에 적용.
        - 무장애 장소: ACCESSIBLE_PARTY_TYPES에만 적용.
        """
        wellness_matched: list[str] = []
        accessibility_matched: list[str] = []

        for poi in pois:
            if _nearest_km(poi, self._wellness) <= MATCH_RADIUS_KM:
                wellness_matched.append(poi.name)
            if (
                party_type in ACCESSIBLE_PARTY_TYPES
                and _nearest_km(poi, self._barrier_free) <= MATCH_RADIUS_KM
            ):
                accessibility_matched.append(poi.name)

        wellness_bonus = min(
            len(wellness_matched) * WELLNESS_BONUS_PER_PLACE, BONUS_CAP
        )
        accessibility_bonus = min(
            len(accessibility_matched) * ACCESSIBILITY_BONUS_PER_PLACE, BONUS_CAP
        )
        total_bonus = min(wellness_bonus + accessibility_bonus, BONUS_CAP)

        return BonusResult(
            wellness_bonus=wellness_bonus,
            accessibility_bonus=accessibility_bonus,
            total_bonus=total_bonus,
            wellness_matched=wellness_matched,
            accessibility_matched=accessibility_matched,
        )


def _nearest_km(poi: POI, coords: list[_PlaceCoord]) -> float:
    """POI와 가장 가까운 좌표까지의 거리(km). coords가 비어있으면 inf 반환."""
    if not coords:
        return float("inf")
    return min(haversine_km(poi.lat, poi.lng, c.lat, c.lng) for c in coords)
