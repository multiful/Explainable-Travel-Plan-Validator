"""Hard Fail 발생 장소에 대한 대체 후보 탐색기 (Repair 보조 도구).

이 모듈은 '검증'이 아닌 '수리 제안'의 보조 도구이다.
표준 Repair 순서는 재배치 → 시간 조정 → 삭제이며, 장소 대체(substitution)는
최후 수단(opt-in)에 해당한다. build_alternatives_map()의 allow_substitution=True를
명시적으로 전달할 때만 결과를 반환한다.

외부 I/O 없음 — 입력으로 전달된 poi_pool에서만 탐색.

사용 예:
    finder = AlternativesFinder(poi_pool=nearby_pois, max_alternatives=3)
    # 표준: 재배치/삭제 우선, 대체 불가
    alternatives_map = finder.build_alternatives_map(hard_fails, plan_pois)
    # → {}
    # opt-in: 대체 허용
    alternatives_map = finder.build_alternatives_map(
        hard_fails, plan_pois, allow_substitution=True
    )
    # → {"경복궁": [AlternativePOI(name="창덕궁", ...), ...]}
"""
from __future__ import annotations

import math
from typing import Sequence

from src.data.models import AlternativePOI, HardFail, POI

_EARTH_R = 6371.0
_MAX_SEARCH_KM = 10.0   # 기본 탐색 반경


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


class AlternativesFinder:
    """Hard Fail POI를 대체할 후보 추천기.

    Args:
        poi_pool: 탐색 대상 전체 POI 풀 (TourAPI 등 외부에서 주입).
        max_alternatives: POI 하나당 최대 추천 수.
        max_search_km: 탐색 반경(km). 이 반경 내 POI만 후보로 삼음.
    """

    def __init__(
        self,
        poi_pool: Sequence[POI],
        max_alternatives: int = 3,
        max_search_km: float = _MAX_SEARCH_KM,
    ) -> None:
        self._pool = list(poi_pool)
        self._max = max_alternatives
        self._radius = max_search_km

    def find_alternatives(
        self,
        failed_poi: POI,
        exclude_names: set[str] | None = None,
    ) -> list[AlternativePOI]:
        """failed_poi와 같은 카테고리 중 가장 가까운 POI를 반환.

        같은 카테고리가 없으면 반경 내 모든 POI를 거리 순으로 반환.
        """
        exclude = exclude_names or set()
        candidates: list[tuple[float, POI]] = []

        for poi in self._pool:
            if poi.name == failed_poi.name or poi.name in exclude:
                continue
            dist = _haversine_km(failed_poi.lat, failed_poi.lng, poi.lat, poi.lng)
            if dist <= self._radius:
                candidates.append((dist, poi))

        # 같은 카테고리 우선 정렬 → 거리 순
        candidates.sort(key=lambda x: (x[1].category != failed_poi.category, x[0]))

        return [
            AlternativePOI(
                name=poi.name,
                distance_km=round(dist, 2),
                category=poi.category,
                lat=poi.lat,
                lng=poi.lng,
            )
            for dist, poi in candidates[: self._max]
        ]

    def build_alternatives_map(
        self,
        hard_fails: Sequence[HardFail],
        plan_pois: Sequence[POI],
        allow_substitution: bool = False,
    ) -> dict[str, list[AlternativePOI]]:
        """Hard Fail 목록 기반으로 POI 이름 → 대체 후보 딕셔너리 반환.

        Minimal Interference 원칙(재배치 → 시간조정 → 삭제)에 따라
        allow_substitution=False(기본값)이면 빈 dict를 반환한다.
        장소 대체는 호출자가 명시적으로 allow_substitution=True를 전달할 때만 수행된다.
        """
        if not allow_substitution:
            return {}

        plan_names = {p.name for p in plan_pois}
        poi_by_name: dict[str, POI] = {p.name: p for p in plan_pois}
        result: dict[str, list[AlternativePOI]] = {}

        for fail in hard_fails:
            if fail.poi_name is None or fail.poi_name in result:
                continue
            failed_poi = poi_by_name.get(fail.poi_name)
            if failed_poi is None:
                continue
            alts = self.find_alternatives(failed_poi, exclude_names=plan_names)
            result[fail.poi_name] = alts

        return result
