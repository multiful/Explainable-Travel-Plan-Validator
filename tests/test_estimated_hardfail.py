"""P1: 추정 영업시간 충돌의 하드페일 강등 테스트."""
from __future__ import annotations

from src.data.models import DayPlan, ItineraryPlan, PlaceInput, POI
from src.validation.hard_fail import HardFailDetector


def _poi(name: str, open_start: str, open_end: str, estimated: bool) -> POI:
    return POI(
        poi_id=f"p_{name}",
        name=name,
        lat=37.5,
        lng=127.0,
        open_start=open_start,
        open_end=open_end,
        duration_min=60,
        category="14",
        hours_estimated=estimated,
    )


def _plan(names: list[str]) -> ItineraryPlan:
    return ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=n) for n in names])],
        party_size=2,
        party_type="친구",
        date="2026-05-10",
    )


def test_estimated_hours_conflict_flagged_estimated() -> None:
    # 09:00 출발인데 10:30 오픈 → 도착 < 오픈 충돌. 추정 영업시간.
    pois = [_poi("개성만두궁", "10:30", "21:00", estimated=True)]
    fails = HardFailDetector().detect(_plan(["개성만두궁"]), pois, matrix={}, start_minutes=9 * 60)
    conflicts = [f for f in fails if f.fail_type == "OPERATING_HOURS_CONFLICT"]
    assert len(conflicts) == 1
    assert conflicts[0].estimated is True
    assert "추정 영업시간" in conflicts[0].message


def test_verified_hours_conflict_not_estimated_and_message_unchanged() -> None:
    # hours_estimated=False(기존 동작) → estimated False, 원문 메시지 유지.
    pois = [_poi("궁", "10:30", "21:00", estimated=False)]
    fails = HardFailDetector().detect(_plan(["궁"]), pois, matrix={}, start_minutes=9 * 60)
    conflicts = [f for f in fails if f.fail_type == "OPERATING_HOURS_CONFLICT"]
    assert len(conflicts) == 1
    assert conflicts[0].estimated is False
    assert "추정 영업시간" not in conflicts[0].message
    assert conflicts[0].message.endswith("아직 문을 열지 않았습니다.")
