"""Tests for src/scoring/cluster_dispersion.py — per-day 검증."""

from __future__ import annotations

from src.data.models import VRPTWDay, VRPTWPlace
from src.scoring.cluster_dispersion import (
    COMBINED_PENALTY_CAP,
    PENALTY_SWITCH_WARN,
    count_geo_cluster_backtracks,
    evaluate_cluster_dispersion,
)


def _make_place(name: str, lng: float, lat: float):
    return VRPTWPlace(
        name=name,
        lng=lng,
        lat=lat,
        open="09:00",
        close="22:00",
        stay_duration=60,
        is_depot=False,
    )


def test_compact_day_no_penalty():
    """같은 시군구 + 거리 < 30km → 패널티 0."""
    day = VRPTWDay(
        places=[
            _make_place("강남A", 127.027, 37.498),
            _make_place("강남B", 127.030, 37.500),
            _make_place("강남C", 127.025, 37.495),
        ]
    )
    sg = [["680", "680", "680"]]  # 모두 강남구
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    assert report.total_penalty == 0
    assert report.per_day[0].sigungu_switches == 0
    assert report.per_day[0].max_pairwise_km < 30


def test_lightning_pattern_high_penalty():
    """1일차에 서울↔부산 섞기 → 거리 메트릭 CRITICAL + 캡 적용."""
    day = VRPTWDay(
        places=[
            _make_place("서울 강남", 127.027, 37.498),
            _make_place("부산 해운대", 129.157, 35.158),
            _make_place("서울 종로", 126.984, 37.572),
        ]
    )
    sg = [["680", "260", "110"]]  # 강남구 → 해운대구 → 종로구
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    # 서울↔부산 직선거리 ~325km → CRITICAL
    assert report.per_day[0].max_pairwise_km > 100
    # 시군구 3회 전환 + 거리 CRITICAL → 합산 캡 적용
    assert report.total_penalty == COMBINED_PENALTY_CAP


def test_per_day_independence():
    """Day1=서울 / Day2=부산 (각 day 안에서는 응집) → 패널티 없음."""
    day1 = VRPTWDay(
        places=[
            _make_place("서울A", 127.027, 37.498),
            _make_place("서울B", 127.030, 37.500),
        ]
    )
    day2 = VRPTWDay(
        places=[
            _make_place("부산A", 129.157, 35.158),
            _make_place("부산B", 129.160, 35.160),
        ]
    )
    sg = [["680", "680"], ["260", "260"]]
    report = evaluate_cluster_dispersion([day1, day2], sigungu_codes_per_day=sg)
    assert report.total_penalty == 0


def test_geo_cluster_backtrack_gyeongju():
    """M4: 경주 — 동일 시군구지만 지리적으로 분산 왕복 → M3=0인데 M4≥1."""
    day = VRPTWDay(
        places=[
            _make_place("첨성대", 129.2191, 35.8347),  # 경주 시내
            _make_place("감포해수욕장", 129.5007, 35.7914),  # 경주 동해안 ~28km
            _make_place("안압지", 129.2246, 35.8344),  # 경주 시내 (재방문)
            _make_place("불국사", 129.3317, 35.7896),  # 중간
        ]
    )
    # 모두 경주시 → M3=0, M2=25km대 (30km 미만 → 패널티 없음)
    sg = [["경주시", "경주시", "경주시", "경주시"]]
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    metric = report.per_day[0]

    assert metric.area_backtrack_count == 0, "M3: 같은 시군구라 백트래킹 0"
    assert metric.geo_cluster_backtrack >= 1, "M4: 지리적 클러스터 재진입 탐지"
    assert report.total_penalty >= 5, "M4 패널티 발생"
    bt_rules = [d.rule for d in report.deep_dive]
    assert "geo_cluster_backtrack" in bt_rules


def test_geo_cluster_no_false_positive_sequential():
    """M4 false positive: 강남→홍대 순방향 방문은 패널티 없어야."""
    day = VRPTWDay(
        places=[
            _make_place("강남역", 127.0276, 37.4979),
            _make_place("코엑스", 127.0590, 37.5115),
            _make_place("홍대입구", 126.9248, 37.5574),
            _make_place("연남동", 126.9259, 37.5634),
        ]
    )
    bt = count_geo_cluster_backtracks(day.places)
    assert bt == 0, "순방향 방문은 지리 클러스터 백트래킹 0"


def test_geo_cluster_no_double_penalty_when_m3_fires():
    """M3가 이미 탐지한 이벤트에 M4가 중복 패널티를 추가하지 않는다.

    강남역↔역삼역: ~0.9km (같은 geo cluster), 홍대입구: 별도 cluster.
    M3: 강남→마포→강남 = 1회 탐지. M4도 동일 이벤트 탐지.
    → geo_pen = max(0, 1 - 1) = 0 → M4 DeepDive 없어야.
    """
    day = VRPTWDay(
        places=[
            _make_place("강남역", 127.0276, 37.4979),  # cluster A
            _make_place("홍대입구", 126.9248, 37.5574),  # cluster B
            _make_place("역삼역", 127.0368, 37.5006),  # cluster A (~0.9km from 강남역)
        ]
    )
    sg = [["강남구", "마포구", "강남구"]]
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    m = report.per_day[0]

    assert m.area_backtrack_count == 1, "M3: 강남→마포→강남 탐지"
    assert m.geo_cluster_backtrack >= 1, "M4: geo 클러스터도 동일 이벤트 탐지"
    geo_rules = [d.rule for d in report.deep_dive if d.rule == "geo_cluster_backtrack"]
    assert len(geo_rules) == 0, "M3가 이미 커버 → M4 DeepDive 중복 없어야"


def test_sigungu_switches_only():
    """거리는 안 멀지만 시군구 전환 4회+ → 시군구 패널티만 발생."""
    day = VRPTWDay(
        places=[
            _make_place("A", 127.00, 37.55),  # 강남
            _make_place("B", 127.01, 37.56),  # 송파 (10km 미만)
            _make_place("C", 127.02, 37.57),  # 광진 (10km 미만)
            _make_place("D", 127.03, 37.58),  # 성동 (10km 미만)
            _make_place("E", 127.04, 37.59),  # 중구 (10km 미만)
        ]
    )
    sg = [["680", "710", "215", "200", "140"]]  # 5개 다른 시군구 → 4회 전환
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    assert report.per_day[0].sigungu_switches == 4
    assert report.total_penalty >= PENALTY_SWITCH_WARN
