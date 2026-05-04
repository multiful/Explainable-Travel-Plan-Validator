"""ValidatorPipeline — 전체 QA 파이프라인 오케스트레이터.

흐름:
  1. per-day HardFail 탐지
  2. Warning 탐지 (전체 POI 합산)
  3. ScoreCalculator → base_score
  4. ClusterDispersion 패널티
  5. TravelRatio 패널티
  6. ThemeAlignment 패널티 (선택적 — UserPreferences 제공 시)
  7. BonusEngine 가산점
  8. generate_rewards
  9. ValidationResult 조립

최종 점수:
  adjusted = base_score - cluster_penalty - travel_ratio_penalty - theme_penalty + bonus
  adjusted = clamp(adjusted, 0, 100)
  if hard_fails: adjusted = min(adjusted, 59)
"""
from __future__ import annotations

from pathlib import Path

from src.data.models import (
    ItineraryPlan,
    POI,
    Scores,
    ValidationResult,
    VRPTWDay,
    VRPTWPlace,
)
from src.data.theme_taxonomy import UserPreferences
from src.scoring.bonus_engine import BonusEngine
from src.scoring.cluster_dispersion import evaluate_cluster_dispersion
from src.scoring.reward_engine import generate_rewards
from src.scoring.theme_alignment import POIWithCategory, ThemeAlignmentJudge
from src.scoring.travel_ratio import evaluate_travel_ratio
from src.explain.repair import RepairEngine
from src.validation.hard_fail import HardFailDetector
from src.validation.scoring import ScoreCalculator
from src.validation.warning import WarningDetector

_DEFAULT_WELLNESS_PATH = Path("data/wellness_places.json")
_DEFAULT_BARRIER_FREE_PATH = Path("data/barrier_free_places.json")


def _to_vrptw_day(pois: list[POI]) -> VRPTWDay:
    """POI 리스트 → VRPTWDay 변환."""
    places = [
        VRPTWPlace(
            name=poi.name,
            lat=poi.lat,
            lng=poi.lng,
            open=poi.open_start,
            close=poi.open_end,
            stay_duration=poi.duration_min,
            is_depot=False,
        )
        for poi in pois
    ]
    return VRPTWDay(places=places)


def _to_poi_with_category(pois: list[POI], order_offset: int = 0) -> list[POIWithCategory]:
    return [
        POIWithCategory(
            name=poi.name,
            category_name=poi.category or "",
            visit_order=order_offset + idx + 1,
            stay_minutes=poi.duration_min,
        )
        for idx, poi in enumerate(pois)
    ]


