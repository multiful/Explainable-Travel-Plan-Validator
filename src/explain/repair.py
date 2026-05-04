"""Minimal Interference Repair Engine.

교정 우선순위 (Hard Fail 발생 시 순서대로 시도):
  1. Re-ordering   : 순열 탐색으로 Hard Fail이 없는 방문 순서 탐색 (n ≤ 7)
  2. Stay-time Tuning : 체류 시간을 최솟값까지 5분 단위로 감소
  3. Outlier Deletion : 이동 거리 절감 최대 장소(지리적 이상치)를 삭제 후보로 제안

이 엔진은 '장소 대체(substitution)'를 수행하지 않는다.
사용자가 선택한 POI 목록을 보존하며 제약 조건만을 최적화하는 수학적 교정 도구다.
"""
from __future__ import annotations

import dataclasses
import itertools
import re
from dataclasses import dataclass, field

from src.data.dwell_db import MANUAL_OVERRIDES as _DWELL_OVERRIDES
from src.data.models import HardFail, ItineraryPlan, POI
from src.data.party_config import get_party_profile
from src.utils.geo import build_dist_cache, get_travel_min, haversine_km
from src.validation.hard_fail import HardFailDetector

_MAX_PERM_N: int = 7       # 7! = 5040 — 탐색 허용 상한
_MIN_DWELL_RATIO: float = 0.5   # 최소 체류 = 원래의 50%
_MIN_DWELL_ABS: int = 20        # 절대 최솟값 20분


def _norm(name: str) -> str:
    return re.sub(r"[\s·ㆍ\-\/\(\)（）「」\.,]+", "", name).lower()


def _min_dwell_for(name: str, original_min: int) -> int:
    """dwell_db 기준 최소 권장 체류 시간 (50% 기준, 절대 최솟값 20분)."""
    key = _norm(name)
    for k, (mn, _) in _DWELL_OVERRIDES.items():
        if _norm(k) == key:
            return max(_MIN_DWELL_ABS, int(mn * _MIN_DWELL_RATIO))
    return max(_MIN_DWELL_ABS, int(original_min * _MIN_DWELL_RATIO))


@dataclass
class ReorderSuggestion:
    day_index: int
    suggested_order: list[str]
    reason: str


@dataclass
class TimeTuneSuggestion:
    day_index: int
    adjustments: dict[str, int]  # poi_name → 조정 후 duration_min
    saved_minutes: int
    reason: str


@dataclass
class DeletionSuggestion:
    day_index: int
    candidate_name: str
    travel_saved_km: float
    reason: str


@dataclass
class RepairResult:
    reorders: list[ReorderSuggestion] = field(default_factory=list)
    time_tunes: list[TimeTuneSuggestion] = field(default_factory=list)
    deletions: list[DeletionSuggestion] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.reorders or self.time_tunes or self.deletions)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


