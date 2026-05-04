"""Tests for WarningDetector (TDD)."""
from __future__ import annotations

import pytest

from src.data.models import DayPlan, ItineraryPlan, PlaceInput, POI
from src.validation.warning import WarningDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_poi(
    poi_id: str = "1",
    name: str = "POI",
    lat: float = 37.5,
    lng: float = 127.0,
    category: str = "14",
    duration_min: int = 60,
) -> POI:
    return POI(
        poi_id=poi_id, name=name, lat=lat, lng=lng,
        open_start="09:00", open_end="18:00",
        duration_min=duration_min, category=category,
    )


def make_plan(
    names: list[str],
    travel_type: str | None = None,
    party_type: str = "친구",
) -> ItineraryPlan:
    places = names if names else ["_p0"]
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=n) for n in places])],
        party_size=2,
        party_type=party_type,
        date="2026-05-10",
        travel_type=travel_type,
    )


def make_matrix(pairs: dict[tuple[int, int], float]) -> dict:
    matrix: dict[int, dict] = {}
    for (i, j), travel_min in pairs.items():
        matrix.setdefault(i, {})[j] = {
            "travel_min": travel_min,
            "distance_km": travel_min * (22.0 / 60.0),
        }
    return matrix


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector() -> WarningDetector:
    return WarningDetector()


# ---------------------------------------------------------------------------
# DENSE_SCHEDULE
# ---------------------------------------------------------------------------

class TestDenseSchedule:
    def test_dense_trigger_baby(self, detector):
        # 아기동반 피로도 한계 8h=480분, 4×60 + 3×100 = 540 > 480 → 발동
        pois = [make_poi(poi_id=str(i), name=f"P{i}", duration_min=60) for i in range(4)]
        matrix = make_matrix({(0, 1): 100.0, (1, 2): 100.0, (2, 3): 100.0})
        plan = make_plan([f"P{i}" for i in range(4)], party_type="아기동반")
        warns = detector.detect(plan, pois, matrix)
        types = [w.warning_type for w in warns]
        assert "DENSE_SCHEDULE" in types

    def test_dense_trigger_friends_heavy(self, detector):
        # 친구 피로도 한계 12h=720분, 4×120 + 3×120 = 840 > 720 → 발동
        pois = [make_poi(poi_id=str(i), name=f"P{i}", duration_min=120) for i in range(4)]
        matrix = make_matrix({(0, 1): 120.0, (1, 2): 120.0, (2, 3): 120.0})
        plan = make_plan([f"P{i}" for i in range(4)], party_type="친구")
        warns = detector.detect(plan, pois, matrix)
        types = [w.warning_type for w in warns]
        assert "DENSE_SCHEDULE" in types

    def test_no_dense_within_threshold(self, detector):
        # 친구 720분 한계, 4×60 + 3×10 = 270 < 720 → 미발동
        pois = [make_poi(poi_id=str(i), name=f"P{i}", duration_min=60) for i in range(4)]
        matrix = make_matrix({(0, 1): 10.0, (1, 2): 10.0, (2, 3): 10.0})
        plan = make_plan([f"P{i}" for i in range(4)])
        warns = detector.detect(plan, pois, matrix)
        types = [w.warning_type for w in warns]
        assert "DENSE_SCHEDULE" not in types

    def test_dense_message_includes_party_type(self, detector):
        pois = [make_poi(poi_id=str(i), name=f"P{i}", duration_min=60) for i in range(4)]
        matrix = make_matrix({(0, 1): 100.0, (1, 2): 100.0, (2, 3): 100.0})
        plan = make_plan([f"P{i}" for i in range(4)], party_type="어르신동반")
        warns = detector.detect(plan, pois, matrix)
        dense = next((w for w in warns if w.warning_type == "DENSE_SCHEDULE"), None)
        assert dense is not None
        assert "어르신동반" in dense.message


# ---------------------------------------------------------------------------
# PHYSICAL_STRAIN
# ---------------------------------------------------------------------------

class TestPhysicalStrain:
    def test_strain_trigger(self, detector):
        # POIs ~13 km apart × 3 legs ≈ 39 km total > 30 km threshold
        pois = [
            make_poi(poi_id="1", name="A", lat=37.0, lng=127.0),
            make_poi(poi_id="2", name="B", lat=37.12, lng=127.0),
            make_poi(poi_id="3", name="C", lat=37.24, lng=127.0),
            make_poi(poi_id="4", name="D", lat=37.36, lng=127.0),
        ]
        plan = make_plan(["A", "B", "C", "D"])
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "PHYSICAL_STRAIN" in types

    def test_no_strain_short_distance(self, detector):
        pois = [
            make_poi(poi_id=str(i), name=f"P{i}", lat=37.5, lng=127.0)
            for i in range(4)
        ]
        plan = make_plan([f"P{i}" for i in range(4)])
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "PHYSICAL_STRAIN" not in types


