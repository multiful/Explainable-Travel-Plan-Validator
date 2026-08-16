"""ValidatorPipeline — 전체 QA 파이프라인 오케스트레이터.

흐름:
   1. per-day HardFail 탐지
   2. Warning 탐지 (전체 POI 합산)
   3. ScoreCalculator → base_score
   4. ClusterDispersion 패널티
   5. TravelRatio 패널티
   6. ThemeAlignment 패널티 (선택적 — UserPreferences 제공 시)
   7. BonusEngine 가산점
   8. 최종 점수 조립
   9. generate_rewards
  10. RepairEngine (Hard Fail 발생 시만)
  11. ExplainEngine → 4단계 자연어 설명 생성

최종 점수:
  adjusted = base_score - cluster_penalty - travel_ratio_penalty - theme_penalty + bonus
  adjusted = clamp(adjusted, 0, 100)
  if hard_fails: adjusted = min(adjusted, 59)
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from src.data.models import (
    POI,
    HardFail,
    ItineraryPlan,
    Scores,
    ValidationResult,
    VRPTWDay,
    VRPTWPlace,
    VRPTWRequest,
)
from src.data.theme_taxonomy import UserPreferences
from src.explain.explain_engine import ExplainEngine
from src.explain.repair import RepairEngine, RepairResult
from src.scoring.bonus_engine import BonusEngine, BonusResult
from src.scoring.cluster_dispersion import evaluate_cluster_dispersion
from src.scoring.reward_engine import generate_rewards
from src.scoring.theme_alignment import POIWithCategory, ThemeAlignmentJudge
from src.scoring.travel_ratio import evaluate_travel_ratio
from src.validation.hard_fail import HardFailDetector
from src.validation.scoring import ScoreCalculator
from src.validation.vrptw_engine import VRPTWEngine
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


@dataclasses.dataclass
class _ScoreBundle:
    """1·3·3b·4·5·6·7·8단계(점수 계산)만의 결과. Warning·Repair·Explain 미포함."""
    adjusted: int
    base_score: int
    scores: Scores
    hard_fails: list[HardFail]
    capping_fails: list[HardFail]
    vrptw_optimal_route: list | None
    vrptw_efficiency_gap: float | None
    cluster_penalty: int
    travel_ratio_penalty: int
    theme_penalty: int
    vrptw_penalty: int
    overall_travel_ratio: float
    bonus_result: BonusResult


class ValidatorPipeline:
    """전체 검증 파이프라인. External I/O = Claude API (ExplainEngine·ThemeAlignmentJudge)."""

    def __init__(
        self,
        bonus_engine: BonusEngine | None = None,
        theme_judge: ThemeAlignmentJudge | None = None,
        explain_engine: ExplainEngine | None = None,
    ) -> None:
        self._hard_fail = HardFailDetector()
        self._warning = WarningDetector()
        self._scorer = ScoreCalculator()
        self._repair = RepairEngine()
        self._bonus = bonus_engine or BonusEngine.from_dataset(
            _DEFAULT_WELLNESS_PATH, _DEFAULT_BARRIER_FREE_PATH
        )
        self._theme_judge = theme_judge or ThemeAlignmentJudge()
        self._explain = explain_engine or ExplainEngine()

    def run(
        self,
        plan: ItineraryPlan,
        per_day_pois: list[list[POI]],
        matrix: dict,
        sigungu_codes_per_day: list[list[str]] | None = None,
        user_prefs: UserPreferences | None = None,
        pet_friendly_enabled: bool = False,
    ) -> ValidationResult:
        """파이프라인 실행 → ValidationResult 반환.

        Args:
            plan: 여행 계획 (party_type, travel_type, date 포함)
            per_day_pois: 일자별 POI 리스트
            matrix: 이동 시간 행렬 (인덱스 기반, 없으면 빈 dict)
            sigungu_codes_per_day: 일자별 시군구 코드 (ClusterDispersion M1/M3용)
            user_prefs: LLM 테마 판정용 UserPreferences (None이면 스킵)
            pet_friendly_enabled: 사용자가 "반려동물 동반" 카테고리를 켰는지 여부
        """
        all_pois: list[POI] = [poi for day in per_day_pois for poi in day]
        bundle = self._score(
            plan, per_day_pois, matrix,
            sigungu_codes_per_day, user_prefs, pet_friendly_enabled,
        )

        # ── 2. Warning 탐지 (per-day) ────────────────────────────────────
        # PURPOSE_MISMATCH는 여행 전체 테마 판단 → all_pois로 1회만 호출
        # 나머지(DENSE_SCHEDULE, PHYSICAL_STRAIN, INEFFICIENT_ROUTE, AREA_REVISIT)는
        # 일자별로 개별 호출해 threshold를 하루 기준에 맞게 적용
        warnings: list = []
        for day_idx, day_pois in enumerate(per_day_pois):
            if not day_pois:
                continue
            day_warns = self._warning.detect(plan=plan, pois=day_pois, matrix=matrix, day_index=day_idx)
            warnings.extend(w for w in day_warns if w.warning_type != "PURPOSE_MISMATCH")

        warnings.extend(self._warning._check_purpose_mismatch(plan, all_pois))

        # CUMULATIVE_FATIGUE — cross-day 분석 (2일 이상 일정에서만 의미 있음)
        warnings.extend(
            self._warning.check_cumulative_fatigue(plan, per_day_pois, matrix)
        )

        rewards = generate_rewards(
            scores=bundle.scores,
            n_hard_fails=len(bundle.hard_fails),
            n_warnings=len(warnings),
            overall_travel_ratio=bundle.overall_travel_ratio,
            cluster_penalty=bundle.cluster_penalty,
        )

        penalty_breakdown: dict[str, int] = {}
        if bundle.cluster_penalty:
            penalty_breakdown["cluster_dispersion"] = bundle.cluster_penalty
        if bundle.travel_ratio_penalty:
            penalty_breakdown["travel_ratio"] = bundle.travel_ratio_penalty
        if bundle.theme_penalty:
            penalty_breakdown["theme_alignment"] = bundle.theme_penalty
        if bundle.vrptw_penalty:
            penalty_breakdown["vrptw_efficiency"] = bundle.vrptw_penalty

        bonus_breakdown: dict[str, int] = {}
        if bundle.bonus_result.wellness_bonus:
            bonus_breakdown["wellness"] = bundle.bonus_result.wellness_bonus
        if bundle.bonus_result.accessibility_bonus:
            bonus_breakdown["accessibility"] = bundle.bonus_result.accessibility_bonus
        if bundle.bonus_result.pet_friendly_bonus:
            bonus_breakdown["pet_friendly"] = bundle.bonus_result.pet_friendly_bonus

        # ── 10. Repair Engine (Hard Fail 발생 시만 실행) ─────────────────
        repair_data: dict = {}
        if bundle.hard_fails:
            repair_result = self._repair.repair(
                plan=plan,
                per_day_pois=per_day_pois,
                matrix=matrix,
                hard_fails=bundle.hard_fails,
            )
            if not repair_result.is_empty:
                repair_result = self._estimate_repair_gains(
                    plan, per_day_pois, matrix, pet_friendly_enabled, repair_result,
                )
                repair_data = repair_result.to_dict()

        # ── 11. ExplainEngine → 4단계 자연어 설명 생성 ─────────────────
        explanations = self._explain.generate(
            hard_fails=bundle.hard_fails,
            warnings=warnings,
            penalty_breakdown=penalty_breakdown,
            bonus_breakdown=bonus_breakdown,
            scores=bundle.scores,
            plan=plan,
            final_score=bundle.adjusted,
        )

        # ── 12. Hard Fail POI 대안 (지식그래프 도보권 대안, 미설정/미매칭 시 빈 dict) ──
        alternatives = self._explain.build_alternatives(bundle.hard_fails) if bundle.hard_fails else {}

        return ValidationResult(
            plan_id=plan.plan_id,
            final_score=bundle.adjusted,
            base_score=bundle.base_score,
            hard_fails=bundle.hard_fails,
            warnings=warnings,
            scores=bundle.scores,
            explanations=explanations,
            rewards=rewards,
            alternatives=alternatives,
            penalty_breakdown=penalty_breakdown,
            bonus_breakdown=bonus_breakdown,
            wellness_matched=bundle.bonus_result.wellness_matched,
            repair=repair_data,
            vrptw_optimal_route=bundle.vrptw_optimal_route,
            vrptw_efficiency_gap=bundle.vrptw_efficiency_gap,
        )

    def _score(
        self,
        plan: ItineraryPlan,
        per_day_pois: list[list[POI]],
        matrix: dict,
        sigungu_codes_per_day: list[list[str]] | None,
        user_prefs: UserPreferences | None,
        pet_friendly_enabled: bool,
    ) -> _ScoreBundle:
        """1·3·3b·4·5·6·7·8단계만 실행해 점수를 계산한다 (Warning·Repair·Explain 제외).

        RepairEngine 제안의 예상 점수 변화를 시뮬레이션하는 `_estimate_repair_gains`에서도 재사용된다.
        """
        all_pois: list[POI] = [poi for day in per_day_pois for poi in day]

        # ── 1. HardFail 탐지 (per-day) ─────────────────────────────────
        hard_fails: list[HardFail] = []
        prev_last_accom: POI | None = None
        for day_idx, day_pois in enumerate(per_day_pois):
            if not day_pois:
                continue
            fails = self._hard_fail.detect(
                plan=plan,
                pois=day_pois,
                matrix=matrix,
                origin_poi=prev_last_accom,
                day_index=day_idx,
            )
            hard_fails.extend(fails)
            accom_pois = [p for p in day_pois if p.category == "32"]
            prev_last_accom = accom_pois[-1] if accom_pois else None

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

        # ── 3b. VRPTWEngine 실행 — 최적 경로 + Efficiency Gap ────────────
        vrptw_days = [_to_vrptw_day(day) for day in per_day_pois if day]
        vrptw_optimal_route = None
        vrptw_efficiency_gap = None
        vrptw_penalty = 0

        if vrptw_days:
            _vrptw_result = VRPTWEngine().validate(VRPTWRequest(days=vrptw_days))
            vrptw_optimal_route = _vrptw_result.optimal_route
            vrptw_efficiency_gap = _vrptw_result.efficiency_gap
            if vrptw_efficiency_gap is not None:
                if vrptw_efficiency_gap > 0.60:
                    vrptw_penalty = 15
                elif vrptw_efficiency_gap > 0.40:
                    vrptw_penalty = 10
                elif vrptw_efficiency_gap > 0.20:
                    vrptw_penalty = 5

        # ── 4. ClusterDispersion 패널티 ─────────────────────────────────
        cluster_penalty = 0
        if vrptw_days:
            cd_report = evaluate_cluster_dispersion(vrptw_days, sigungu_codes_per_day)
            cluster_penalty = cd_report.total_penalty

        # ── 5. TravelRatio 패널티 ───────────────────────────────────────
        travel_ratio_penalty = 0
        overall_travel_ratio = 0.0
        if vrptw_days:
            tr_report = evaluate_travel_ratio(vrptw_days)
            travel_ratio_penalty = tr_report.total_penalty
            overall_travel_ratio = tr_report.overall_ratio

        # ── 6. ThemeAlignment 패널티 (선택) ────────────────────────────
        theme_penalty = 0
        if user_prefs is not None and self._theme_judge.is_available():
            poi_with_cat = _to_poi_with_category(all_pois)
            ta_report = self._theme_judge.evaluate(user_prefs, poi_with_cat)
            theme_penalty = ta_report.penalty

        # ── 7. BonusEngine 가산점 ───────────────────────────────────────
        bonus_result = self._bonus.compute(
            pois=all_pois, party_type=plan.party_type,
            pet_friendly_enabled=pet_friendly_enabled,
        )

        # ── 8. 최종 점수 조립 ───────────────────────────────────────────
        penalty_total = cluster_penalty + travel_ratio_penalty + theme_penalty + vrptw_penalty
        adjusted = base_score - penalty_total + bonus_result.total_bonus
        adjusted = max(0, min(100, adjusted))
        # 추정 영업시간 충돌(estimated=True)은 '확인 필요' 수준 → 점수 캡에서 제외.
        capping_fails = [hf for hf in hard_fails if not getattr(hf, "estimated", False)]
        if capping_fails:
            adjusted = min(adjusted, 59)

        return _ScoreBundle(
            adjusted=adjusted,
            base_score=base_score,
            scores=scores,
            hard_fails=hard_fails,
            capping_fails=capping_fails,
            vrptw_optimal_route=vrptw_optimal_route,
            vrptw_efficiency_gap=vrptw_efficiency_gap,
            cluster_penalty=cluster_penalty,
            travel_ratio_penalty=travel_ratio_penalty,
            theme_penalty=theme_penalty,
            vrptw_penalty=vrptw_penalty,
            overall_travel_ratio=overall_travel_ratio,
            bonus_result=bonus_result,
        )

    def _estimate_repair_gains(
        self,
        plan: ItineraryPlan,
        per_day_pois: list[list[POI]],
        matrix: dict,
        pet_friendly_enabled: bool,
        repair_result: RepairResult,
    ) -> RepairResult:
        """교정 제안별 예상 점수 변화(`estimated_score_gain`)와 문제 해소 여부(`resolves_hard_fail`)를 채운다.

        ponytail: baseline·시뮬레이션 양쪽 모두 sigungu_codes_per_day=None, user_prefs=None로
        고정해 M1/M3 시군구 백트래킹과 LLM 테마 판정(ThemeAlignment)을 생략한다 — 두 항목 모두
        비교 대상인 base_score/penalty 구조와 무관하게 baseline·시뮬레이션에 동일하게 적용되므로
        델타 계산의 공정성은 유지되면서 추가 I/O·LLM 호출 없이 저지연으로 끝난다.
        정밀도가 필요해지면 실제 sigungu_codes_per_day·user_prefs를 그대로 전달하도록 확장한다.
        """
        baseline = self._score(
            plan, per_day_pois, matrix,
            sigungu_codes_per_day=None, user_prefs=None,
            pet_friendly_enabled=pet_friendly_enabled,
        )

        def simulate(day_idx: int, modified_day: list[POI]) -> tuple[int, bool]:
            sim_days = list(per_day_pois)
            sim_days[day_idx] = modified_day
            bundle = self._score(
                plan, sim_days, matrix,
                sigungu_codes_per_day=None, user_prefs=None,
                pet_friendly_enabled=pet_friendly_enabled,
            )
            resolved = not any(hf.day_index == day_idx for hf in bundle.capping_fails)
            return bundle.adjusted - baseline.adjusted, resolved

        reorders = []
        for ro in repair_result.reorders:
            by_name = {p.name: p for p in per_day_pois[ro.day_index]}
            modified = [by_name[n] for n in ro.suggested_order if n in by_name]
            gain, resolved = simulate(ro.day_index, modified)
            reorders.append(dataclasses.replace(
                ro, estimated_score_gain=gain, resolves_hard_fail=resolved,
            ))

        time_tunes = []
        for tt in repair_result.time_tunes:
            modified = [
                p.model_copy(update={"duration_min": tt.adjustments[p.name]})
                if p.name in tt.adjustments else p
                for p in per_day_pois[tt.day_index]
            ]
            gain, resolved = simulate(tt.day_index, modified)
            time_tunes.append(dataclasses.replace(
                tt, estimated_score_gain=gain, resolves_hard_fail=resolved,
            ))

        deletions = []
        for dl in repair_result.deletions:
            modified = [p for p in per_day_pois[dl.day_index] if p.name != dl.candidate_name]
            gain, resolved = simulate(dl.day_index, modified)
            deletions.append(dataclasses.replace(
                dl, estimated_score_gain=gain, resolves_hard_fail=resolved,
            ))

        return RepairResult(reorders=reorders, time_tunes=time_tunes, deletions=deletions)
