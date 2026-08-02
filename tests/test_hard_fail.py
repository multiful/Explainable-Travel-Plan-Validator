"""Tests for HardFailDetector (TDD)."""
from __future__ import annotations

import pytest

from src.data.models import DayPlan, ItineraryPlan, PlaceInput, POI
from src.validation.hard_fail import DEFAULT_START_MINUTES, HardFailDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_poi(
    poi_id: str = "1",
    name: str = "POI",
    lat: float = 37.579,
    lng: float = 126.977,
    open_start: str = "09:00",
    open_end: str = "18:00",
    duration_min: int = 60,
    category: str = "14",
) -> POI:
    return POI(
        poi_id=poi_id, name=name, lat=lat, lng=lng,
        open_start=open_start, open_end=open_end,
        duration_min=duration_min, category=category,
    )


def make_plan(names: list[str]) -> ItineraryPlan:
    places = names if names else ["P0"]
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=n) for n in places])],
        party_size=2,
        party_type="친구",
        date="2026-05-10",
    )


# matrix[i][j] = {"travel_min": float, "distance_km": float}
def make_matrix(pairs: dict[tuple[int, int], float]) -> dict:
    matrix: dict[int, dict] = {}
    for (i, j), travel_min in pairs.items():
        matrix.setdefault(i, {})[j] = {
            "travel_min": travel_min,
            "distance_km": travel_min * (22.0 / 60.0),
            "mode": "car",
            "is_fallback": False,
        }
    return matrix


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector() -> HardFailDetector:
    return HardFailDetector()


@pytest.fixture
def open_poi() -> POI:
    return make_poi(poi_id="1", name="A", open_start="09:00", open_end="18:00", duration_min=60)


# ---------------------------------------------------------------------------
# _time_to_min / _min_to_time
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_time_to_min(self):
        assert HardFailDetector._time_to_min("09:30") == 570

    def test_min_to_time(self):
        assert HardFailDetector._min_to_time(570) == "09:30"

    def test_time_to_min_midnight(self):
        assert HardFailDetector._time_to_min("00:00") == 0

    def test_min_to_time_midnight(self):
        assert HardFailDetector._min_to_time(0) == "00:00"


# ---------------------------------------------------------------------------
# OPERATING_HOURS_CONFLICT
# ---------------------------------------------------------------------------

class TestOperatingHours:
    def test_no_fail_within_hours(self, detector, open_poi):
        # start=09:10, open 09:00-18:00 → no fail
        pois = [open_poi]
        plan = make_plan(["A"])
        fails = detector.detect(plan, pois, {}, start_minutes=9 * 60 + 10)
        types = [f.fail_type for f in fails]
        assert "OPERATING_HOURS_CONFLICT" not in types

    def test_fail_arrive_before_open(self, detector, open_poi):
        # start=08:30, open 09:00-18:00 → OPERATING_HOURS_CONFLICT
        pois = [open_poi]
        plan = make_plan(["A"])
        fails = detector.detect(plan, pois, {}, start_minutes=8 * 60 + 30)
        types = [f.fail_type for f in fails]
        assert "OPERATING_HOURS_CONFLICT" in types
        match = next(f for f in fails if f.fail_type == "OPERATING_HOURS_CONFLICT")
        assert match.poi_name == "A"
        assert match.confidence == "Medium"

    def test_fail_arrive_after_close(self, detector):
        # start at 19:00 for a 09:00-18:00 POI → OPERATING_HOURS_CONFLICT
        poi = make_poi(poi_id="1", name="A", open_start="09:00", open_end="18:00", duration_min=60)
        pois = [poi]
        plan = make_plan(["A"])
        fails = detector.detect(plan, pois, {}, start_minutes=19 * 60)
        types = [f.fail_type for f in fails]
        assert "OPERATING_HOURS_CONFLICT" in types

    def test_no_fail_for_fallback_hours(self, detector):
        # 00:00~23:59 is fallback — should not trigger OPERATING_HOURS_CONFLICT
        poi = make_poi(poi_id="1", name="A", open_start="00:00", open_end="23:59")
        pois = [poi]
        plan = make_plan(["A"])
        fails = detector.detect(plan, pois, {}, start_minutes=3 * 60)
        types = [f.fail_type for f in fails]
        assert "OPERATING_HOURS_CONFLICT" not in types


# ---------------------------------------------------------------------------
# TRAVEL_TIME_IMPOSSIBLE
# ---------------------------------------------------------------------------

