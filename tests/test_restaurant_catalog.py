"""RestaurantCatalog 유닛 테스트 (실제 CSV I/O 없음 — 인메모리 데이터 사용)."""
from __future__ import annotations

from src.data.restaurant_catalog import RestaurantCatalog


def _catalog() -> RestaurantCatalog:
    return RestaurantCatalog([
        {"name": "가까운식당", "lat": 33.500, "lng": 126.500},   # ~0km
        {"name": "먼식당", "lat": 33.700, "lng": 126.700},        # 반경 밖
        {"name": "자기자신", "lat": 33.500, "lng": 126.500},
    ])


def test_nearby_returns_within_radius_sorted_by_distance():
    results = _catalog().nearby(33.5001, 126.5001, radius_km=2.0)
    names = [r.name for r in results]
    assert "가까운식당" in names
    assert "먼식당" not in names


def test_nearby_excludes_self():
    results = _catalog().nearby(33.500, 126.500, exclude_name="자기자신", radius_km=5.0)
    assert all(r.name != "자기자신" for r in results)


def test_nearby_empty_when_no_restaurants_in_radius():
    catalog = RestaurantCatalog([{"name": "먼식당", "lat": 33.700, "lng": 126.700}])
    assert catalog.nearby(33.5, 126.5, radius_km=2.0) == []
