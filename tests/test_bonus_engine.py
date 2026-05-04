"""Tests for BonusEngine (TDD)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.data.models import POI
from src.scoring.bonus_engine import (
    ACCESSIBLE_PARTY_TYPES,
    ACCESSIBILITY_BONUS_PER_PLACE,
    BONUS_CAP,
    WELLNESS_BONUS_PER_PLACE,
    BonusEngine,
    _PlaceCoord,
)


def make_poi(poi_id: str = "1", lat: float = 37.5, lng: float = 127.0) -> POI:
    return POI(
        poi_id=poi_id, name=f"POI_{poi_id}",
        lat=lat, lng=lng,
        open_start="09:00", open_end="18:00",
        duration_min=60,
    )


def make_engine(
    wellness_coords: list[tuple[float, float]] | None = None,
    barrier_free_coords: list[tuple[float, float]] | None = None,
) -> BonusEngine:
    w = [_PlaceCoord(lat=lat, lng=lng) for lat, lng in (wellness_coords or [])]
    b = [_PlaceCoord(lat=lat, lng=lng) for lat, lng in (barrier_free_coords or [])]
    return BonusEngine(wellness_coords=w, barrier_free_coords=b)


# ---------------------------------------------------------------------------
# BonusEngine.compute() — wellness bonus
# ---------------------------------------------------------------------------

class TestWellnessBonus:
    def test_no_wellness_data_gives_zero(self):
        engine = make_engine(wellness_coords=[])
        pois = [make_poi("1", 37.5, 127.0)]
        result = engine.compute(pois, party_type="친구")
        assert result.wellness_bonus == 0

    def test_matching_poi_gives_bonus(self):
        engine = make_engine(wellness_coords=[(37.5, 127.0)])
        pois = [make_poi("1", 37.5, 127.0)]
        result = engine.compute(pois, party_type="친구")
        assert result.wellness_bonus == WELLNESS_BONUS_PER_PLACE

    def test_two_matching_pois_give_double_bonus(self):
        engine = make_engine(wellness_coords=[(37.5, 127.0), (37.6, 127.1)])
        pois = [
            make_poi("1", 37.5, 127.0),
            make_poi("2", 37.6, 127.1),
        ]
        result = engine.compute(pois, party_type="친구")
        assert result.wellness_bonus == WELLNESS_BONUS_PER_PLACE * 2

    def test_wellness_bonus_capped(self):
        # Create enough pois to exceed BONUS_CAP
        coords = [(37.5 + i * 0.01, 127.0) for i in range(20)]
        engine = make_engine(wellness_coords=coords)
        pois = [make_poi(str(i), 37.5 + i * 0.01, 127.0) for i in range(20)]
        result = engine.compute(pois, party_type="친구")
        assert result.wellness_bonus <= BONUS_CAP

    def test_non_matching_poi_no_bonus(self):
        engine = make_engine(wellness_coords=[(37.5, 127.0)])
        pois = [make_poi("1", 35.0, 129.0)]  # far away
        result = engine.compute(pois, party_type="친구")
        assert result.wellness_bonus == 0

    def test_wellness_applies_to_all_party_types(self):
        engine = make_engine(wellness_coords=[(37.5, 127.0)])
        pois = [make_poi("1", 37.5, 127.0)]
        for pt in ["혼자", "친구", "연인", "가족", "아기동반", "어르신동반"]:
            result = engine.compute(pois, party_type=pt)
            assert result.wellness_bonus > 0, f"party_type={pt} should get wellness bonus"


# ---------------------------------------------------------------------------
# BonusEngine.compute() — accessibility bonus
# ---------------------------------------------------------------------------

class TestAccessibilityBonus:
    def test_accessible_party_gets_bonus(self):
        engine = make_engine(barrier_free_coords=[(37.5, 127.0)])
        pois = [make_poi("1", 37.5, 127.0)]
        for pt in ACCESSIBLE_PARTY_TYPES:
            result = engine.compute(pois, party_type=pt)
            assert result.accessibility_bonus == ACCESSIBILITY_BONUS_PER_PLACE, f"failed for {pt}"

    def test_non_accessible_party_no_bonus(self):
        engine = make_engine(barrier_free_coords=[(37.5, 127.0)])
        pois = [make_poi("1", 37.5, 127.0)]
        for pt in ["혼자", "친구", "연인"]:
            result = engine.compute(pois, party_type=pt)
            assert result.accessibility_bonus == 0, f"non-accessible {pt} should not get bonus"

    def test_accessibility_bonus_capped(self):
        coords = [(37.5 + i * 0.01, 127.0) for i in range(20)]
        engine = make_engine(barrier_free_coords=coords)
        pois = [make_poi(str(i), 37.5 + i * 0.01, 127.0) for i in range(20)]
        result = engine.compute(pois, party_type="아기동반")
        assert result.accessibility_bonus <= BONUS_CAP


# ---------------------------------------------------------------------------
# BonusEngine.compute() — total_bonus cap
# ---------------------------------------------------------------------------

class TestTotalBonusCap:
    def test_combined_bonus_capped_at_cap(self):
        coords = [(37.5 + i * 0.01, 127.0) for i in range(20)]
        engine = make_engine(wellness_coords=coords, barrier_free_coords=coords)
        pois = [make_poi(str(i), 37.5 + i * 0.01, 127.0) for i in range(20)]
        result = engine.compute(pois, party_type="아기동반")
        assert result.total_bonus <= BONUS_CAP

    def test_total_is_sum_when_under_cap(self):
        engine = make_engine(
            wellness_coords=[(37.5, 127.0)],
            barrier_free_coords=[(37.51, 127.0)],
        )
        pois = [
            make_poi("1", 37.5, 127.0),
            make_poi("2", 37.51, 127.0),
        ]
        result = engine.compute(pois, party_type="아기동반")
        expected_total = min(
            result.wellness_bonus + result.accessibility_bonus, BONUS_CAP
        )
        assert result.total_bonus == expected_total


# ---------------------------------------------------------------------------
# BonusEngine.from_dataset()
# ---------------------------------------------------------------------------

class TestFromDataset:
    def test_missing_files_give_empty_engine(self):
        engine = BonusEngine.from_dataset(
            wellness_path="nonexistent_wellness.json",
            barrier_free_path="nonexistent_barrier.json",
        )
        pois = [make_poi("1", 37.5, 127.0)]
        result = engine.compute(pois, party_type="아기동반")
        assert result.total_bonus == 0

    def test_loads_from_json_files(self):
        records = [{"lat": 37.5, "lng": 127.0, "title": "Test"}]
        with tempfile.TemporaryDirectory() as tmp:
            wp = Path(tmp) / "wellness.json"
            bp = Path(tmp) / "barrier_free.json"
            wp.write_text(json.dumps(records), encoding="utf-8")
            bp.write_text(json.dumps(records), encoding="utf-8")

            engine = BonusEngine.from_dataset(wellness_path=wp, barrier_free_path=bp)
            pois = [make_poi("1", 37.5, 127.0)]
            result = engine.compute(pois, party_type="아기동반")
            assert result.wellness_bonus == WELLNESS_BONUS_PER_PLACE
            assert result.accessibility_bonus == ACCESSIBILITY_BONUS_PER_PLACE

    def test_zero_coords_skipped(self):
        records = [{"lat": 0.0, "lng": 0.0, "title": "Invalid"}]
        with tempfile.TemporaryDirectory() as tmp:
            wp = Path(tmp) / "wellness.json"
            wp.write_text(json.dumps(records), encoding="utf-8")

            engine = BonusEngine.from_dataset(wellness_path=wp, barrier_free_path="nonexistent.json")
            pois = [make_poi("1", 37.5, 127.0)]
            result = engine.compute(pois, party_type="친구")
            assert result.wellness_bonus == 0


# ---------------------------------------------------------------------------
# BonusResult fields
# ---------------------------------------------------------------------------

class TestBonusResultFields:
    def test_matched_names_populated(self):
        engine = make_engine(wellness_coords=[(37.5, 127.0)])
        pois = [make_poi("1", 37.5, 127.0)]
        result = engine.compute(pois, party_type="친구")
        assert "POI_1" in result.wellness_matched

    def test_no_match_empty_lists(self):
        engine = make_engine(wellness_coords=[(35.0, 129.0)])
        pois = [make_poi("1", 37.5, 127.0)]
        result = engine.compute(pois, party_type="친구")
        assert result.wellness_matched == []
        assert result.accessibility_matched == []