class TestTravelTimeImpossible:
    def test_travel_impossible(self, detector):
        # departure at 09:00, next poi closes at 10:00 → window=60 min
        # matrix says 200 min travel → TRAVEL_TIME_IMPOSSIBLE
        poi_a = make_poi(poi_id="1", name="A", open_start="09:00", open_end="18:00", duration_min=1)
        poi_b = make_poi(poi_id="2", name="B", open_start="09:00", open_end="10:00", duration_min=60)
        pois = [poi_a, poi_b]
        matrix = make_matrix({(0, 1): 200.0})  # 200 min travel
        plan = make_plan(["A", "B"])
        fails = detector.detect(plan, pois, matrix, start_minutes=9 * 60)
        types = [f.fail_type for f in fails]
        assert "TRAVEL_TIME_IMPOSSIBLE" in types
        match = next(f for f in fails if f.fail_type == "TRAVEL_TIME_IMPOSSIBLE")
        assert match.confidence == "High"

    def test_no_fail_sufficient_window(self, detector):
        poi_a = make_poi(poi_id="1", name="A", open_start="09:00", open_end="18:00", duration_min=60)
        poi_b = make_poi(poi_id="2", name="B", open_start="09:00", open_end="18:00", duration_min=60)
        pois = [poi_a, poi_b]
        matrix = make_matrix({(0, 1): 30.0})
        plan = make_plan(["A", "B"])
        fails = detector.detect(plan, pois, matrix)
        types = [f.fail_type for f in fails]
        assert "TRAVEL_TIME_IMPOSSIBLE" not in types


# ---------------------------------------------------------------------------
# SCHEDULE_INFEASIBLE
# ---------------------------------------------------------------------------

class TestScheduleInfeasible:
    def test_schedule_exceeds_24h(self, detector):
        # 4 POIs × 360 min dwell + heavy travel → > 1440 min
        pois = [
            make_poi(poi_id=str(i), name=f"P{i}",
                     lat=37.5 + i * 0.01, lng=127.0,
                     duration_min=360)
            for i in range(4)
        ]
        # travel 30 min between each pair
        matrix = make_matrix({
            (0, 1): 30.0, (1, 2): 30.0, (2, 3): 30.0,
        })
        plan = make_plan([f"P{i}" for i in range(4)])
        fails = detector.detect(plan, pois, matrix)
        # 4×360 + 3×30 = 1440 + 90 = 1530 > 1440
        types = [f.fail_type for f in fails]
        assert "SCHEDULE_INFEASIBLE" in types

    def test_schedule_within_24h(self, detector):
        pois = [
            make_poi(poi_id=str(i), name=f"P{i}", duration_min=60)
            for i in range(4)
        ]
        matrix = make_matrix({(0, 1): 30.0, (1, 2): 30.0, (2, 3): 30.0})
        plan = make_plan([f"P{i}" for i in range(4)])
        fails = detector.detect(plan, pois, matrix)
        # 4×60 + 3×30 = 240+90 = 330 min → no SCHEDULE_INFEASIBLE
        types = [f.fail_type for f in fails]
        assert "SCHEDULE_INFEASIBLE" not in types


# ---------------------------------------------------------------------------
# Normal plan — empty result
# ---------------------------------------------------------------------------

class TestNormalPlan:
    def test_normal_plan_no_fails(self, detector):
        pois = [
            make_poi(poi_id="1", name="A", open_start="09:00", open_end="18:00", duration_min=60),
            make_poi(poi_id="2", name="B", open_start="09:00", open_end="18:00", duration_min=60),
            make_poi(poi_id="3", name="C", open_start="09:00", open_end="18:00", duration_min=60),
            make_poi(poi_id="4", name="D", open_start="09:00", open_end="18:00", duration_min=60),
        ]
        matrix = make_matrix({
            (0, 1): 20.0, (1, 2): 20.0, (2, 3): 20.0,
        })
        plan = make_plan(["A", "B", "C", "D"])
        fails = detector.detect(plan, pois, matrix)
        assert fails == []


# ---------------------------------------------------------------------------
# day_index threading
# ---------------------------------------------------------------------------

class TestDayIndex:
    def test_day_index_defaults_to_none(self, detector):
        poi = make_poi(poi_id="1", name="A", open_start="09:00", open_end="18:00", duration_min=60)
        plan = make_plan(["A"])
        fails = detector.detect(plan, [poi], {}, start_minutes=19 * 60)
        assert fails
        assert fails[0].day_index is None

    def test_day_index_set_when_passed(self, detector):
        poi = make_poi(poi_id="1", name="A", open_start="09:00", open_end="18:00", duration_min=60)
        plan = make_plan(["A"])
        fails = detector.detect(plan, [poi], {}, start_minutes=19 * 60, day_index=2)
        assert fails
        assert all(f.day_index == 2 for f in fails)
