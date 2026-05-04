"""5개 지표 기반 최종 점수 계산기."""
from __future__ import annotations

from src.data.models import HardFail, ItineraryPlan, POI, Scores
from src.data.party_config import get_party_profile
from src.utils.geo import build_dist_cache, get_travel_min, nn_heuristic_km
from src.validation.warning import INTENT_VECTORS, _cosine_distance

WEIGHTS = {
    "efficiency":     0.30,
    "feasibility":    0.25,
    "purpose_fit":    0.20,
    "flow":           0.15,
    "area_intensity": 0.10,
}

HARD_FAIL_SCORE_CAP: int = 59


class ScoreCalculator:
    """5개 지표 → Final Score (0~100) 계산기. External I/O 없음."""

    def compute(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
        hard_fails: list[HardFail],
    ) -> tuple[Scores, int]:
        """5개 지표 계산 + Final Score (0~100) 반환.

        hard_fails 있으면 Final Score ≤ 59.
        반환: (Scores, final_score)
        """
        dist_cache = build_dist_cache(pois)

        efficiency     = self._calc_efficiency(pois, dist_cache)
        feasibility    = self._calc_feasibility(plan, pois, matrix, hard_fails, dist_cache)
        purpose_fit    = self._calc_purpose_fit(plan, pois)
        flow           = self._calc_flow(pois, dist_cache)
        area_intensity = self._calc_area_intensity(pois)

        scores = Scores(
            efficiency=round(efficiency, 4),
            feasibility=round(feasibility, 4),
            purpose_fit=round(purpose_fit, 4),
            flow=round(flow, 4),
            area_intensity=round(area_intensity, 4),
        )

        raw = sum(getattr(scores, k) * w for k, w in WEIGHTS.items())
        final_score = round(raw * 100)
        if hard_fails:
            final_score = min(final_score, HARD_FAIL_SCORE_CAP)

        return scores, max(0, min(100, final_score))

    @staticmethod
    def _cosine_distance(v1: dict, v2: dict) -> float:
        """warning 모듈의 공유 구현에 위임."""
        return _cosine_distance(v1, v2)

    def _calc_efficiency(
        self,
        pois: list[POI],
        dist_cache: dict | None = None,
    ) -> float:
        """Efficiency = nn_heuristic_km / actual_total_km, clamped to [0, 1]."""
        if len(pois) <= 1:
            return 1.0
        if not dist_cache:
            dist_cache = build_dist_cache(pois)
        actual_km = sum(dist_cache.get((i, i + 1), 0.0) for i in range(len(pois) - 1))
        if actual_km == 0:
            return 1.0
        nn_km = nn_heuristic_km(pois, dist_cache)
        return min(1.0, nn_km / actual_km)

    def _calc_feasibility(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
        hard_fails: list[HardFail],
        dist_cache: dict | None = None,
    ) -> float:
        """Feasibility = hard×0.5 + temporal×0.3 + human×0.2.

        temporal 임계값은 party_type별 fatigue_hours 에서 결정된다.
        """
        if not dist_cache:
            dist_cache = build_dist_cache(pois)
        hard = 0.0 if hard_fails else 1.0

        profile = get_party_profile(plan.party_type)
        num_days = len(plan.days)
        threshold = float(profile.fatigue_hours * 60) * num_days

        total_dwell = sum(p.duration_min for p in pois)
        total_travel_min = sum(
            get_travel_min(matrix, i - 1, i, pois[i - 1], pois[i], dist_cache)
            for i in range(1, len(pois))
        )
        total_min = total_dwell + total_travel_min
        excess_ratio = max(0.0, (total_min - threshold) / threshold)
        temporal = max(0.0, 1.0 - excess_ratio)

        total_km = sum(dist_cache.get((i, i + 1), 0.0) for i in range(len(pois) - 1))
        human = 1.0 - min(1.0, total_km / 50.0)

        return hard * 0.5 + temporal * 0.3 + human * 0.2

    def _calc_purpose_fit(self, plan: ItineraryPlan, pois: list[POI]) -> float:
        """1 - cosine_distance(intent_vector, activity_vector)."""
        if not plan.travel_type:
            return 0.5
        intent = INTENT_VECTORS.get(plan.travel_type)
        if not intent:
            return 0.5
        total = len(pois)
        if total == 0:
            return 0.5
        cat_count: dict[str, float] = {}
        for poi in pois:
            cat = str(poi.category) if poi.category else "other"
            if cat not in ("12", "14", "15", "38", "39"):
                cat = "other"
            cat_count[cat] = cat_count.get(cat, 0.0) + 1.0
        activity = {k: v / total for k, v in cat_count.items()}
        return max(0.0, min(1.0, 1.0 - _cosine_distance(intent, activity)))

    def _calc_flow(
        self,
        pois: list[POI],
        dist_cache: dict | None = None,
    ) -> float:
        """1 - (backtracking×0.65 + revisit_area×0.35).

        switch_ratio 제거: 카테고리 다양성은 패널티가 아니라 긍정 신호이므로
        backtracking(동선 백트래킹)과 revisit_area(이미 방문한 카테고리 재방문)만 반영.
        """
        n = len(pois)
        if n <= 1:
            return 1.0
        if not dist_cache:
            dist_cache = build_dist_cache(pois)

        actual_km = sum(dist_cache.get((i, i + 1), 0.0) for i in range(n - 1))
        nn_km = nn_heuristic_km(pois, dist_cache)
        backtrack_ratio = (
            max(0.0, (actual_km - nn_km) / actual_km) if actual_km > 0 else 0.0
        )

        seen: dict[str, bool] = {}
        prev_cat: str | None = None
        revisit_count = 0
        for poi in pois:
            cat = poi.category or ""
            if cat and cat in seen and cat != prev_cat:
                revisit_count += 1
            if cat:
                seen[cat] = True
            prev_cat = cat
        revisit_ratio = revisit_count / max(1, n - 1)

        flow = 1.0 - (backtrack_ratio * 0.65 + revisit_ratio * 0.35)
        return max(0.0, min(1.0, flow))

    def _calc_area_intensity(self, pois: list[POI]) -> float:
        """1 - dominant_category_ratio. 분산될수록 1에 가까움."""
        cats = [p.category for p in pois if p.category]
        if not cats:
            return 1.0
        cat_counts: dict[str, int] = {}
        for c in cats:
            cat_counts[c] = cat_counts.get(c, 0) + 1
        dominant_ratio = max(cat_counts.values()) / len(cats)
        return 1.0 - dominant_ratio
