"""Tests for src/scoring/travel_ratio.py."""

from __future__ import annotations

from src.data.models import VRPTWDay, VRPTWPlace
from src.scoring.travel_ratio import (
    evaluate_travel_ratio,
)
from src.validation.vrptw_engine import HaversineMatrix


def _make_place(name: str, lng: float, lat: float, stay_min: int = 60):
    return VRPTWPlace(
        name=name,
        lng=lng,
        lat=lat,
        open="09:00",
        close="22:00",
        stay_duration=stay_min,
        is_depot=False,
    )


def test_no_penalty_when_ratio_low():
    """4개 장소가 모두 가까이 있으면 travel_ratio가 낮음 → 패널티 0."""
    day = VRPTWDay(
        places=[
            _make_place("A", 127.0, 37.5),
            _make_place("B", 127.001, 37.501),
            _make_place("C", 127.002, 37.502),
            _make_place("D", 127.003, 37.503),
        ]
    )
    report = evaluate_travel_ratio([day], matrix=HaversineMatrix())
    assert report.total_penalty == 0
    assert report.per_day[0].travel_ratio < 0.20


def test_penalty_when_ratio_high():
    """장소가 멀리 떨어져 이동 시간이 관광 시간을 압도하면 패널티 발생."""
    day = VRPTWDay(
        places=[
            _make_place("서울", 126.978, 37.566, stay_min=15),
            _make_place("부산", 129.075, 35.180, stay_min=15),
        ]
    )
    report = evaluate_travel_ratio([day], matrix=HaversineMatrix())
    # 서울→부산 직선거리 약 325km, 30km/h 가정 시 이동 ~10시간
    # vs 체류 30분 → ratio ≈ 0.95 → CRITICAL
    assert report.per_day[0].travel_ratio > 0.6
    assert report.total_penalty >= 20


def test_overall_ratio_aggregates_across_days():
    days = [
        VRPTWDay(
            places=[
                _make_place("A", 127.0, 37.5, stay_min=60),
                _make_place("B", 127.001, 37.501, stay_min=60),
            ]
        ),
        VRPTWDay(
            places=[
                _make_place("C", 127.0, 37.5, stay_min=60),
                _make_place("D", 127.001, 37.501, stay_min=60),
            ]
        ),
    ]
    report = evaluate_travel_ratio(days, matrix=HaversineMatrix())
    assert len(report.per_day) == 2
    assert report.overall_ratio >= 0.0
