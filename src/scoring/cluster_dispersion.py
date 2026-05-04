"""경로 밀집도 / 번개패턴 탐지 (모듈 ⑥) — Per-day 검증.

사용자 의도 (Q3):
  "1일차에는 목적지 근처로, 2일차에는 또 다른 목적지" — 하루 안에서 너무
  멀리 떨어진 장소 배치 시 패널티. 다일 간 거리(Day1↔Day2)는 패널티 없음.

네 메트릭 (모두 위반 시 합산 캡 -20 적용 — 이중 패널티 방지):
  M1. sigungu_switches (per-day) — 같은 day 안에서 lDongSignguCd 변경 횟수
  M2. max_pairwise_distance_km (per-day) — 같은 day 안 좌표쌍 최대 직선거리
  M3. area_backtrack_count (per-day) — 시군구 기반 비연속 재진입 (행정 경계)
      ex) 강남→홍대→강남 = 1회, 정방향 4구역 순회 = 0회
  M4. geo_cluster_backtrack (per-day) — DBSCAN 지리적 클러스터 기반 비연속 재진입
      M3 보완: 경주·제주 등 대형 시군구 내부에서 지리적으로 흩어진 경우 탐지.
      eps=2.0km (도보 25분). sklearn 없으면 자동 스킵.
      per-request 즉석 계산 (4~8 POI → <1ms, DB 사전 클러스터링 불필요).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.data.models import DeepDiveItem, VRPTWDay, VRPTWPlace
from src.utils.geo import haversine_km as _haversine_km

try:
    import numpy as np
    from sklearn.cluster import DBSCAN as _DBSCAN
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

_EARTH_R_KM = 6371.0

# ── M1: 시군구 전환 임계값 ────────────────────────────────────────────
SWITCH_WARN: int = 3
SWITCH_CRIT: int = 4
PENALTY_SWITCH_WARN: int = 5
PENALTY_SWITCH_CRIT: int = 10

# ── M2: 최대 직선거리 임계값 (km) ─────────────────────────────────────
DIST_WARN_KM: float = 30.0
DIST_RISK_KM: float = 50.0
DIST_CRIT_KM: float = 100.0
PENALTY_DIST_WARN: int = 5
PENALTY_DIST_RISK: int = 10
PENALTY_DIST_CRIT: int = 20

# ── M3: 시군구 백트래킹 임계값 ───────────────────────────────────────
BACKTRACK_WARN: int = 1
BACKTRACK_CRIT: int = 2
PENALTY_BACKTRACK_WARN: int = 5
PENALTY_BACKTRACK_CRIT: int = 10

# ── M4: 지리 클러스터 백트래킹 임계값 ────────────────────────────────
GEO_BT_WARN: int = 1
GEO_BT_CRIT: int = 2
PENALTY_GEO_BT_WARN: int = 5
PENALTY_GEO_BT_CRIT: int = 10
DBSCAN_EPS_KM: float = 2.0   # 도보 25분 ≈ 2km

# ── 합산 캡 ──────────────────────────────────────────────────────────
COMBINED_PENALTY_CAP: int = 20


def count_area_backtracks(sigungu_codes: list[str]) -> int:
    """M3: 시군구 기반 비연속 구역 재진입 횟수.

    강남→홍대→강남 = 1, 순방향 4구역 순회 = 0.
    """
    seen: set[str] = set()
    prev: str | None = None
    count = 0
    for code in sigungu_codes:
        if code in seen and code != prev:
            count += 1
        seen.add(code)
        prev = code
    return count


def _count_label_backtracks(labels: list[int]) -> int:
    """클러스터 레이블 리스트에서 비연속 재진입 횟수 계산 (M4 공용)."""
    seen: set[int] = set()
    prev: int | None = None
    count = 0
    for lbl in labels:
        if lbl in seen and lbl != prev:
            count += 1
        seen.add(lbl)
        prev = lbl
    return count


def count_geo_cluster_backtracks(
    places: list[VRPTWPlace],
    eps_km: float = DBSCAN_EPS_KM,
) -> int:
    """M4: DBSCAN 지리 클러스터 기반 비연속 재진입 횟수.

    M3(시군구 기반)가 잡지 못하는 대형 시군구 내부 분산 케이스 보완.
    경주·제주·강원 지방 목적지에서 효과적.
    sklearn 미설치 시 0 반환 (graceful fallback).
    """
    if not _SKLEARN_AVAILABLE or len(places) < 2:
        return 0
    coords = np.radians([[p.lat, p.lng] for p in places])
    eps_rad = eps_km / _EARTH_R_KM
    labels: list[int] = _DBSCAN(
        eps=eps_rad, min_samples=1, metric="haversine"
    ).fit_predict(coords).tolist()
    return _count_label_backtracks(labels)


@dataclass(frozen=True)
class DayDispersionMetric:
    """일자별 밀집도 측정."""
    day_index: int
    sigungu_switches: int
    max_pairwise_km: float
    sigungu_codes_visited: list[str]
    area_backtrack_count: int = 0       # M3 시군구 기반
    geo_cluster_backtrack: int = 0      # M4 DBSCAN 지리 기반


@dataclass(frozen=True)
class ClusterDispersionReport:
    per_day: list[DayDispersionMetric]
    total_penalty: int
    deep_dive: list[DeepDiveItem]


def _compute_day_dispersion(
    day_idx: int,
    places: list[VRPTWPlace],
    sigungu_codes: list[str | None] | None = None,
) -> DayDispersionMetric:
    """하루 일정의 네 메트릭 계산."""
    # ── M1 ──
    sigungus: list[str] = [c for c in (sigungu_codes or []) if c]
    switches = sum(1 for a, b in zip(sigungus, sigungus[1:]) if a != b)

    # ── M2 ──
    max_dist = 0.0
    n = len(places)
    for i in range(n):
        for j in range(i + 1, n):
            d = _haversine_km(places[i].lat, places[i].lng, places[j].lat, places[j].lng)
            if d > max_dist:
                max_dist = d

    # ── M3 ──
    backtrack = count_area_backtracks(sigungus)

    # ── M4 ──
    geo_bt = count_geo_cluster_backtracks(places)

    return DayDispersionMetric(
        day_index=day_idx,
        sigungu_switches=switches,
        max_pairwise_km=round(max_dist, 2),
        sigungu_codes_visited=list(set(sigungus)),
        area_backtrack_count=backtrack,
        geo_cluster_backtrack=geo_bt,
    )


def _switch_penalty(switches: int) -> int:
    if switches >= SWITCH_CRIT:
        return PENALTY_SWITCH_CRIT
    if switches >= SWITCH_WARN:
        return PENALTY_SWITCH_WARN
    return 0


def _distance_penalty(dist_km: float) -> int:
    if dist_km >= DIST_CRIT_KM:
        return PENALTY_DIST_CRIT
    if dist_km >= DIST_RISK_KM:
        return PENALTY_DIST_RISK
    if dist_km >= DIST_WARN_KM:
        return PENALTY_DIST_WARN
    return 0


def _backtrack_penalty(count: int) -> int:
    if count >= BACKTRACK_CRIT:
        return PENALTY_BACKTRACK_CRIT
    if count >= BACKTRACK_WARN:
        return PENALTY_BACKTRACK_WARN
    return 0


def _geo_bt_penalty(count: int, m3_count: int) -> int:
    """M4 패널티. M3가 이미 같은 이벤트를 탐지한 경우 중복 방지."""
    net = max(0, count - m3_count)  # M3이 미탐지한 순증분만 패널티
    if net >= GEO_BT_CRIT:
        return PENALTY_GEO_BT_CRIT
    if net >= GEO_BT_WARN:
        return PENALTY_GEO_BT_WARN
    return 0


def evaluate_cluster_dispersion(
    days: list[VRPTWDay],
    sigungu_codes_per_day: list[list[str | None]] | None = None,
) -> ClusterDispersionReport:
    """전체 일정의 per-day 밀집도 + 패널티 산출.

    sigungu_codes_per_day: [day_idx][place_idx] 구조. None이면 M1/M3 스킵.
    """
    per_day: list[DayDispersionMetric] = []
    deep_dive: list[DeepDiveItem] = []
    total_penalty = 0

    for idx, day in enumerate(days):
        sg = sigungu_codes_per_day[idx] if sigungu_codes_per_day and idx < len(sigungu_codes_per_day) else None
        metric = _compute_day_dispersion(idx, day.places, sg)
        per_day.append(metric)

        sw_pen  = _switch_penalty(metric.sigungu_switches)
        ds_pen  = _distance_penalty(metric.max_pairwise_km)
        bt_pen  = _backtrack_penalty(metric.area_backtrack_count)
        geo_pen = _geo_bt_penalty(metric.geo_cluster_backtrack, metric.area_backtrack_count)

        day_penalty = min(sw_pen + ds_pen + bt_pen + geo_pen, COMBINED_PENALTY_CAP)
        total_penalty += day_penalty

        if bt_pen > 0:
            deep_dive.append(DeepDiveItem(
                fact=(
                    f"{idx + 1}일차 구역 백트래킹 {metric.area_backtrack_count}회 탐지 "
                    f"(이미 방문한 시군구에 다시 되돌아옴)"
                ),
                rule="area_backtrack",
                risk="WARNING" if bt_pen == PENALTY_BACKTRACK_WARN else "CRITICAL",
                suggestion=(
                    "이미 방문한 지역으로 되돌아가는 동선이 있습니다. "
                    "같은 구역 방문을 연속으로 묶어 이동 낭비를 줄이세요."
                ),
            ))
        if geo_pen > 0:
            deep_dive.append(DeepDiveItem(
                fact=(
                    f"{idx + 1}일차 지리적 클러스터 백트래킹 {metric.geo_cluster_backtrack}회 탐지 "
                    f"(같은 시군구 내 지리적으로 분산된 구역 간 왕복)"
                ),
                rule="geo_cluster_backtrack",
                risk="WARNING" if geo_pen == PENALTY_GEO_BT_WARN else "CRITICAL",
                suggestion=(
                    "같은 행정구역 안에서도 멀리 떨어진 장소를 왕복하고 있습니다. "
                    "인접한 장소끼리 묶어 방문 순서를 재배치하세요."
                ),
            ))
        if sw_pen > 0:
            deep_dive.append(DeepDiveItem(
                fact=(
                    f"{idx + 1}일차 시군구 전환 {metric.sigungu_switches}회 "
                    f"(방문: {', '.join(metric.sigungu_codes_visited)})"
                ),
                rule="cluster_dispersion_switches",
                risk="WARNING" if sw_pen == PENALTY_SWITCH_WARN else "CRITICAL",
                suggestion=(
                    "하루 안에 너무 많은 시군구를 이동합니다. "
                    "같은 지역 내 장소로 묶어주세요."
                ),
            ))
        if ds_pen > 0:
            risk = "CRITICAL" if ds_pen == PENALTY_DIST_CRIT else "WARNING"
            deep_dive.append(DeepDiveItem(
                fact=(
                    f"{idx + 1}일차 최대 직선거리 {metric.max_pairwise_km}km "
                    f"({len(day.places)}개 장소)"
                ),
                rule="cluster_dispersion_distance",
                risk=risk,  # type: ignore[arg-type]
                suggestion=(
                    "하루 안에 멀리 떨어진 장소들이 섞여 있습니다. "
                    "1일차는 목적지 근처에 집중하고, 다른 지역은 다른 날로 분리하세요."
                ),
            ))

    return ClusterDispersionReport(
        per_day=per_day,
        total_penalty=total_penalty,
        deep_dive=deep_dive,
    )
