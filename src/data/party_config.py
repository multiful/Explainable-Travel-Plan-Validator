"""동행 유형별 이동 속도 보정 계수 및 피로도 임계값.

이동수단은 항상 자동차이므로 speed_factor는 Haversine 폴백 거리 기반
체력 부담(Physical Strain) 임계값 보정에만 사용된다.
- speed_factor < 1.0 → 더 낮은 거리에서 WARNING 발동 (e.g. 아기동반)
- fatigue_hours → DENSE_SCHEDULE WARNING 임계 시간

피로도 임계값 정책:
  혼자 / 친구 / 연인  : 12h  (일반 성인 그룹)
  가족              : 10h  (어린 자녀 동반 가능성)
  아기동반 / 어르신동반: 8h   (취약 그룹 동반, 조기 경고)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PartyProfile:
    speed_factor: float  # 체력 부담 임계 보정 계수 (1.0 = 기준)
    fatigue_hours: int  # 일정 과밀 경고 기준 시간


PARTY_PROFILES: dict[str, PartyProfile] = {
    "혼자": PartyProfile(speed_factor=1.0, fatigue_hours=12),
    "친구": PartyProfile(speed_factor=1.0, fatigue_hours=12),
    "연인": PartyProfile(speed_factor=1.0, fatigue_hours=12),
    "가족": PartyProfile(speed_factor=0.9, fatigue_hours=10),
    "아기동반": PartyProfile(speed_factor=0.8, fatigue_hours=8),
    "어르신동반": PartyProfile(speed_factor=0.8, fatigue_hours=8),
}

_DEFAULT = PARTY_PROFILES["친구"]


def get_party_profile(party_type: str) -> PartyProfile:
    """party_type 문자열 → PartyProfile. 미등록 값은 '친구' 기준 반환."""
    return PARTY_PROFILES.get(party_type, _DEFAULT)
