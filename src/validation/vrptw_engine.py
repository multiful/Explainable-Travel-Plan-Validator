"""VRPTW Validation Engine.

Validates travel itineraries against mathematical feasibility and efficiency.
Read-only: never modifies input data or analysis result files.

TimeMatrix interface is swappable — replace CachedRouteMatrix with a Kakao
Mobility implementation without touching solver code.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.data.models import (
    DayRouteComparison,
    DeepDiveItem,
    VRPTWDay,
    VRPTWPlace,
    VRPTWRequest,
    VRPTWResult,
)


def _time_to_minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------

EFFICIENCY_GAP_THRESHOLD: float = 0.20  # 20%: efficiency gap that triggers "low efficiency"
FATIGUE_HOURS_LIMIT: int = 12  # hours: daily schedule exceeding this incurs penalty
FATIGUE_PENALTY_PER_HOUR: int = 10  # points deducted per hour over limit
SAFETY_MARGIN_MINUTES: int = 60  # minutes: arrival within this of close → CRITICAL
PASS_THRESHOLD: int = 60  # risk_score >= this → passed

# Day-start time assumption when no depot open time is specified
DEFAULT_START_MINUTES: int = 9 * 60  # 09:00

# ---------------------------------------------------------------------------
# OR-Tools import (graceful degradation)
# ---------------------------------------------------------------------------

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    _ORTOOLS_AVAILABLE = True
except Exception:
    _ORTOOLS_AVAILABLE = False


# ---------------------------------------------------------------------------
# TimeMatrix interface
# ---------------------------------------------------------------------------


class TimeMatrix(ABC):
    """Abstract travel-time provider. Implementations are interchangeable."""

    @abstractmethod
    def get_travel_time(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int:
        """Return travel time in seconds."""


class HaversineMatrix(TimeMatrix):
    """Calibrated haversine fallback using distance-band multipliers.

    Kakao Mobility 실측 데이터(서울 5개 구간) 기반 보정:
      도심 단거리(<5km): 직선거리 대비 실제 도로 2.5배 + 신호·막힘 반영 → 유효 속도 ~12km/h
      중거리(5~50km):   도로우회 + 부분 고속화 → 유효 속도 ~22km/h
      장거리(>50km):    고속도로 주행 → 유효 속도 ~80km/h
    기존 30km/h 단일 가정 대비 도심 오차 -62~-68% → ±15% 수준으로 개선.
    """

    # (거리 상한 m, 유효 속도 m/s)
    _BANDS: tuple = (
        (5_000, 12_000 / 3600),  # 도심 <5km
        (50_000, 22_000 / 3600),  # 중거리 5~50km
        (float("inf"), 80_000 / 3600),  # 장거리 >50km
    )

    def _effective_speed(self, dist_m: float) -> float:
        for limit_m, speed in self._BANDS:
            if dist_m < limit_m:
                return speed
        return self._BANDS[-1][1]

    def get_travel_time(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int:
        dist_m = _haversine_m(origin.lat, origin.lng, destination.lat, destination.lng)
        return round(dist_m / self._effective_speed(dist_m))


class CachedRouteMatrix(TimeMatrix):
    """Uses Kakao Mobility cache (lng,lat|lng,lat → seconds). Falls back to Haversine.

    Cache keys are normalised to float tuples at construction to avoid
    string-formatting mismatches (e.g. "33.5460" vs "33.546").
    """

    def __init__(self, cache: dict[str, int]) -> None:
        # Normalise: "lng1,lat1|lng2,lat2" → (lng1, lat1, lng2, lat2)
        self._cache: dict[tuple[float, float, float, float], int] = {}
        for raw_key, val in cache.items():
            try:
                left, right = raw_key.split("|")
                lng1, lat1 = (float(x) for x in left.split(","))
                lng2, lat2 = (float(x) for x in right.split(","))
                self._cache[(lng1, lat1, lng2, lat2)] = val
            except Exception:
                pass
        self._fallback = HaversineMatrix()

    @classmethod
    def from_file(cls, path: str | Path) -> CachedRouteMatrix:
        with open(path, encoding="utf-8") as f:
            data: dict[str, int] = json.load(f)
        return cls(data)

    def get_travel_time(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int:
        if origin.lng == destination.lng and origin.lat == destination.lat:
            return 0
        fwd = (origin.lng, origin.lat, destination.lng, destination.lat)
        rev = (destination.lng, destination.lat, origin.lng, origin.lat)
        if fwd in self._cache:
            return self._cache[fwd]
        if rev in self._cache:
            return self._cache[rev]
        return self._fallback.get_travel_time(origin, destination)


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass
class _SimResult:
    """Simulation result for a single day."""

    travel_seconds: int
    visit_order: list[str]
    deep_dive: list[DeepDiveItem] = field(default_factory=list)


def _minutes_to_hhmm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}"


def _simulate_day(
    places: list[VRPTWPlace],
    matrix: TimeMatrix,
    start_minutes: int = DEFAULT_START_MINUTES,
) -> _SimResult:
    """Simulate traversal in the given order. Returns travel time and issues."""
    deep_dive: list[DeepDiveItem] = []
    total_travel_sec = 0
    current_time = start_minutes  # minutes from midnight

    for i, place in enumerate(places):
        if i == 0:
            # Arrive at first place at start_minutes or when it opens
            arrive = max(current_time, place.open_minutes)
        else:
            prev = places[i - 1]
            travel_sec = matrix.get_travel_time(prev, place)
            total_travel_sec += travel_sec
            depart = current_time
            arrive = depart + travel_sec / 60

        # --- Safety margin check ---
        minutes_before_close = place.close_minutes - arrive
        if 0 < minutes_before_close < SAFETY_MARGIN_MINUTES and not place.is_depot:
            deep_dive.append(
                DeepDiveItem(
                    fact=(
                        f"'{place.name}' 도착 예정 {_minutes_to_hhmm(arrive)}, "
                        f"영업 종료 {place.close} — {minutes_before_close:.0f}분 여유"
                    ),
                    rule="safety_margin",
                    risk="CRITICAL",
                    suggestion=(
                        f"'{place.name}' 방문 순서를 앞당기거나 "
                        f"체류 시간({place.stay_duration}분)을 줄이세요."
                    ),
                )
            )

        # --- Time window infeasibility check ---
        if arrive > place.close_minutes and not place.is_depot:
            deep_dive.append(
                DeepDiveItem(
                    fact=(
                        f"'{place.name}' 도착 예정 {_minutes_to_hhmm(arrive)}이나 "
                        f"영업 종료는 {place.close}. 입장 불가."
                    ),
                    rule="time_window_infeasibility",
                    risk="CRITICAL",
                    suggestion=f"'{place.name}'을 더 이른 시간대로 이동하거나 일정에서 제외하세요.",
                )
            )

        # Wait until open if arrived early
        effective_arrive = max(arrive, place.open_minutes)
        current_time = effective_arrive + place.stay_duration

    return _SimResult(
        travel_seconds=total_travel_sec,
        visit_order=[p.name for p in places],
        deep_dive=deep_dive,
    )


def _compute_day_total_minutes(
    places: list[VRPTWPlace],
    matrix: TimeMatrix,
    start_minutes: int = DEFAULT_START_MINUTES,
) -> float:
    """Total elapsed minutes from first departure to last arrival+stay."""
    if not places:
        return 0.0
    total_travel_sec = 0
    current_time = float(start_minutes)

    for i, place in enumerate(places):
        if i == 0:
            arrive = max(current_time, place.open_minutes)
        else:
            travel_sec = matrix.get_travel_time(places[i - 1], place)
            total_travel_sec += travel_sec
            arrive = current_time + travel_sec / 60
        effective_arrive = max(arrive, place.open_minutes)
        current_time = effective_arrive + place.stay_duration

    return current_time - start_minutes


# ---------------------------------------------------------------------------
# OR-Tools VRPTW solver (per-day, single-vehicle)
# ---------------------------------------------------------------------------


def _solve_vrptw_ortools(
    places: list[VRPTWPlace],
    matrix: TimeMatrix,
    start_minutes: int = DEFAULT_START_MINUTES,
) -> tuple[list[str], int] | None:
    """Return (optimal_order, total_travel_seconds) or None on failure."""
    n = len(places)
    if n <= 2:
        # Nothing to optimise with 0 or 1 stops (plus depot at idx 0 implicitly)
        sim = _simulate_day(places, matrix, start_minutes)
        return sim.visit_order, sim.travel_seconds

    # Build integer time matrix (seconds)
    travel = [[matrix.get_travel_time(places[i], places[j]) for j in range(n)] for i in range(n)]

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def _time_callback(from_idx: int, to_idx: int) -> int:
        fi = manager.IndexToNode(from_idx)
        ti = manager.IndexToNode(to_idx)
        return travel[fi][ti] + places[fi].stay_duration * 60

    cb_idx = routing.RegisterTransitCallback(_time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(cb_idx)

    # Time dimension with slack (waiting allowed)
    # OR-Tools AddDimension: (evaluator_index, slack_max, capacity, fix_start_cumul_to_zero, name)
    routing.AddDimension(
        cb_idx,
        24 * 3600,  # slack_max (max waiting time)
        24 * 3600,  # capacity (max total time)
        False,  # fix_start_cumul_to_zero
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    for i, place in enumerate(places):
        idx = manager.NodeToIndex(i)
        open_sec = place.open_minutes * 60
        close_sec = place.close_minutes * 60
        time_dim.CumulVar(idx).SetRange(open_sec, close_sec)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.time_limit.seconds = 5

    solution = routing.SolveWithParameters(params)
    if not solution:
        return None

    # Extract route
    route: list[str] = []
    total_travel = 0
    idx = routing.Start(0)
    prev_node: int | None = None
    while not routing.IsEnd(idx):
        node = manager.IndexToNode(idx)
        route.append(places[node].name)
        if prev_node is not None:
            total_travel += travel[prev_node][node]
        prev_node = node
        idx = solution.Value(routing.NextVar(idx))

    return route, total_travel


# ---------------------------------------------------------------------------
# Depot constraint checker
# ---------------------------------------------------------------------------


def _check_depot_constraints(
    days: list[VRPTWDay],
) -> list[DeepDiveItem]:
    """Enforce depot rules for 2박3일+ (3+ days). 1박2일 is exempt."""
    issues: list[DeepDiveItem] = []
    n = len(days)
    if n < 3:
        return issues

    def _has_depot(places: list[VRPTWPlace], position: str) -> bool:
        if position == "first":
            return places[0].is_depot if places else False
        return places[-1].is_depot if places else False

    for day_idx, day in enumerate(days):
        places = day.places
        is_first_day = day_idx == 0
        is_last_day = day_idx == n - 1

        if is_first_day:
            # Day 1: must end at depot
            if not _has_depot(places, "last"):
                issues.append(
                    DeepDiveItem(
                        fact=f"1일차 마지막 장소가 숙소(depot)가 아닙니다. ('{places[-1].name}')",
                        rule="depot_constraint",
                        risk="CRITICAL",
                        suggestion="1일차 일정 마지막에 숙소 복귀를 추가하세요.",
                    )
                )
        elif is_last_day:
            # Last day: must start at depot
            if not _has_depot(places, "first"):
                issues.append(
                    DeepDiveItem(
                        fact=f"마지막 날 첫 장소가 숙소(depot)가 아닙니다. ('{places[0].name}')",
                        rule="depot_constraint",
                        risk="CRITICAL",
                        suggestion="마지막 날 일정은 숙소 출발로 시작해야 합니다.",
                    )
                )
        else:
            # Middle days: must start AND end at depot
            if not _has_depot(places, "first"):
                issues.append(
                    DeepDiveItem(
                        fact=f"{day_idx + 1}일차 첫 장소가 숙소(depot)가 아닙니다. ('{places[0].name}')",
                        rule="depot_constraint",
                        risk="CRITICAL",
                        suggestion=f"{day_idx + 1}일차는 숙소에서 출발해야 합니다.",
                    )
                )
            if not _has_depot(places, "last"):
                issues.append(
                    DeepDiveItem(
                        fact=f"{day_idx + 1}일차 마지막 장소가 숙소(depot)가 아닙니다. ('{places[-1].name}')",
                        rule="depot_constraint",
                        risk="CRITICAL",
                        suggestion=f"{day_idx + 1}일차는 숙소로 귀환해야 합니다.",
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class VRPTWEngine:
    """VRPTW-based travel itinerary validator.

    Accepts a TimeMatrix implementation; swap CachedRouteMatrix for
    any other provider (e.g. Kakao Mobility) without touching this class.
    """

    def __init__(
        self,
        matrix: TimeMatrix | None = None,
        ortools_available: bool | None = None,
    ) -> None:
        self._matrix = matrix or HaversineMatrix()
        if ortools_available is None:
            self._ortools = _ORTOOLS_AVAILABLE
        else:
            self._ortools = ortools_available

    def validate(self, request: VRPTWRequest) -> VRPTWResult:
        deep_dive: list[DeepDiveItem] = []
        day_comparisons: list[DayRouteComparison] = []
        total_user_travel = 0
        total_optimal_travel: int | None = 0 if self._ortools else None

        # Depot constraint check
        deep_dive.extend(_check_depot_constraints(request.days))

        start_minutes = _time_to_minutes(request.start_time)
        for day_idx, day in enumerate(request.days):
            places = day.places
            start_min = start_minutes

            # Determine day start from depot open time if present
            if places and places[0].is_depot:
                start_min = max(start_minutes, places[0].open_minutes)

            # Simulate user route
            user_sim = _simulate_day(places, self._matrix, start_min)
            total_user_travel += user_sim.travel_seconds
            deep_dive.extend(user_sim.deep_dive)

            # Fatigue check for this day
            day_total_min = _compute_day_total_minutes(places, self._matrix, start_min)
            if day_total_min > FATIGUE_HOURS_LIMIT * 60:
                excess_h = (day_total_min - FATIGUE_HOURS_LIMIT * 60) / 60
                deep_dive.append(
                    DeepDiveItem(
                        fact=(
                            f"{day_idx + 1}일차 총 소요 시간 {day_total_min:.0f}분 "
                            f"({day_total_min / 60:.1f}시간) — "
                            f"{FATIGUE_HOURS_LIMIT}시간 초과 {excess_h:.1f}시간"
                        ),
                        rule="fatigue",
                        risk="WARNING",
                        suggestion="장소 수를 줄이거나 체류 시간을 단축해 일정을 12시간 이내로 조정하세요.",
                    )
                )

            # OR-Tools optimal route
            optimal_order: list[str] | None = None
            optimal_travel: int | None = None
            if self._ortools:
                result = _solve_vrptw_ortools(places, self._matrix, start_min)
                if result is not None:
                    optimal_order, optimal_travel = result
                    if total_optimal_travel is not None:
                        total_optimal_travel += optimal_travel

            day_comparisons.append(
                DayRouteComparison(
                    day_index=day_idx,
                    user_order=[p.name for p in places],
                    optimal_order=optimal_order,
                    user_travel_seconds=user_sim.travel_seconds,
                    optimal_travel_seconds=optimal_travel,
                )
            )

        # Efficiency gap
        efficiency_gap: float | None = None
        if total_optimal_travel is not None and total_optimal_travel > 0 and total_user_travel > 0:
            efficiency_gap = (total_user_travel - total_optimal_travel) / total_optimal_travel
            if efficiency_gap > EFFICIENCY_GAP_THRESHOLD:
                deep_dive.append(
                    DeepDiveItem(
                        fact=(
                            f"사용자 이동 시간 {total_user_travel}초 vs "
                            f"최적 {total_optimal_travel}초 "
                            f"(효율성 격차 {efficiency_gap:.1%})"
                        ),
                        rule="efficiency_gap",
                        risk="WARNING",
                        suggestion="VRPTW 최적 순서를 참고해 방문 순서를 재배치하세요.",
                    )
                )

        # Risk score
        risk_score = self._compute_risk_score(deep_dive, efficiency_gap, request.days)
        passed = risk_score >= PASS_THRESHOLD

        summary = (
            f"종합 Risk Score: {risk_score}/100 — "
            f"{'PASS' if passed else 'FAIL'}. "
            f"총 이동 시간 {total_user_travel}초"
            + (f", 최적 대비 {efficiency_gap:.1%} 초과" if efficiency_gap is not None else "")
            + f". 이슈 {len(deep_dive)}건."
        )

        return VRPTWResult(
            risk_score=risk_score,
            passed=passed,
            user_total_travel_seconds=total_user_travel,
            optimal_total_travel_seconds=total_optimal_travel,
            efficiency_gap=efficiency_gap,
            optimal_route=day_comparisons if self._ortools else None,
            deep_dive=deep_dive,
            summary=summary,
        )

    def _compute_risk_score(
        self,
        deep_dive: list[DeepDiveItem],
        efficiency_gap: float | None,
        days: list[VRPTWDay],
    ) -> int:
        score = 100

        # Penalise CRITICAL issues (15 pts each)
        critical_count = sum(1 for d in deep_dive if d.risk == "CRITICAL")
        score -= critical_count * 15

        # Penalise WARNING issues (5 pts each)
        warning_count = sum(1 for d in deep_dive if d.risk == "WARNING")
        score -= warning_count * 5

        # Efficiency gap overrun (additional penalty)
        if efficiency_gap is not None and efficiency_gap > EFFICIENCY_GAP_THRESHOLD:
            overshoot = efficiency_gap - EFFICIENCY_GAP_THRESHOLD
            score -= min(int(overshoot * 100), 20)

        # Fatigue: extra deduction already encoded in deep_dive above;
        # additionally compute raw fatigue hours across all days
        for _day_idx, day in enumerate(days):
            day_total_min = _compute_day_total_minutes(
                day.places, self._matrix, DEFAULT_START_MINUTES
            )
            if day_total_min > FATIGUE_HOURS_LIMIT * 60:
                excess_h = (day_total_min - FATIGUE_HOURS_LIMIT * 60) / 60
                score -= int(excess_h) * FATIGUE_PENALTY_PER_HOUR

        return max(0, min(100, score))