# ---------------------------------------------------------------------------
# PURPOSE_MISMATCH
# ---------------------------------------------------------------------------

class TestPurposeMismatch:
    def test_mismatch_cultural_all_sports(self, detector):
        # travel_type=cultural, all POIs are 레포츠(15) → mismatch
        pois = [
            make_poi(poi_id=str(i), name=f"P{i}", category="15")
            for i in range(4)
        ]
        plan = make_plan([f"P{i}" for i in range(4)], travel_type="cultural")
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "PURPOSE_MISMATCH" in types

    def test_no_mismatch_cultural_all_cultural(self, detector):
        # travel_type=cultural, all POIs are 문화시설(14) → no mismatch
        pois = [
            make_poi(poi_id=str(i), name=f"P{i}", category="14")
            for i in range(4)
        ]
        plan = make_plan([f"P{i}" for i in range(4)], travel_type="cultural")
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "PURPOSE_MISMATCH" not in types

    def test_no_mismatch_when_no_travel_type(self, detector):
        pois = [make_poi(poi_id=str(i), name=f"P{i}", category="15") for i in range(4)]
        plan = make_plan([f"P{i}" for i in range(4)], travel_type=None)
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "PURPOSE_MISMATCH" not in types


# ---------------------------------------------------------------------------
# AREA_REVISIT
# ---------------------------------------------------------------------------

class TestAreaRevisit:
    def test_consecutive_same_category_triggers(self, detector):
        # 3 consecutive "14" → AREA_REVISIT
        pois = [
            make_poi(poi_id="1", name="A", category="14"),
            make_poi(poi_id="2", name="B", category="14"),
            make_poi(poi_id="3", name="C", category="14"),
            make_poi(poi_id="4", name="D", category="39"),
        ]
        plan = make_plan(["A", "B", "C", "D"])
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "AREA_REVISIT" in types

    def test_all_different_no_revisit(self, detector):
        pois = [
            make_poi(poi_id="1", name="A", category="14"),
            make_poi(poi_id="2", name="B", category="12"),
            make_poi(poi_id="3", name="C", category="39"),
            make_poi(poi_id="4", name="D", category="38"),
        ]
        plan = make_plan(["A", "B", "C", "D"])
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "AREA_REVISIT" not in types

    def test_three_consecutive_triggers(self, detector):
        # 3 consecutive same category → AREA_REVISIT (threshold raised from 2 to 3)
        pois = [
            make_poi(poi_id="1", name="A", category="14"),
            make_poi(poi_id="2", name="B", category="14"),
            make_poi(poi_id="3", name="C", category="14"),
            make_poi(poi_id="4", name="D", category="39"),
        ]
        plan = make_plan(["A", "B", "C", "D"])
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "AREA_REVISIT" in types

    def test_two_consecutive_no_trigger(self, detector):
        # 2 consecutive: no longer triggers (문화투어 false positive 방지)
        pois = [
            make_poi(poi_id="1", name="A", category="14"),
            make_poi(poi_id="2", name="B", category="14"),
            make_poi(poi_id="3", name="C", category="12"),
            make_poi(poi_id="4", name="D", category="39"),
        ]
        plan = make_plan(["A", "B", "C", "D"])
        warns = detector.detect(plan, pois, {})
        types = [w.warning_type for w in warns]
        assert "AREA_REVISIT" not in types


# ---------------------------------------------------------------------------
# Warning model fields
# ---------------------------------------------------------------------------

class TestWarningFields:
    def test_warning_has_confidence_from_types(self, detector):
        pois = [
            make_poi(poi_id=str(i), name=f"P{i}", category="15")
            for i in range(4)
        ]
        plan = make_plan([f"P{i}" for i in range(4)], travel_type="cultural")
        warns = detector.detect(plan, pois, {})
        mismatch = next((w for w in warns if w.warning_type == "PURPOSE_MISMATCH"), None)
        assert mismatch is not None
        assert mismatch.confidence == "Medium-Low"

    def test_warning_message_not_empty(self, detector):
        pois = [make_poi(poi_id=str(i), name=f"P{i}", duration_min=60) for i in range(4)]
        matrix = make_matrix({(0, 1): 100.0, (1, 2): 100.0, (2, 3): 100.0})
        plan = make_plan([f"P{i}" for i in range(4)])
        warns = detector.detect(plan, pois, matrix)
        for w in warns:
            assert len(w.message) > 0
