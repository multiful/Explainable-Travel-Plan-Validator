"""운영 검증용 indexed route matrix 서비스 테스트."""

import asyncio

from src.data.models import POI
from src.matrix.route_matrix import RouteMatrixService
from src.validation.vrptw_engine import HaversineMatrix


def _poi(name: str, lat: float, lng: float) -> POI:
    return POI(
        poi_id=name,
        name=name,
        lat=lat,
        lng=lng,
        open_start="09:00",
        open_end="18:00",
        duration_min=60,
        category="12",
    )


class FakeRouteProvider:
    def __init__(self):
        self.prefetched = False

    async def aprefetch_matrix(self, places):
        self.prefetched = True

    def get_travel_time(self, origin, destination):
        return 120 if origin.name != destination.name else 0


def test_build_uses_provider_seconds_as_minutes():
    provider = FakeRouteProvider()
    service = RouteMatrixService(provider=provider, mode="kakao")
    pois = [_poi("A", 37.5, 127.0), _poi("B", 37.51, 127.01)]

    matrix = asyncio.run(service.build(pois))

    assert provider.prefetched is True
    assert matrix[0][1]["travel_min"] == 2
    assert matrix[1][0]["travel_min"] == 2
    assert matrix[0][1]["mode"] == "kakao"


def test_haversine_provider_is_used_when_api_key_is_unavailable():
    service = RouteMatrixService(provider=HaversineMatrix())
    pois = [_poi("A", 37.5, 127.0), _poi("B", 37.51, 127.01)]

    matrix = asyncio.run(service.build(pois))

    assert matrix[0][1]["travel_min"] > 0
    assert matrix[0][1]["mode"] == "haversine_fallback"
