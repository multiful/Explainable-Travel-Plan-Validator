"""Tests for ValidatorPipeline (TDD)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.data.models import AlternativePOI, DayPlan, HardFail, ItineraryPlan, PlaceInput, POI, ValidationResult
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

    def test_base_score_populated(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert 0 <= result.base_score <= 100


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

    def test_hard_fail_day_index_matches_offending_day(self, pipeline):
        # Day 0 정상, Day 1에 시간대 충돌 POI 배치
        day0 = [make_poi("1", 37.50, 127.00)]
        night_only = POI(
            poi_id="X", name="NightOnly",
            lat=37.5, lng=127.0,
            open_start="22:00", open_end="23:00",
            duration_min=60, category="14",
        )
        day1 = [night_only]
        plan = make_multi_day_plan([[p.name for p in day0], [night_only.name]])
        result = pipeline.run(plan=plan, per_day_pois=[day0, day1], matrix={})
        assert result.hard_fails
        assert all(f.day_index == 1 for f in result.hard_fails)

    def test_alternatives_populated_from_explain_engine(self):
        mock_explain = MagicMock()
        mock_explain.generate.return_value = []
        mock_explain.build_alternatives.return_value = {
            "NightOnly": [AlternativePOI(name="Alt", distance_km=0.3, category="14", lat=37.5, lng=127.0)]
        }
        pipeline = ValidatorPipeline(
            bonus_engine=make_empty_bonus_engine(), explain_engine=mock_explain
        )
        night_only = POI(
            poi_id="X", name="NightOnly", lat=37.5, lng=127.0,
            open_start="22:00", open_end="23:00", duration_min=60, category="14",
        )
        plan = make_plan([night_only.name])
        result = pipeline.run(plan=plan, per_day_pois=[[night_only]], matrix={})
        assert result.hard_fails
        mock_explain.build_alternatives.assert_called_once_with(result.hard_fails)
        assert result.alternatives == mock_explain.build_alternatives.return_value

    def test_alternatives_not_computed_without_hard_fails(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(plan=sample_plan, per_day_pois=[sample_pois], matrix={})
        if not result.hard_fails:
            assert result.alternatives == {}


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

    def test_pet_friendly_bonus_when_enabled(self, pipeline):
        poi = make_poi("1", 37.5, 127.0).model_copy(update={"pet_friendly": True})
        plan = make_plan([poi.name])
        result = pipeline.run(
            plan=plan, per_day_pois=[[poi]], matrix={}, pet_friendly_enabled=True
        )
        assert "pet_friendly" in result.bonus_breakdown
        assert result.bonus_breakdown["pet_friendly"] > 0

    def test_pet_friendly_bonus_absent_when_disabled(self, pipeline):
        poi = make_poi("1", 37.5, 127.0).model_copy(update={"pet_friendly": True})
        plan = make_plan([poi.name])
        result = pipeline.run(
            plan=plan, per_day_pois=[[poi]], matrix={}, pet_friendly_enabled=False
        )
        assert "pet_friendly" not in result.bonus_breakdown

    def test_wellness_matched_exposed_on_result(self):
        wellness = [_PlaceCoord(lat=37.5, lng=127.0)]
        engine = BonusEngine(wellness_coords=wellness, barrier_free_coords=[])
        pipeline = ValidatorPipeline(bonus_engine=engine)

        pois = [make_poi("1", 37.5, 127.0)]
        plan = make_plan([p.name for p in pois])
        result = pipeline.run(plan=plan, per_day_pois=[pois], matrix={})
        assert pois[0].name in result.wellness_matched


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


# ---------------------------------------------------------------------------
# ValidatorPipeline.run() — VRPTW 통합
# ---------------------------------------------------------------------------

class TestPipelineVRPTW:
    def test_vrptw_fields_present(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        # 필드 자체가 존재해야 함 (None이어도 무방)
        assert hasattr(result, "vrptw_optimal_route")
        assert hasattr(result, "vrptw_efficiency_gap")

    def test_vrptw_efficiency_gap_is_float_or_none(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        assert result.vrptw_efficiency_gap is None or isinstance(result.vrptw_efficiency_gap, float)

    def test_vrptw_efficiency_gap_non_negative(self, pipeline, sample_pois, sample_plan):
        result = pipeline.run(
            plan=sample_plan,
            per_day_pois=[sample_pois],
            matrix={},
        )
        if result.vrptw_efficiency_gap is not None:
            assert result.vrptw_efficiency_gap >= 0.0

    def test_vrptw_optimal_route_per_day_count(self, pipeline):
        day1 = [make_poi("1", 37.50, 127.00), make_poi("2", 37.52, 127.02)]
        day2 = [make_poi("3", 37.51, 127.01), make_poi("4", 37.53, 127.03)]
        plan = make_multi_day_plan([
            [p.name for p in day1],
            [p.name for p in day2],
        ])
        result = pipeline.run(plan=plan, per_day_pois=[day1, day2], matrix={})
        if result.vrptw_optimal_route is not None:
            assert len(result.vrptw_optimal_route) == 2
            assert result.vrptw_optimal_route[0].day_index == 0
            assert result.vrptw_optimal_route[1].day_index == 1

    def test_vrptw_penalty_in_breakdown_when_gap_exceeds_threshold(self, pipeline):
        # A→C→B 순서 (백트래킹): A(127.00)→C(127.30)→B(127.10)
        # 최적 A→B→C 대비 비효율 → efficiency_gap > 20% 예상
        pois = [
            make_poi("A", 37.5, 127.00),
            make_poi("C", 37.5, 127.30),
            make_poi("B", 37.5, 127.10),
        ]
        plan = make_plan([p.name for p in pois])
        result = pipeline.run(plan=plan, per_day_pois=[pois], matrix={})
        if result.vrptw_efficiency_gap is not None and result.vrptw_efficiency_gap > 0.20:
            assert "vrptw_efficiency" in result.penalty_breakdown
            assert result.penalty_breakdown["vrptw_efficiency"] in (5, 10, 15)

    def test_vrptw_penalty_does_not_double_count_with_single_poi(self, pipeline):
        pois = [make_poi("solo", 37.5, 127.0)]
        plan = make_plan([p.name for p in pois])
        result = pipeline.run(plan=plan, per_day_pois=[pois], matrix={})
        # 단일 POI는 efficiency gap 미정의 → vrptw 패널티 없어야 함
        assert result.penalty_breakdown.get("vrptw_efficiency", 0) == 0


# ---------------------------------------------------------------------------
# ValidatorPipeline.run() — Repair 제안 예상 점수 변화 (지도 UX 개선)
# ---------------------------------------------------------------------------

class TestPipelineRepairGainEstimation:
    def test_deletion_suggestion_carries_gain_and_resolves_flag(self, pipeline):
        """지리적 이상치이자 Hard Fail 유발 POI를 삭제하면 점수가 오르고 문제가 해소돼야 한다."""
        a = make_poi("A", 37.50, 127.00)
        b = make_poi("B", 37.51, 127.01)
        night_only = POI(
            poi_id="X", name="NightOnly", lat=38.50, lng=127.00,
            open_start="22:00", open_end="23:00", duration_min=60, category="14",
        )
        pois = [a, b, night_only]
        plan = make_plan([p.name for p in pois])
        result = pipeline.run(plan=plan, per_day_pois=[pois], matrix={})

        assert result.hard_fails
        deletions = result.repair.get("deletions", [])
        assert deletions
        target = next((d for d in deletions if d["candidate_name"] == night_only.name), None)
        assert target is not None
        assert target["resolves_hard_fail"] is True
        assert target["estimated_score_gain"] > 0

    def test_no_repair_no_gain_fields_needed(self, pipeline, sample_pois, sample_plan):
        """Hard Fail이 없으면 repair 자체가 비어 있어야 한다 (기존 동작 유지)."""
        result = pipeline.run(plan=sample_plan, per_day_pois=[sample_pois], matrix={})
        if not result.hard_fails:
            assert result.repair == {}