class RepairEngine:
    """Minimal Interference 교정 엔진. External I/O 없음."""

    def __init__(self) -> None:
        self._hard_fail = HardFailDetector()

    def repair(
        self,
        plan: ItineraryPlan,
        per_day_pois: list[list[POI]],
        matrix: dict,
        hard_fails: list[HardFail],
    ) -> RepairResult:
        """3단계 교정 시도. Hard Fail이 없으면 즉시 빈 결과 반환."""
        result = RepairResult()
        if not hard_fails:
            return result

        for day_idx, day_pois in enumerate(per_day_pois):
            if not day_pois:
                continue

            # Step 1: Re-ordering — 순서만 바꿔서 Hard Fail 제거 가능 여부 탐색
            reorder = self._try_reorder(plan, day_idx, day_pois, matrix)
            if reorder:
                result.reorders.append(reorder)
                continue  # 이 날은 재배치로 해결 → Step 2/3 불필요

            # Step 2: Stay-time Tuning — 체류 시간 압축으로 과밀 완화
            tune = self._try_time_tune(plan, day_idx, day_pois, matrix)
            if tune:
                result.time_tunes.append(tune)

            # Step 3: Outlier Deletion — 최후 수단, 지리적 이상치 삭제 제안
            deletion = self._suggest_deletion(day_idx, day_pois)
            if deletion:
                result.deletions.append(deletion)

        return result

    def _try_reorder(
        self,
        plan: ItineraryPlan,
        day_idx: int,
        pois: list[POI],
        matrix: dict,
    ) -> ReorderSuggestion | None:
        """n ≤ 7인 경우 순열 전수 탐색으로 Hard Fail 없는 순서 반환."""
        n = len(pois)
        if n <= 1 or n > _MAX_PERM_N:
            return None

        original = [p.name for p in pois]
        for perm in itertools.permutations(pois):
            perm_list = list(perm)
            if [p.name for p in perm_list] == original:
                continue
            if not self._hard_fail.detect(plan=plan, pois=perm_list, matrix=matrix):
                names = [p.name for p in perm_list]
                return ReorderSuggestion(
                    day_index=day_idx,
                    suggested_order=names,
                    reason=(
                        f"{day_idx + 1}일차 방문 순서 재배치만으로 모든 제약이 해소됩니다. "
                        f"제안 순서: {' → '.join(names)}"
                    ),
                )
        return None

    def _try_time_tune(
        self,
        plan: ItineraryPlan,
        day_idx: int,
        pois: list[POI],
        matrix: dict,
    ) -> TimeTuneSuggestion | None:
        """체류 시간을 최솟값까지 5분 단위로 줄여 일정 과밀 완화."""
        profile = get_party_profile(plan.party_type)
        limit = int(profile.fatigue_hours * 60)
        dist_cache = build_dist_cache(pois)

        travel_total = sum(
            get_travel_min(matrix, i - 1, i, pois[i - 1], pois[i], dist_cache)
            for i in range(1, len(pois))
        )
        total = travel_total + sum(p.duration_min for p in pois)
        if total <= limit:
            return None

        needed = int(total - limit)
        adjustments: dict[str, int] = {}
        # 체류 시간이 긴 장소부터 깎기 (최대 절감 효과)
        for poi in sorted(pois, key=lambda p: p.duration_min, reverse=True):
            min_d = _min_dwell_for(poi.name, poi.duration_min)
            headroom = poi.duration_min - min_d
            cut = min(headroom, ((min(needed, headroom) // 5) + 1) * 5)
            cut = min(headroom, cut)
            cut = (cut // 5) * 5
            if cut <= 0:
                continue
            adjustments[poi.name] = poi.duration_min - cut
            needed -= cut
            if needed <= 0:
                break

        if not adjustments:
            return None

        saved = sum(
            poi.duration_min - adjustments[poi.name]
            for poi in pois if poi.name in adjustments
        )
        return TimeTuneSuggestion(
            day_index=day_idx,
            adjustments=adjustments,
            saved_minutes=saved,
            reason=(
                f"{day_idx + 1}일차 체류 시간 조정으로 {saved}분 절감 가능합니다. "
                "각 장소의 최소 권장 체류 시간(원래의 50%)을 유지하며 일정을 압축합니다."
            ),
        )

    def _suggest_deletion(
        self,
        day_idx: int,
        pois: list[POI],
    ) -> DeletionSuggestion | None:
        """이동 거리 절감량이 최대인 장소(지리적 이상치)를 삭제 후보로 제안.

        삭제 비용 = 제거 시 이동 절감(before→i + i→after) - 우회 거리(before→after).
        이 값이 가장 큰 장소가 동선 파괴의 주범이다.
        """
        if len(pois) < 3:
            return None

        dist_cache = build_dist_cache(pois)
        max_savings = -1.0
        best_idx = -1

        for i, poi in enumerate(pois):
            before = pois[i - 1] if i > 0 else None
            after = pois[i + 1] if i < len(pois) - 1 else None

            detour = 0.0
            if before:
                detour += dist_cache.get((i - 1, i), 0.0)
            if after:
                detour += dist_cache.get((i, i + 1), 0.0)

            bypass = (
                haversine_km(before.lat, before.lng, after.lat, after.lng)
                if before and after else 0.0
            )

            savings = detour - bypass
            if savings > max_savings:
                max_savings = savings
                best_idx = i

        if best_idx < 0 or max_savings <= 0:
            return None

        name = pois[best_idx].name
        return DeletionSuggestion(
            day_index=day_idx,
            candidate_name=name,
            travel_saved_km=round(max_savings, 1),
            reason=(
                f"'{name}'이(가) 동선상 지리적 이상치입니다. "
                f"이 장소를 제외하면 불필요한 이동 {max_savings:.1f}km가 절감됩니다. "
                "나머지 장소는 그대로 유지됩니다."
            ),
        )
