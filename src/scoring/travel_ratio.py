"""이동 vs 관광 시간 비율 패널티 (모듈 ⑤).

공식: travel_ratio = travel_sec / (travel_sec + dwell_sec)

기존 `phases/0-setup/analyze.py`의 정의 유지.
임계값은 구석구석 50개 / 트리플 38개 실측 P75/P90 기반.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.data.models import DeepDiveItem, VRPTWDay, VRPTWPlace
from src.validation.vrptw_engine import HaversineMatrix, TimeMatrix

# ── 임계값 (구석구석 P75=0.20, P90=0.50 기반) ─────────────────────────
WARN_THRESHOLD: float = 0.20
RISK_THRESHOLD: float = 0.40
CRIT_THRESHOLD: float = 0.60

# 패널티 점수
PENALTY_WARN: int = 5
PENALTY_RISK: int = 10
PENALTY_CRIT: int = 20


@dataclass(frozen=True)
class DayRatioMetric:
    """일자별 비율 측정 결과."""

    day_index: int
    travel_sec: int
    dwell_sec: int
    travel_ratio: float


@dataclass(frozen=True)
class TravelRatioReport:
    """전체 평가 리포트."""

    per_day: list[DayRatioMetric]
    overall_ratio: float  # 전체 일정 합산 기준
    total_penalty: int  # 일자별 패널티 합산
    deep_dive: list[DeepDiveItem]


def _compute_day_metric(
    day_idx: int,
    places: list[VRPTWPlace],
    matrix: TimeMatrix,
) -> DayRatioMetric:
    """하루 일정의 travel_sec, dwell_sec, ratio 계산."""
    travel_sec = 0
    dwell_sec = 0
    for i, place in enumerate(places):
        # depot은 체류시간 0으로 취급
        if not place.is_depot:
            dwell_sec += place.stay_duration * 60
        if i > 0:
            travel_sec += matrix.get_travel_time(places[i - 1], place)

    total = travel_sec + dwell_sec
    ratio = travel_sec / total if total > 0 else 0.0
    return DayRatioMetric(
        day_index=day_idx,
        travel_sec=travel_sec,
        dwell_sec=dwell_sec,
        travel_ratio=ratio,
    )


def _classify_ratio(ratio: float) -> tuple[int, str]:
    """비율 → (패널티, risk_label) 반환."""
    if ratio >= CRIT_THRESHOLD:
        return PENALTY_CRIT, "CRITICAL"
    if ratio >= RISK_THRESHOLD:
        return PENALTY_RISK, "WARNING"
    if ratio >= WARN_THRESHOLD:
        return PENALTY_WARN, "WARNING"
    return 0, "OK"


def evaluate_travel_ratio(
    days: list[VRPTWDay],
    matrix: TimeMatrix | None = None,
) -> TravelRatioReport:
    """전체 일정의 일자별 travel_ratio + 패널티 산출."""
    matrix = matrix or HaversineMatrix()

    per_day: list[DayRatioMetric] = []
    deep_dive: list[DeepDiveItem] = []
    total_penalty = 0
    total_travel = 0
    total_dwell = 0

    for idx, day in enumerate(days):
        metric = _compute_day_metric(idx, day.places, matrix)
        per_day.append(metric)
        total_travel += metric.travel_sec
        total_dwell += metric.dwell_sec

        penalty, risk = _classify_ratio(metric.travel_ratio)
        if penalty > 0:
            total_penalty += penalty
            travel_min = metric.travel_sec // 60
            dwell_min = metric.dwell_sec // 60
            deep_dive.append(
                DeepDiveItem(
                    fact=(
                        f"{idx + 1}일차 이동 비율 {metric.travel_ratio:.1%} "
                        f"(이동 {travel_min}분 / 관광 {dwell_min}분)"
                    ),
                    rule="travel_ratio",
                    risk=risk,  # type: ignore[arg-type]
                    suggestion=(
                        "이동 시간이 관광 시간 대비 너무 큽니다. "
                        "더 가까운 장소로 변경하거나 일정을 단순화하세요."
                    ),
                )
            )

    overall_total = total_travel + total_dwell
    overall_ratio = total_travel / overall_total if overall_total > 0 else 0.0

    return TravelRatioReport(
        per_day=per_day,
        overall_ratio=overall_ratio,
        total_penalty=total_penalty,
        deep_dive=deep_dive,
    )
