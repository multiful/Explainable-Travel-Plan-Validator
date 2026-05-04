"""AlternativesFinder 유닛 테스트."""
from __future__ import annotations

import pytest

from src.data.models import AlternativePOI, HardFail, POI
from src.validation.alternatives import AlternativesFinder


def _poi(
    name: str,
    lat: float = 37.5,
    lng: float = 127.0,
    category: str = "14",
    poi_id: str | None = None,
) -> POI:
    return POI(
        poi_id=poi_id or name,
        name=name,
        lat=lat,
        lng=lng,
        open_start="09:00",
        open_end="18:00",
        duration_min=60,
        category=category,
    )


def _hardfail(poi_name: str | None) -> HardFail:
    return HardFail(
        fail_type="OPERATING_HOURS_CONFLICT",
        message="test",
        evidence="test",
        confidence="High",
        poi_name=poi_name,
    )


class TestFindAlternatives:
    def test_returns_nearby_same_category(self):
        pool = [
            _poi("B", lat=37.502, lng=127.0, category="14"),
            _poi("C", lat=37.6,   lng=127.0, category="12"),
        ]
        finder = AlternativesFinder(poi_pool=pool)
        failed = _poi("A", lat=37.5, lng=127.0, category="14")
        alts = finder.find_alternatives(failed)
        assert alts[0].name == "B"

    def test_excludes_failed_poi_itself(self):
        pool = [_poi("A", lat=37.500, lng=127.0)]
        finder = AlternativesFinder(poi_pool=pool)
        failed = _poi("A", lat=37.500, lng=127.0)
        alts = finder.find_alternatives(failed)
        assert all(a.name != "A" for a in alts)

    def test_respects_max_alternatives(self):
        pool = [_poi(f"P{i}", lat=37.5 + i * 0.001, lng=127.0) for i in range(10)]
        finder = AlternativesFinder(poi_pool=pool, max_alternatives=2)
        failed = _poi("X", lat=37.5, lng=127.0)
        alts = finder.find_alternatives(failed)
        assert len(alts) <= 2

    def test_respects_search_radius(self):
        far_poi = _poi("Far", lat=38.5, lng=127.0)  # ~111 km away
        pool = [far_poi]
        finder = AlternativesFinder(poi_pool=pool, max_search_km=10.0)
        failed = _poi("X", lat=37.5, lng=127.0)
        alts = finder.find_alternatives(failed)
        assert alts == []

    def test_distance_km_is_correct(self):
        pool = [_poi("B", lat=37.509, lng=127.0)]  # ~1 km north
        finder = AlternativesFinder(poi_pool=pool)
        failed = _poi("A", lat=37.500, lng=127.0)
        alts = finder.find_alternatives(failed)
        assert len(alts) == 1
        assert alts[0].distance_km < 2.0

    def test_same_category_sorted_before_different(self):
        pool = [
            _poi("Same", lat=37.510, lng=127.0, category="14"),  # farther, same cat
            _poi("Diff", lat=37.502, lng=127.0, category="12"),  # closer, diff cat
        ]
        finder = AlternativesFinder(poi_pool=pool)
        failed = _poi("A", lat=37.5, lng=127.0, category="14")
        alts = finder.find_alternatives(failed)
        assert alts[0].name == "Same"


class TestBuildAlternativesMap:
    def test_maps_failed_poi_to_alternatives(self):
        failed_poi = _poi("A", lat=37.5, lng=127.0, category="14")
        nearby = _poi("B", lat=37.502, lng=127.0, category="14")
        finder = AlternativesFinder(poi_pool=[nearby, failed_poi])
        fails = [_hardfail("A")]
        # allow_substitution=True required (Minimal Interference: substitution is opt-in)
        result = finder.build_alternatives_map(fails, [failed_poi], allow_substitution=True)
        assert "A" in result
        assert result["A"][0].name == "B"

    def test_default_no_substitution(self):
        failed_poi = _poi("A", lat=37.5, lng=127.0, category="14")
        nearby = _poi("B", lat=37.502, lng=127.0, category="14")
        finder = AlternativesFinder(poi_pool=[nearby, failed_poi])
        fails = [_hardfail("A")]
        result = finder.build_alternatives_map(fails, [failed_poi])
        assert result == {}

    def test_skips_none_poi_name(self):
        finder = AlternativesFinder(poi_pool=[])
        fails = [_hardfail(None)]
        result = finder.build_alternatives_map(fails, [])
        assert result == {}

    def test_no_duplicate_keys(self):
        failed_poi = _poi("A")
        finder = AlternativesFinder(poi_pool=[])
        fails = [_hardfail("A"), _hardfail("A")]
        result = finder.build_alternatives_map(fails, [failed_poi], allow_substitution=True)
        assert list(result.keys()).count("A") == 1

    def test_excludes_plan_pois_from_alternatives(self):
        plan = [_poi("A", lat=37.5, lng=127.0), _poi("B", lat=37.502, lng=127.0)]
        finder = AlternativesFinder(poi_pool=plan)
        fails = [_hardfail("A")]
        result = finder.build_alternatives_map(fails, plan)
        # B is in plan — should not appear as alternative
        alts_names = [a.name for a in result.get("A", [])]
        assert "B" not in alts_names
