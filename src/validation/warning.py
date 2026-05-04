"""Warning 탐지기 (동선 비효율·일정 과밀·체력 부담·목적 부적합·구역 재방문)."""
from __future__ import annotations

from src.data.models import ItineraryPlan, POI, Warning
from src.data.party_config import get_party_profile
from src.utils.geo import build_dist_cache, get_travel_min, haversine_km, nn_heuristic_km

DEFAULT_START_MINUTES: int = 9 * 60  # 09:00

WARNING_TYPES = {
    "DENSE_SCHEDULE":    ("일정 과밀",     "Medium"),
    "INEFFICIENT_ROUTE": ("동선 비효율",   "Medium"),
    "PHYSICAL_STRAIN":   ("체력 부담",     "Medium"),
    "PURPOSE_MISMATCH":  ("목적 부적합",   "Medium-Low"),
    "AREA_REVISIT":      ("구역 재방문",   "Medium"),
    "CUMULATIVE_FATIGUE": ("누적 피로도",  "Medium"),
}

INTENT_VECTORS: dict[str, dict[str, float]] = {
    "cultural":  {"14": 0.6, "12": 0.2, "15": 0.1, "other": 0.1},
    "nature":    {"12": 0.5, "15": 0.3, "14": 0.1, "other": 0.1},
    "shopping":  {"38": 0.5, "12": 0.3, "14": 0.1, "other": 0.1},
    "food":      {"39": 0.6, "12": 0.2, "14": 0.1, "other": 0.1},
    "adventure": {"15": 0.6, "12": 0.2, "14": 0.1, "other": 0.1},
}


