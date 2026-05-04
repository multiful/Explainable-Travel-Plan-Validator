"""RepairEngine 유닛 테스트."""
from __future__ import annotations

import pytest

from src.data.models import DayPlan, HardFail, ItineraryPlan, PlaceInput, POI
from src.explain.repair import RepairEngine, _MAX_PERM_N


def _poi(
    name: str,
    lat: float = 37.5,
    lng: float = 127.0,
    category: str = "14",
    duration: int = 90,
    open_start: str = "09:00",
    open_end: str = "18:00",
) -> POI:
    return POI(
        poi_id=name, name=name, lat=lat, lng=lng,
        open_start=open_start, open_end=open_end,
        duration_min=duration, category=category,
    )


def _plan(names: list[str], party_type: str = "친구") -> ItineraryPlan:
    if not names:
        names = ["placeholder"]
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=n) for n in names])],
        party_size=2,
        party_type=party_type,  # type: ignore[arg-type]
        date="2026-05-10",
    )


def _fail() -> HardFail:
    return HardFail(
        fail_type="SCHEDULE_INFEASIBLE",
        message="test", evidence="test", confidence="High",
    )


# ---------------------------------------------------------------------------
# 기본 동작
# ---------------------------------------------------------------------------

class TestRepairEngineNoop:
    def test_empty_when_no_hard_fails(self):
        engine = RepairEngine()
        plan = _plan(["A", "B"])
        result = engine.repair(plan, [[_poi("A"), _poi("B")]], {}, hard_fails=[])
        assert result.is_empty

    def test_empty_when_pois_list_is_empty(self):
        engine = RepairEngine()
        plan = _plan(["A"])
        result = engine.repair(plan, [[]], {}, hard_fails=[_fail()])
        assert result.is_empty


# ---------------------------------------------------------------------------
# 개선 7 — Outlier Deletion
# n > _MAX_PERM_N (8 POIs): reorder 단계 스킵
# duration=20 (절대 최솟값): time_tune 단계 스킵
# → deletion 단계 검증 가능
# ---------------------------------------------------------------------------

def _outlier_pois() -> list[POI]:
    """8개 POI — D(lat=38.5)가 A-C, E-H(lat=37.5) 사이의 지리적 이상치."""
    return [
        _poi("A", lat=37.5, lng=127.0, duration=20),
        _poi("B", lat=37.5, lng=127.1, duration=20),
        _poi("C", lat=37.5, lng=127.2, duration=20),
        _poi("D", lat=38.5, lng=127.0, duration=20),  # ~110km 우회 이상치
        _poi("E", lat=37.5, lng=127.3, duration=20),
        _poi("F", lat=37.5, lng=127.4, duration=20),
        _poi("G", lat=37.5, lng=127.5, duration=20),
        _poi("H", lat=37.5, lng=127.6, duration=20),
    ]


class TestDeletionSuggestion:
    def test_identifies_geometric_outlier(self):
        engine = RepairEngine()
        plan = _plan(["A", "B", "C", "D", "E", "F", "G", "H"])
        pois = [_outlier_pois()]
        result = engine.repair(plan, pois, {}, hard_fails=[_fail()])
        assert result.deletions
        assert result.deletions[0].candidate_name == "D"

    def test_outlier_deletion_has_positive_savings(self):
        engine = RepairEngine()
        plan = _plan(["A", "B", "C", "D", "E", "F", "G", "H"])
        result = engine.repair(plan, [_outlier_pois()], {}, hard_fails=[_fail()])
        assert result.deletions
        assert result.deletions[0].travel_saved_km > 50  # D는 ~110km 우회

    def test_no_deletion_for_two_pois(self):
        engine = RepairEngine()
        plan = _plan(["A", "B"])
        result = engine.repair(plan, [[_poi("A"), _poi("B")]], {}, hard_fails=[_fail()])
        assert not result.deletions

    def test_deletion_reason_mentions_candidate(self):
        engine = RepairEngine()
        plan = _plan(["A", "B", "C", "D", "E", "F", "G", "H"])
        result = engine.repair(plan, [_outlier_pois()], {}, hard_fails=[_fail()])
        assert result.deletions
        assert "D" in result.deletions[0].reason


# ---------------------------------------------------------------------------
# Stay-time Tuning
# ---------------------------------------------------------------------------

class TestTimeTuneSuggestion:
    def test_no_tune_when_within_limit(self):
        """친구(720min) 기준, 총 120min → 조정 불필요."""
        engine = RepairEngine()
        plan = _plan(["A", "B"])
        pois = [[_poi("A", duration=60), _poi("B", duration=60)]]
        result = engine.repair(plan, pois, {}, hard_fails=[_fail()])
        assert not result.time_tunes

    def test_tune_suggested_when_over_limit(self):
        """5 × 200min = 1000min > 720min → 튜닝 필요."""
        engine = RepairEngine()
        plan = _plan(["A", "B", "C", "D", "E"])
        pois = [[_poi(n, duration=200) for n in ["A", "B", "C", "D", "E"]]]
        result = engine.repair(plan, pois, {}, hard_fails=[_fail()])
        # 재배치로 해결 가능하면 tune이 없을 수 있음 → reorder OR tune 중 하나는 있어야 함
        assert result.reorders or result.time_tunes

    def test_adjusted_durations_above_minimum(self):
        """조정 후 duration이 절대 최솟값(20분) 이상 보장."""
        engine = RepairEngine()
        plan = _plan(["A", "B", "C"])
        pois = [[_poi(n, duration=300) for n in ["A", "B", "C"]]]
        result = engine.repair(plan, pois, {}, hard_fails=[_fail()])
        if result.time_tunes:
            for new_dur in result.time_tunes[0].adjustments.values():
                assert new_dur >= 20


# ---------------------------------------------------------------------------
# to_dict / is_empty
# ---------------------------------------------------------------------------

class TestResultModel:
    def test_to_dict_is_serializable(self):
        engine = RepairEngine()
        plan = _plan(["A", "B", "C", "D", "E", "F", "G", "H"])
        result = engine.repair(plan, [_outlier_pois()], {}, hard_fails=[_fail()])
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "reorders" in d and "time_tunes" in d and "deletions" in d

    def test_is_empty_true_when_no_suggestions(self):
        engine = RepairEngine()
        plan = _plan(["A"])
        result = engine.repair(plan, [[_poi("A")]], {}, hard_fails=[])
        assert result.is_empty

    def test_is_empty_false_when_has_deletion(self):
        engine = RepairEngine()
        plan = _plan(["A", "B", "C", "D", "E", "F", "G", "H"])
        result = engine.repair(plan, [_outlier_pois()], {}, hard_fails=[_fail()])
        assert not result.is_empty
