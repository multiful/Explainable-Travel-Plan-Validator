"""외부 장소 클라이언트를 조합하는 데이터 레이어 resolver."""

from __future__ import annotations

import re

from src.data.kakao_local import KakaoLocalClient
from src.data.models import ExternalPlaceResolution, KakaoPlace, Settings
from src.data.tour_api import TourAPIClient


def _normalize(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value or "", flags=re.UNICODE).lower()


class ExternalPlaceResolver:
    """TourAPI, Kakao 키워드 검색, 주소 지오코딩의 우선순위를 관리한다."""

    def __init__(
        self,
        kakao_client: KakaoLocalClient | None,
        tour_api_client: TourAPIClient | None,
    ) -> None:
        self._kakao = kakao_client
        self._tour_api = tour_api_client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ExternalPlaceResolver:
        return cls(
            KakaoLocalClient.from_env(),
            TourAPIClient.from_settings(settings),
        )

    def resolve(
        self,
        name: str,
        address: str = "",
        allow_tour_api: bool = False,
    ) -> ExternalPlaceResolution | None:
        normalized = _normalize(name)

        if allow_tour_api and self._tour_api is not None:
            candidates = self._tour_api.search_poi_sync(name, num_of_rows=5)
            candidate = next(
                (
                    poi
                    for poi in candidates
                    if _normalize(poi.name) == normalized or normalized in _normalize(poi.name)
                ),
                None,
            )
            if candidate is not None:
                return ExternalPlaceResolution(
                    lat=candidate.lat,
                    lng=candidate.lng,
                    category=candidate.category,
                    source="tour_api",
                    poi_id=candidate.poi_id,
                    open_start=candidate.open_start,
                    open_end=candidate.open_end,
                )

        if self._kakao is not None:
            candidate = self._kakao.search_keyword(name)
            if candidate is not None:
                return ExternalPlaceResolution(
                    lat=candidate.lat,
                    lng=candidate.lng,
                    category_name=candidate.category_name,
                    source="kakao",
                )

            if address:
                coordinates = self._kakao.geocode_address(address)
                if coordinates is not None:
                    return ExternalPlaceResolution(
                        lat=coordinates[0],
                        lng=coordinates[1],
                        source="geocode",
                    )

        return None

    def search_keyword_list(self, query: str, size: int = 15) -> list[KakaoPlace]:
        """카카오 장소 목록 검색을 data 레이어에서 수행한다."""
        if self._kakao is None:
            return []
        return self._kakao.search_keyword_list(query, size=size)