def _cosine_distance(v1: dict[str, float], v2: dict[str, float]) -> float:
    import math
    keys = set(v1) | set(v2)
    dot = sum(v1.get(k, 0.0) * v2.get(k, 0.0) for k in keys)
    norm1 = math.sqrt(sum(x ** 2 for x in v1.values()))
    norm2 = math.sqrt(sum(x ** 2 for x in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 1.0
    return 1.0 - dot / (norm1 * norm2)


class WarningDetector:
    """여행 일정의 Soft Warning 조건을 탐지한다.

    External I/O 없음. matrix: dict[int, dict[int, dict]] 인덱스 기반.
    피로도 임계·체력 부담 기준은 party_type별 PartyProfile에서 동적으로 결정된다.
    """

    STRAIN_THRESHOLD_KM: float = 30.0  # 기준 그룹(혼자/친구) 체력 부담 임계
    BACKTRACK_THRESHOLD: float = 0.3   # 30% 초과 이동거리 비효율
    PURPOSE_FIT_THRESHOLD: float = 0.5
    CONSECUTIVE_REVISIT: int = 3       # 같은 카테고리 연속 ≥ 3회 (2회는 문화투어 등에서 false positive)

    def detect(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
    ) -> list[Warning]:
        """Warning 목록 반환. 없으면 빈 리스트."""
        dist_cache = build_dist_cache(pois)
        warns: list[Warning] = []
        warns.extend(self._check_dense_schedule(plan, pois, matrix, dist_cache))
        warns.extend(self._check_inefficient_route(pois, dist_cache))
        warns.extend(self._check_physical_strain(plan, pois, dist_cache))
        warns.extend(self._check_purpose_mismatch(plan, pois))
        warns.extend(self._check_area_revisit(pois))
        return warns

    def _check_dense_schedule(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
        dist_cache: dict,
    ) -> list[Warning]:
        profile = get_party_profile(plan.party_type)
        threshold_min = profile.fatigue_hours * 60
        dwell = sum(p.duration_min for p in pois)
        travel = sum(
            get_travel_min(matrix, i - 1, i, pois[i - 1], pois[i], dist_cache)
            for i in range(1, len(pois))
        )
        total_min = dwell + travel
        if total_min <= threshold_min:
            return []
        _, confidence = WARNING_TYPES["DENSE_SCHEDULE"]
        return [Warning(
            warning_type="DENSE_SCHEDULE",
            message=(
                f"총 일정 소요 시간 {total_min:.0f}분 ({total_min / 60:.1f}시간)이 "
                f"'{plan.party_type}' 그룹 피로도 한계 {profile.fatigue_hours}시간을 초과합니다."
            ),
            confidence=confidence,
        )]

    def _check_inefficient_route(
        self,
        pois: list[POI],
        dist_cache: dict,
    ) -> list[Warning]:
        if len(pois) <= 2:
            return []
        actual_km = sum(dist_cache.get((i, i + 1), 0.0) for i in range(len(pois) - 1))
        if actual_km == 0:
            return []
        nn_km = nn_heuristic_km(pois, dist_cache)
        ratio = (actual_km - nn_km) / actual_km
        if ratio <= self.BACKTRACK_THRESHOLD:
            return []
        _, confidence = WARNING_TYPES["INEFFICIENT_ROUTE"]
        return [Warning(
            warning_type="INEFFICIENT_ROUTE",
            message=(
                f"현재 방문 순서의 이동 거리({actual_km:.1f}km)가 최적 경로 대비 "
                f"{ratio:.1%} 더 깁니다. 방문 순서를 재배치해 보세요."
            ),
            confidence=confidence,
        )]

    def _check_physical_strain(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        dist_cache: dict,
    ) -> list[Warning]:
        profile = get_party_profile(plan.party_type)
        threshold_km = self.STRAIN_THRESHOLD_KM * profile.speed_factor
        total_km = sum(dist_cache.get((i, i + 1), 0.0) for i in range(len(pois) - 1))
        if total_km <= threshold_km:
            return []
        _, confidence = WARNING_TYPES["PHYSICAL_STRAIN"]
        return [Warning(
            warning_type="PHYSICAL_STRAIN",
            message=(
                f"총 이동 거리 {total_km:.1f}km가 "
                f"'{plan.party_type}' 그룹 체력 한계 {threshold_km:.0f}km를 초과합니다."
            ),
            confidence=confidence,
        )]

    def _check_purpose_mismatch(self, plan: ItineraryPlan, pois: list[POI]) -> list[Warning]:
        if not plan.travel_type:
            return []
        intent = INTENT_VECTORS.get(plan.travel_type)
        if not intent:
            return []
        total = len(pois)
        if total == 0:
            return []

        cat_count: dict[str, float] = {}
        for poi in pois:
            cat = str(poi.category) if poi.category else "other"
            if cat not in ("12", "14", "15", "38", "39"):
                cat = "other"
            cat_count[cat] = cat_count.get(cat, 0.0) + 1.0
        activity = {k: v / total for k, v in cat_count.items()}

        purpose_fit = 1.0 - _cosine_distance(intent, activity)
        if purpose_fit >= self.PURPOSE_FIT_THRESHOLD:
            return []
        _, confidence = WARNING_TYPES["PURPOSE_MISMATCH"]
        return [Warning(
            warning_type="PURPOSE_MISMATCH",
            message=(
                f"여행 테마 '{plan.travel_type}'과 실제 장소 구성의 일치도가 "
                f"{purpose_fit:.2f}로 낮습니다. 테마에 맞는 장소 선택을 권장합니다."
            ),
            confidence=confidence,
        )]

    def check_cumulative_fatigue(
        self,
        plan: ItineraryPlan,
        per_day_pois: list[list[POI]],
        matrix: dict,
    ) -> list[Warning]:
        """Multi-day 누적 피로도 분석 — 단일 detect() 호출로는 포착할 수 없는 cross-day 패턴."""
        if len(per_day_pois) < 2:
            return []

        profile = get_party_profile(plan.party_type)
        daily_limit = float(profile.fatigue_hours * 60)

        intensities: list[float] = []
        for day_pois in per_day_pois:
            if not day_pois:
                intensities.append(0.0)
                continue
            dist_cache = build_dist_cache(day_pois)
            dwell = sum(p.duration_min for p in day_pois)
            travel = sum(
                get_travel_min(matrix, i - 1, i, day_pois[i - 1], day_pois[i], dist_cache)
                for i in range(1, len(day_pois))
            )
            intensities.append((dwell + travel) / daily_limit)

        # 3일 이상 연속 고강도(>75%) → 학대 일정
        HIGH = 0.75
        ABUSE_RUN = 3
        run = max_run = 0
        for v in intensities:
            run = run + 1 if v > HIGH else 0
            max_run = max(max_run, run)

        if max_run >= ABUSE_RUN:
            return [Warning(
                warning_type="CUMULATIVE_FATIGUE",
                message=(
                    f"{max_run}일 연속으로 일일 피로도 한계의 {int(HIGH*100)}% 이상인 일정이 감지되었습니다. "
                    f"'{plan.party_type}' 그룹에게 심각한 누적 피로가 예상됩니다. "
                    "중간에 여유 있는 반나절 일정을 넣어보세요."
                ),
                confidence="Medium",
            )]

        # 전날 매우 강도 높음(>85%) + 다음날도 상당(>60%) → carry-over 경고
        VERY_HIGH = 0.85
        MODERATE = 0.60
        for i in range(1, len(intensities)):
            if intensities[i - 1] > VERY_HIGH and intensities[i] > MODERATE:
                return [Warning(
                    warning_type="CUMULATIVE_FATIGUE",
                    message=(
                        f"{i}일차 일정이 피로도 한계의 {intensities[i-1]:.0%}로 매우 고강도였고, "
                        f"{i+1}일차도 {intensities[i]:.0%} 강도로 계획되어 있습니다. "
                        "전날 피로가 이월되어 컨디션이 저하될 수 있습니다."
                    ),
                    confidence="Medium",
                )]

        return []

    def _check_area_revisit(self, pois: list[POI]) -> list[Warning]:
        if len(pois) < self.CONSECUTIVE_REVISIT:
            return []
        max_run = 1
        cur_run = 1
        for i in range(1, len(pois)):
            cat_cur = pois[i].category
            cat_prev = pois[i - 1].category
            # 빈 카테고리("" 또는 미분류)는 비교 대상에서 제외
            if cat_cur and cat_cur == cat_prev:
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 1
        if max_run < self.CONSECUTIVE_REVISIT:
            return []
        _, confidence = WARNING_TYPES["AREA_REVISIT"]
        return [Warning(
            warning_type="AREA_REVISIT",
            message=(
                f"동일 카테고리 장소가 {max_run}회 연속 배치되어 있습니다. "
                "다양한 유형의 장소를 번갈아 방문하면 여행이 더 풍성해집니다."
            ),
            confidence=confidence,
        )]
