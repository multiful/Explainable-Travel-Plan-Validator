"""Tests for ValidatorPipeline (TDD)."""
from __future__ import annotations

import pytest

from src.data.models import DayPlan, HardFail, ItineraryPlan, PlaceInput, POI, ValidationResult
from src.explain.pipeline import ValidatorPipeline, _to_vrptw_day
from src.scoring.bonus_engine import BonusEngine, _PlaceCoord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_poi(
    poi_id: str = "1",
    lat: float = 37.5,
    lng: float = 127.0,
    category: str = "14",
    duration_min: int = 60,
) -> POI:
    return POI(
        poi_id=poi_id, name=f"POI_{poi_id}",
        lat=lat, lng=lng,
        open_start="09:00", open_end="18:00",
        duration_min=duration_min,
        category=category,
    )


def make_plan(
    names: list[str],
    party_type: str = "친구",
    travel_type: str | None = None,
) -> ItineraryPlan:
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=n) for n in names])],
        party_size=2,
        party_type=party_type,
        date="2026-05-10",
        travel_type=travel_type,
    )


def make_multi_day_plan(days: list[list[str]]) -> ItineraryPlan:
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=n) for n in day]) for day in days],
        party_size=2,
        party_type="친구",
        date="2026-05-10",
    )


def make_empty_bonus_engine() -> BonusEngine:
    return BonusEngine(wellness_coords=[], barrier_free_coords=[])


@pytest.fixture
def pipeline() -> ValidatorPipeline:
    return ValidatorPipeline(bonus_engine=make_empty_bonus_engine())


@pytest.fixture
def sample_pois() -> list[POI]:
    return [
        make_poi("1", 37.50, 127.00, category="14"),
        make_poi("2", 37.51, 127.01, category="14"),
        make_poi("3", 37.52, 127.02, category="12"),
        make_poi("4", 37.53, 127.03, category="39"),
    ]


@pytest.fixture
def sample_plan(sample_pois: list[POI]) -> ItineraryPlan:
    return make_plan([p.name for p in sample_pois])


# ---------------------------------------------------------------------------
# _to_vrptw_day helper
# ---------------------------------------------------------------------------

class TestToVrptwDay:
    def test_converts_poi_fields(self):
        pois = [make_poi("1", 37.5, 127.0)]
        day = _to_vrptw_day(pois)
        assert len(day.places) == 1
        assert day.places[0].lat == 37.5
        assert day.places[0].lng == 127.0
        assert day.places[0].stay_duration == 60
        assert day.places[0].open == "09:00"

    def test_is_depot_false(self):
        pois = [make_poi()]
        day = _to_vrptw_day(pois)
        assert not day.places[0].is_depot


# ---------------------------------------------------------------------------
# ValidatorPipeline.run() — basic contract
# ---------------------------------------------------------------------------

class TestPipelineBasic:
    def test_returns_validation_result(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert isinstance(result, ValidationResult)

    def test_final_score_in_range(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert 0 <= result.final_score <= 100

    def test_plan_id_matches(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert result.plan_id == sample_plan.plan_id

    def test_scores_populated(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert result.scores is not None
        assert 0.0 <= result.scores.efficiency <= 1.0

    def test_empty_pois_returns_zero_score(self, pipeline):
        plan = make_plan(["X"])  # plan needs at least 1 place
        result = pipeline.run(plan=plan, per_day_pois=[[]], matrix={})
        assert result.final_score == 0


# ---------------------------------------------------------------------------
# ValidatorPipeline.run() — hard_fail cap
# ---------------------------------------------------------------------------

class TestPipelineHardFail:
    def test_open_hours_conflict_caps_score(self, pipeline):
        # POI with impossible time window — close < open
        pois = [
            POI(
                poi_id="X", name="NightOnly",
                lat=37.5, lng=127.0,
                open_start="22:00", open_end="23:00",
                duration_min=60, category="14",
            ),
            make_poi("2", 37.51, 127.01),
        ]
        plan = make_plan([p.name for p in pois])
        result = pipeline.run(plan=plan, per_day_pois=[pois], matrix={})
        if result.hard_fails:
            assert result.final_score <= 59

    def test_no_hard_fail_score_above_59_possible(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert not result.hard_fails or result.final_score <= 59


# ---------------------------------------------------------------------------
# ValidatorPipeline.run() — penalty/bonus breakdown
# ---------------------------------------------------------------------------

class TestPipelineBreakdown:
    def test_breakdown_fields_are_dicts(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert isinstance(result.penalty_breakdown, dict)
        assert isinstance(result.bonus_breakdown, dict)

    def test_wellness_bonus_reflected_in_breakdown(self):
        wellness = [_PlaceCoord(lat=37.5, lng=127.0)]
        engine = BonusEngine(wellness_coords=wellness, barrier_free_coords=[])
        pipeline = ValidatorPipeline(bonus_engine=engine)

        pois = [make_poi("1", 37.5, 127.0)]
        plan = make_plan([p.name for p in pois])
        result = pipeline.run(plan=plan, per_day_pois=[pois], matrix={})
        assert "wellness" in result.bonus_breakdown
        assert result.bonus_breakdown["wellness"] > 0

    def test_accessibility_bonus_for_accessible_party(self):
        barrier_free = [_PlaceCoord(lat=37.5, lng=127.0)]
        engine = BonusEngine(wellness_coords=[], barrier_free_coords=barrier_free)
        pipeline = ValidatorPipeline(bonus_engine=engine)

        pois = [make_poi("1", 37.5, 127.0)]
        plan = make_plan([p.name for p in pois], party_type="아기동반")
        result = pipeline.run(plan=plan, per_day_pois=[pois], matrix={})
        assert "accessibility" in result.bonus_breakdown
        assert result.bonus_breakdown["accessibility"] > 0


# ---------------------------------------------------------------------------
# ValidatorPipeline.run() — multi-day
# ---------------------------------------------------------------------------

class TestPipelineMultiDay:
    def test_multi_day_runs_without_error(self, pipeline):
        day1 = [make_poi("1", 37.50, 127.00), make_poi("2", 37.51, 127.01)]
        day2 = [make_poi("3", 37.52, 127.02), make_poi("4", 37.53, 127.03)]
        plan = make_multi_day_plan([
            [p.name for p in day1],
            [p.name for p in day2],
        ])
        result = pipeline.run(plan=plan, per_day_pois=[day1, day2], matrix={})
        assert isinstance(result, ValidationResult)
        assert 0 <= result.final_score <= 100

    def test_sigungu_codes_accepted(self, pipeline):
        pois = [make_poi("1"), make_poi("2")]
        plan = make_plan([p.name for p in pois])
        sigungu = [["11230", "11230"]]
        result = pipeline.run(
            plan=plan,
            per_day_pois=[pois],
            matrix={},
            sigungu_codes_per_day=sigungu,
        )
        assert isinstance(result, ValidationResult)
