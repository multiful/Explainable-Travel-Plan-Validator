"""Tests for src/utils/geo.py (TDD)."""
from __future__ import annotations

import pytest

from src.data.models import POI
from src.utils.geo import build_dist_cache, get_travel_min, haversine_km, nn_heuristic_km


def make_poi(poi_id: str, lat: float, lng: float) -> POI:
    return POI(
        poi_id=poi_id, name=poi_id,
        lat=lat, lng=lng,
        open_start="09:00", open_end="18:00",
        duration_min=60,
    )


# ---------------------------------------------------------------------------
# haversine_km
# ---------------------------------------------------------------------------

class TestHaversineKm:
    def test_same_point_is_zero(self):
        assert haversine_km(37.5, 127.0, 37.5, 127.0) == pytest.approx(0.0, abs=1e-9)

    def test_known_distance(self):
        # 서울(37.5665, 126.9780) ~ 인천공항(37.4602, 126.4407) ≈ 52 km
        d = haversine_km(37.5665, 126.9780, 37.4602, 126.4407)
        assert 48.0 < d < 56.0

    def test_symmetric(self):
        d1 = haversine_km(37.5, 127.0, 33.5, 126.5)
        d2 = haversine_km(33.5, 126.5, 37.5, 127.0)
        assert d1 == pytest.approx(d2, rel=1e-9)

    def test_positive(self):
        assert haversine_km(37.0, 127.0, 38.0, 128.0) > 0


# ---------------------------------------------------------------------------
# build_dist_cache
# ---------------------------------------------------------------------------

class TestBuildDistCache:
    def test_all_pairs_present(self):
        pois = [make_poi(str(i), 37.5 + i * 0.1, 127.0) for i in range(4)]
        cache = build_dist_cache(pois)
        for i in range(4):
            for j in range(4):
                if i != j:
                    assert (i, j) in cache

    def test_no_self_pairs(self):
        pois = [make_poi(str(i), 37.5 + i * 0.1, 127.0) for i in range(3)]
        cache = build_dist_cache(pois)
        for i in range(3):
            assert (i, i) not in cache

    def test_values_match_haversine(self):
        pois = [
            make_poi("A", 37.5, 127.0),
            make_poi("B", 37.6, 127.1),
        ]
        cache = build_dist_cache(pois)
        expected = haversine_km(37.5, 127.0, 37.6, 127.1)
        assert cache[(0, 1)] == pytest.approx(expected, rel=1e-9)
        assert cache[(1, 0)] == pytest.approx(expected, rel=1e-9)

    def test_single_poi_empty_cache(self):
        pois = [make_poi("A", 37.5, 127.0)]
        cache = build_dist_cache(pois)
        assert cache == {}

    def test_empty_list_empty_cache(self):
        assert build_dist_cache([]) == {}


# ---------------------------------------------------------------------------
# nn_heuristic_km
# ---------------------------------------------------------------------------

class TestNnHeuristicKm:
    def test_single_poi_returns_zero(self):
        pois = [make_poi("A", 37.5, 127.0)]
        assert nn_heuristic_km(pois) == 0.0

    def test_two_pois_returns_distance(self):
        pois = [make_poi("A", 37.5, 127.0), make_poi("B", 37.6, 127.0)]
        expected = haversine_km(37.5, 127.0, 37.6, 127.0)
        assert nn_heuristic_km(pois) == pytest.approx(expected, rel=1e-6)

    def test_nn_le_actual_for_suboptimal(self):
        # 지그재그 순서 A→D→B→C 는 비효율적 → NN 결과는 더 짧아야 함
        pois = [
            make_poi("A", 37.5, 127.0),
            make_poi("D", 37.5, 127.5),
            make_poi("B", 37.5, 127.1),
            make_poi("C", 37.5, 127.4),
        ]
        actual_km = (
            haversine_km(37.5, 127.0, 37.5, 127.5)
            + haversine_km(37.5, 127.5, 37.5, 127.1)
            + haversine_km(37.5, 127.1, 37.5, 127.4)
        )
        nn_km = nn_heuristic_km(pois)
        assert nn_km <= actual_km

    def test_cache_gives_same_result(self):
        pois = [make_poi(str(i), 37.5 + i * 0.05, 127.0 + i * 0.03) for i in range(5)]
        cache = build_dist_cache(pois)
        assert nn_heuristic_km(pois, cache) == pytest.approx(nn_heuristic_km(pois), rel=1e-9)

    def test_collinear_optimal_order_matches_nn(self):
        # 일렬로 나열된 POI를 순서대로 방문 → NN과 동일
        pois = [make_poi(str(i), 37.5, 127.0 + i * 0.1) for i in range(4)]
        actual_km = sum(
            haversine_km(37.5, 127.0 + i * 0.1, 37.5, 127.0 + (i + 1) * 0.1)
            for i in range(3)
        )
        assert nn_heuristic_km(pois) == pytest.approx(actual_km, rel=1e-6)


# ---------------------------------------------------------------------------
# get_travel_min
# ---------------------------------------------------------------------------

class TestGetTravelMin:
    def test_uses_matrix_when_available(self):
        origin = make_poi("A", 37.5, 127.0)
        dest = make_poi("B", 38.0, 128.0)  # far away
        matrix = {0: {1: {"travel_min": 30.0}}}
        assert get_travel_min(matrix, 0, 1, origin, dest) == 30.0

    def test_haversine_fallback_when_no_matrix(self):
        origin = make_poi("A", 37.5, 127.0)
        dest = make_poi("B", 37.6, 127.0)
        km = haversine_km(37.5, 127.0, 37.6, 127.0)
        expected_min = km / (22.0 / 60.0)
        result = get_travel_min({}, 0, 1, origin, dest)
        assert result == pytest.approx(expected_min, rel=1e-6)

    def test_cache_fallback_when_no_matrix(self):
        origin = make_poi("A", 37.5, 127.0)
        dest = make_poi("B", 37.6, 127.0)
        cache = {(0, 1): 10.0}  # 10km
        result = get_travel_min({}, 0, 1, origin, dest, dist_cache=cache)
        assert result == pytest.approx(10.0 / (22.0 / 60.0), rel=1e-6)

    def test_matrix_takes_priority_over_cache(self):
        origin = make_poi("A", 37.5, 127.0)
        dest = make_poi("B", 37.6, 127.0)
        matrix = {0: {1: {"travel_min": 20.0}}}
        cache = {(0, 1): 999.0}
        result = get_travel_min(matrix, 0, 1, origin, dest, dist_cache=cache)
        assert result == 20.0
