"""제주 음식점 근접 검색 카탈로그 — data/jeju_places.csv 기반.

RepairEngine의 Outlier Deletion 제안 시, 삭제 후보 자리를 대신할 근처
음식점을 추천하기 위한 근거 데이터. 외부 API 호출 없이 로컬 CSV만 사용한다.

CLAUDE.md 규칙:
  - 모듈 간 데이터는 Pydantic 모델(AlternativePOI)로만 주고받는다.
"""
from __future__ import annotations

import csv
from pathlib import Path

from src.data.models import AlternativePOI
from src.utils.geo import haversine_km

_RESTAURANT_CODE = "FD"


def _normalize(name: str) -> str:
    return name.strip().lower()


class RestaurantCatalog:
    """카테고리=음식점(FD) 장소의 좌표 근접 검색."""

    def __init__(self, restaurants: list[dict]) -> None:
        self._restaurants = restaurants

    @classmethod
    def from_csv(cls, path: Path) -> RestaurantCatalog:
        restaurants: list[dict] = []
        if not path.exists():
            return cls(restaurants)
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("대분류코드") != _RESTAURANT_CODE:
                    continue
                name = (row.get("상호명") or "").strip()
                if not name:
                    continue
                try:
                    lat, lng = float(row["위도"]), float(row["경도"])
                except (ValueError, TypeError, KeyError):
                    continue
                restaurants.append({"name": name, "lat": lat, "lng": lng})
        return cls(restaurants)

    @classmethod
    def from_default(cls) -> RestaurantCatalog:
        return cls.from_csv(Path("data/jeju_places.csv"))

    def nearby(
        self,
        lat: float,
        lng: float,
        exclude_name: str = "",
        limit: int = 3,
        radius_km: float = 2.0,
    ) -> list[AlternativePOI]:
        """반경 내 가장 가까운 음식점 목록 (거리순, exclude_name 자기 자신 제외)."""
        excl = _normalize(exclude_name)
        candidates = []
        for r in self._restaurants:
            if _normalize(r["name"]) == excl:
                continue
            dist = haversine_km(lat, lng, r["lat"], r["lng"])
            if dist <= radius_km:
                candidates.append((dist, r))
        candidates.sort(key=lambda c: c[0])
        return [
            AlternativePOI(name=r["name"], distance_km=round(dist, 2), category="39", lat=r["lat"], lng=r["lng"])
            for dist, r in candidates[:limit]
        ]