class ValidatorPipeline:
    """전체 검증 파이프라인. External I/O 없음 (데이터셋·행렬은 주입)."""

    def __init__(
        self,
        bonus_engine: BonusEngine | None = None,
        theme_judge: ThemeAlignmentJudge | None = None,
    ) -> None:
        self._hard_fail = HardFailDetector()
        self._warning = WarningDetector()
        self._scorer = ScoreCalculator()
        self._repair = RepairEngine()
        self._bonus = bonus_engine or BonusEngine.from_dataset(
            _DEFAULT_WELLNESS_PATH, _DEFAULT_BARRIER_FREE_PATH
        )
        self._theme_judge = theme_judge or ThemeAlignmentJudge()

    def run(
        self,
        plan: ItineraryPlan,
        per_day_pois: list[list[POI]],
        matrix: dict,
        sigungu_codes_per_day: list[list[str]] | None = None,
        user_prefs: UserPreferences | None = None,
    ) -> ValidationResult:
        """파이프라인 실행 → ValidationResult 반환.

        Args:
            plan: 여행 계획 (party_type, travel_type, date 포함)
            per_day_pois: 일자별 POI 리스트
            matrix: 이동 시간 행렬 (인덱스 기반, 없으면 빈 dict)
            sigungu_codes_per_day: 일자별 시군구 코드 (ClusterDispersion M1/M3용)
            user_prefs: LLM 테마 판정용 UserPreferences (None이면 스킵)
        """
        all_pois: list[POI] = [poi for day in per_day_pois for poi in day]

        # ── 1. HardFail 탐지 (per-day) ─────────────────────────────────
        hard_fails = []
        prev_last_accom: POI | None = None
        for day_idx, day_pois in enumerate(per_day_pois):
            if not day_pois:
                continue
            fails = self._hard_fail.detect(
                plan=plan,
                pois=day_pois,
                matrix=matrix,
                origin_poi=prev_last_accom,
            )
            hard_fails.extend(fails)
            # 마지막 숙소 POI 추출 (다음 날 origin으로)
            accom_pois = [p for p in day_pois if p.category == "32"]
            prev_last_accom = accom_pois[-1] if accom_pois else None

        # ── 2. Warning 탐지 (per-day) ────────────────────────────────────
        # PURPOSE_MISMATCH는 여행 전체 테마 판단 → all_pois로 1회만 호출
        # 나머지(DENSE_SCHEDULE, PHYSICAL_STRAIN, INEFFICIENT_ROUTE, AREA_REVISIT)는
        # 일자별로 개별 호출해 threshold를 하루 기준에 맞게 적용
        warnings: list = []
        for day_pois in per_day_pois:
            if not day_pois:
                continue
            day_warns = self._warning.detect(plan=plan, pois=day_pois, matrix=matrix)
            warnings.extend(w for w in day_warns if w.warning_type != "PURPOSE_MISMATCH")

        warnings.extend(self._warning._check_purpose_mismatch(plan, all_pois))

        # CUMULATIVE_FATIGUE — cross-day 분석 (2일 이상 일정에서만 의미 있음)
        warnings.extend(
            self._warning.check_cumulative_fatigue(plan, per_day_pois, matrix)
        )

        # ── 3. ScoreCalculator → base_score ────────────────────────────
        if all_pois:
            scores, base_score = self._scorer.compute(
                plan=plan, pois=all_pois, matrix=matrix, hard_fails=hard_fails,
            )
        else:
            scores = Scores(
                efficiency=0.0, feasibility=0.0,
                purpose_fit=0.0, flow=0.0, area_intensity=0.0,
            )
            base_score = 0

        # ── 4. ClusterDispersion 패널티 ─────────────────────────────────
        cluster_penalty = 0
        if per_day_pois:
            vrptw_days = [_to_vrptw_day(day) for day in per_day_pois if day]
            if vrptw_days:
                cd_report = evaluate_cluster_dispersion(
                    vrptw_days, sigungu_codes_per_day
                )
                cluster_penalty = cd_report.total_penalty

        # ── 5. TravelRatio 패널티 ───────────────────────────────────────
        travel_ratio_penalty = 0
        overall_travel_ratio = 0.0
        if per_day_pois:
            vrptw_days_for_ratio = [_to_vrptw_day(day) for day in per_day_pois if day]
            if vrptw_days_for_ratio:
                tr_report = evaluate_travel_ratio(vrptw_days_for_ratio)
                travel_ratio_penalty = tr_report.total_penalty
                overall_travel_ratio = tr_report.overall_ratio

        # ── 6. ThemeAlignment 패널티 (선택) ────────────────────────────
        theme_penalty = 0
        if user_prefs is not None and self._theme_judge.is_available():
            poi_with_cat = _to_poi_with_category(all_pois)
            ta_report = self._theme_judge.evaluate(user_prefs, poi_with_cat)
            theme_penalty = ta_report.penalty

        # ── 7. BonusEngine 가산점 ───────────────────────────────────────
        bonus_result = self._bonus.compute(pois=all_pois, party_type=plan.party_type)
        total_bonus = bonus_result.total_bonus

        # ── 8. 최종 점수 조립 ───────────────────────────────────────────
        penalty_total = cluster_penalty + travel_ratio_penalty + theme_penalty
        adjusted = base_score - penalty_total + total_bonus
        adjusted = max(0, min(100, adjusted))
        if hard_fails:
            adjusted = min(adjusted, 59)

        # ── 9. Rewards ──────────────────────────────────────────────────
        rewards = generate_rewards(
            scores=scores,
            n_hard_fails=len(hard_fails),
            n_warnings=len(warnings),
            overall_travel_ratio=overall_travel_ratio,
            cluster_penalty=cluster_penalty,
        )

        penalty_breakdown: dict[str, int] = {}
        if cluster_penalty:
            penalty_breakdown["cluster_dispersion"] = cluster_penalty
        if travel_ratio_penalty:
            penalty_breakdown["travel_ratio"] = travel_ratio_penalty
        if theme_penalty:
            penalty_breakdown["theme_alignment"] = theme_penalty

        bonus_breakdown: dict[str, int] = {}
        if bonus_result.wellness_bonus:
            bonus_breakdown["wellness"] = bonus_result.wellness_bonus
        if bonus_result.accessibility_bonus:
            bonus_breakdown["accessibility"] = bonus_result.accessibility_bonus

        # ── 10. Repair Engine (Hard Fail 발생 시만 실행) ─────────────────
        repair_data: dict = {}
        if hard_fails:
            repair_result = self._repair.repair(
                plan=plan,
                per_day_pois=per_day_pois,
                matrix=matrix,
                hard_fails=hard_fails,
            )
            if not repair_result.is_empty:
                repair_data = repair_result.to_dict()

        return ValidationResult(
            plan_id=plan.plan_id,
            final_score=adjusted,
            hard_fails=hard_fails,
            warnings=warnings,
            scores=scores,
            rewards=rewards,
            penalty_breakdown=penalty_breakdown,
            bonus_breakdown=bonus_breakdown,
            repair=repair_data,
        )
