"""지역별 동적 임계값 설정 — 3-tier POI 밀도 기반.

시군구 코드(5자리) 기준으로 밀도 티어를 결정하고,
VRPTW/ClusterDispersion 임계값을 동적으로 반환한다.

Tier 기준 (향후 POI 밀도 분석으로 교체 예정):
  HIGH   — 서울/부산/수도권 핵심 도심 (≥300 POI/km²)
  MEDIUM — 지방 광역시, 수도권 외곽 (100–299 POI/km²)
  LOW    — 농어촌·산간·도서 지역 (<100 POI/km²)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegionThresholds:
    """지역 티어별 VRPTW/Scoring 임계값."""

    tier: str  # "high" | "medium" | "low"

    # ── ClusterDispersion ────────────────────────────────────────────
    dist_warn_km: float  # M2 경고 임계 직선거리
    dist_risk_km: float
    dist_crit_km: float
    switch_warn: int  # M1 시군구 전환 경고 횟수
    switch_crit: int

    # ── HardFail / Warning ───────────────────────────────────────────
    physical_strain_km: float  # 1일 총 이동거리 경고 임계
    dense_schedule_min: int  # 일정 과밀 임계 (분)

    # ── Scoring ──────────────────────────────────────────────────────
    fatigue_hours_limit: int  # 피로 패널티 기준 시간


TIER_HIGH_DENSITY = RegionThresholds(
    tier="high",
    dist_warn_km=10.0,
    dist_risk_km=20.0,
    dist_crit_km=40.0,
    switch_warn=4,
    switch_crit=6,
    physical_strain_km=20.0,
    dense_schedule_min=420,
    fatigue_hours_limit=10,
)

TIER_MEDIUM_DENSITY = RegionThresholds(
    tier="medium",
    dist_warn_km=30.0,
    dist_risk_km=50.0,
    dist_crit_km=100.0,
    switch_warn=3,
    switch_crit=4,
    physical_strain_km=30.0,
    dense_schedule_min=480,
    fatigue_hours_limit=12,
)

TIER_LOW_DENSITY = RegionThresholds(
    tier="low",
    dist_warn_km=50.0,
    dist_risk_km=80.0,
    dist_crit_km=150.0,
    switch_warn=2,
    switch_crit=3,
    physical_strain_km=50.0,
    dense_schedule_min=540,
    fatigue_hours_limit=14,
)

# 서울 핵심 25개 자치구 + 경기 핵심 시
_HIGH_DENSITY_CODES: frozenset[str] = frozenset(
    {
        "11110",
        "11140",
        "11170",
        "11200",
        "11215",
        "11230",
        "11260",
        "11290",
        "11305",
        "11320",
        "11350",
        "11380",
        "11410",
        "11440",
        "11470",
        "11500",
        "11530",
        "11545",
        "11560",
        "11590",
        "11620",
        "11650",
        "11680",
        "11710",
        "11740",  # 서울 25구
        "26110",
        "26140",
        "26170",
        "26200",
        "26230",
        "26260",
        "26290",
        "26320",
        "26350",
        "26380",
        "26410",
        "26440",
        "26470",
        "26500",
        "26530",  # 부산 15개 구
        "41131",
        "41133",
        "41135",
        "41171",
        "41173",  # 수원·성남·고양
    }
)

_MEDIUM_DENSITY_CODES: frozenset[str] = frozenset(
    {
        "27110",
        "27140",
        "27170",
        "27200",
        "27230",
        "27260",
        "27290",  # 대구
        "28110",
        "28140",
        "28170",
        "28200",
        "28237",
        "28245",
        "28260",  # 인천
        "29110",
        "29140",
        "29155",
        "29170",
        "29200",  # 광주
        "30110",
        "30140",
        "30170",
        "30200",
        "30230",  # 대전
        "31110",
        "31140",
        "31170",
        "31200",  # 울산
        "36110",  # 세종
    }
)


def get_thresholds(sigungu_code: str | None) -> RegionThresholds:
    """시군구 코드로 지역 임계값 반환. 미지정·미분류 → MEDIUM."""
    if sigungu_code is None:
        return TIER_MEDIUM_DENSITY
    code5 = sigungu_code[:5]
    if code5 in _HIGH_DENSITY_CODES:
        return TIER_HIGH_DENSITY
    if code5 in _MEDIUM_DENSITY_CODES:
        return TIER_MEDIUM_DENSITY
    return TIER_LOW_DENSITY
