"""ExplainEngine — Claude API 기반 4단계 자연어 설명 생성기.

검증 엔진이 탐지한 Hard Fail / Warning / 패널티 항목 전체를
단일 LLM 호출로 분석해 [Fact → Rule → Risk → Suggestion] 구조의
ExplanationItem 리스트를 반환한다.

설계 원칙:
  - 단일 API 호출: 모든 이슈를 하나의 요청으로 처리 (비용 최적화)
  - Prompt Caching: system prompt에 cache_control ephemeral 적용
  - Graceful fallback: API 키 없거나 호출 실패 시 규칙 기반 설명으로 대체
  - 이슈 없을 때 LLM 미호출: 불필요한 API 호출 방지
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from typing import Any

from src.data.models import (
    ExplanationItem,
    HardFail,
    ItineraryPlan,
    Scores,
    Warning,
)

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ── LLM 설정 ──────────────────────────────────────────────────────────────
DEFAULT_MODEL: str = "claude-sonnet-4-6"
DEFAULT_TIMEOUT_SEC: float = 20.0
DEFAULT_MAX_TOKENS: int = 2500

# ── 메모리 캐시 (모듈 단위, 콘텐츠 해시 키) ──────────────────────────────

class _LRUCache:
    """최대 크기 제한 LRU 캐시 — collections.OrderedDict 기반 (외부 의존성 없음)."""

    def __init__(self, maxsize: int = 500) -> None:
        self._store: OrderedDict[str, list] = OrderedDict()
        self._maxsize = maxsize

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def __getitem__(self, key: str) -> list:
        self._store.move_to_end(key)
        return self._store[key]

    def __setitem__(self, key: str, value: list) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


_CACHE = _LRUCache(maxsize=500)

# ── 규칙 기반 폴백용 텍스트 사전 ─────────────────────────────────────────
_HARD_FAIL_RULES = {
    "OPERATING_HOURS_CONFLICT": (
        "Hard Fail: 운영시간 외 방문은 물리적으로 불가능합니다. "
        "이 항목이 존재하면 최종 점수는 59점 이하로 제한됩니다."
    ),
    "TRAVEL_TIME_IMPOSSIBLE": (
        "Hard Fail: 앞 장소 출발부터 다음 장소 도착까지 가용한 시간이 이동에 필요한 시간보다 짧습니다."
    ),
    "SCHEDULE_INFEASIBLE": (
        "Hard Fail: 하루 총 소요시간(이동+체류)이 24시간을 초과해 물리적으로 실행 불가능한 일정입니다."
    ),
}

_HARD_FAIL_SUGGESTIONS = {
    "OPERATING_HOURS_CONFLICT": (
        "해당 장소를 운영시간 내 방문 가능하도록 방문 순서를 앞당기거나, "
        "앞 장소들의 체류 시간을 줄여 이동 시간을 확보하세요."
    ),
    "TRAVEL_TIME_IMPOSSIBLE": (
        "두 장소 사이의 거리를 고려해 중간 장소를 제거하거나 방문 순서를 변경하세요. "
        "RepairEngine의 재배치 제안을 참고하세요."
    ),
    "SCHEDULE_INFEASIBLE": (
        "1~2개 장소를 다른 날로 분산하거나 각 장소의 체류 시간을 줄여 "
        "하루 일정을 12시간 이내로 압축하세요."
    ),
}

_WARNING_RULES = {
    "DENSE_SCHEDULE": "Warning: 파티 유형별 하루 피로도 한계(혼자·친구·연인 12h, 가족 10h, 아기·어르신동반 8h)를 초과했습니다.",
    "INEFFICIENT_ROUTE": "Warning: 실제 이동 거리가 NN 휴리스틱 최적 경로 대비 30% 이상 깁니다.",
    "PHYSICAL_STRAIN": "Warning: 하루 총 이동 거리가 파티 유형별 체력 한계를 초과했습니다.",
    "PURPOSE_MISMATCH": "Warning: 선택한 travel_type과 실제 장소 구성의 코사인 유사도가 0.5 미만입니다.",
    "AREA_REVISIT": "Warning: 동일 카테고리 장소가 3회 이상 연속 배치되어 여행 다양성이 낮습니다.",
    "CUMULATIVE_FATIGUE": "Warning: 3일 연속 고강도 일정 또는 전날 85%+ 강도 → 다음날 60%+ 강도가 감지되었습니다.",
}

_WARNING_SUGGESTIONS = {
    "DENSE_SCHEDULE": "하루 일정에서 1~2개 장소를 다른 날로 분산하거나, 체류 시간이 긴 장소의 방문 시간을 줄이세요.",
    "INEFFICIENT_ROUTE": "방문 순서를 지리적으로 인접한 장소끼리 묶어 재배치하면 이동 시간을 절약할 수 있습니다.",
    "PHYSICAL_STRAIN": "원거리 장소를 제외하거나 별도 일자로 분리해 일일 이동 거리를 줄이세요.",
    "PURPOSE_MISMATCH": "선택한 테마에 맞는 장소로 교체하거나, 현재 일정에 맞는 travel_type을 다시 선택하세요.",
    "AREA_REVISIT": "같은 카테고리 장소 사이에 다른 유형의 장소를 배치해 여행 구성을 다양화하세요.",
    "CUMULATIVE_FATIGUE": "연속 고강도 일정 중간에 가벼운 반나절 코스를 배치해 누적 피로를 해소하세요.",
}

_PENALTY_RULES = {
    "cluster_dispersion": (
        "Penalty: 하루 내 시군구 전환 ≥3회(−5/−10점), 최대 직선거리 ≥30km(−5/−10/−20점), "
        "비연속 지역 재진입(−5/−10점) 위반 합산 최대 −20점."
    ),
    "travel_ratio": (
        "Penalty: 총 여행 시간 대비 이동 시간 비율이 여행 기간별 임계값(당일 0.20+, 1박2일 0.12+, 2박3일 0.35+)을 초과 시 최대 −20점."
    ),
    "theme_alignment": (
        "Penalty: LLM이 판정한 테마↔장소 의미적 일치도가 0.8 미만 시 −5/−10/−20점 감점."
    ),
}

_PENALTY_SUGGESTIONS = {
    "cluster_dispersion": (
        "같은 지역(시군구) 내 장소끼리 같은 날에 묶고, 원거리 장소는 별도 일자로 분리하세요. "
        "RepairEngine의 재배치 제안을 확인하세요."
    ),
    "travel_ratio": (
        "이동 비율을 낮추려면 방문 순서를 최적화하거나 원거리 장소를 제거하세요. "
        "NN 최적 경로와 현재 경로의 차이를 비교해 보세요."
    ),
    "theme_alignment": (
        "선택한 테마(cultural/nature/shopping/food/adventure)에 맞는 장소로 구성을 조정하거나, "
        "현재 일정에 맞는 테마를 다시 지정하세요."
    ),
}


SYSTEM_PROMPT = """당신은 한국 여행 일정 QA 보고서 작성 전문가입니다.
여행 검증 시스템이 탐지한 문제 항목들에 대해 사용자가 이해하기 쉬운 4단계 설명을 생성하세요.

[4단계 설명 구조]
- fact : 측정된 수치 사실 (구체적 수치·장소명·시간 반드시 포함, 1~2문장)
- rule : 적용된 검증 규칙과 그 이유 (왜 이것이 문제인지 기준 명시, 1문장)
- risk : 위험도 — "OK" / "WARNING" / "CRITICAL" 셋 중 하나만
- suggestion : 구체적이고 실행 가능한 개선 방법 (1~2문장, "~하세요" 형태)

[출력 형식]
반드시 JSON 배열만 출력하세요. 추가 텍스트, 마크다운, 코드 블록 금지.
입력의 item_type과 item_key는 그대로 유지하세요.

[품질 기준]
- fact에 수치가 없으면 실패입니다. 입력 data에 포함된 측정값을 반드시 활용하세요.
- hard_fail → risk는 항상 "CRITICAL"
- warning → risk는 항상 "WARNING"
- penalty → risk는 패널티 크기(≤5: WARNING, >5: CRITICAL)에 따라 결정
- overall → 전체 상태 요약, passed=true면 "OK", false면 "CRITICAL"
- 한국어로 작성하세요."""


def _cache_key(
    hard_fails: list[HardFail],
    warnings: list[Warning],
    penalty_breakdown: dict[str, int],
    final_score: int,
) -> str:
    payload = {
        "hf": sorted([(h.fail_type, h.poi_name or "") for h in hard_fails]),
        "w": sorted([w.warning_type for w in warnings]),
        "p": sorted(penalty_breakdown.items()),
        "score": final_score,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _build_user_prompt(
    hard_fails: list[HardFail],
    warnings: list[Warning],
    penalty_breakdown: dict[str, int],
    bonus_breakdown: dict[str, int],
    scores: Scores | None,
    plan: ItineraryPlan,
    final_score: int,
) -> str:
    issues: list[dict] = []

    for hf in hard_fails:
        issues.append({
            "item_type": "hard_fail",
            "item_key": hf.fail_type,
            "data": {
                "장소": hf.poi_name or "미지정",
                "메시지": hf.message,
                "증거": hf.evidence,
                "신뢰도": hf.confidence,
            },
        })

    for w in warnings:
        issues.append({
            "item_type": "warning",
            "item_key": w.warning_type,
            "data": {
                "메시지": w.message,
                "신뢰도": w.confidence,
            },
        })

    for key, penalty in penalty_breakdown.items():
        issues.append({
            "item_type": "penalty",
            "item_key": key,
            "data": {
                "감점": penalty,
                "규칙_설명": _PENALTY_RULES.get(key, key),
            },
        })

    passed = final_score >= 60 and not hard_fails
    issues.append({
        "item_type": "overall",
        "item_key": "summary",
        "data": {
            "최종_점수": final_score,
            "합격_여부": "PASS" if passed else "FAIL",
            "Hard_Fail_수": len(hard_fails),
            "Warning_수": len(warnings),
            "총_감점": sum(penalty_breakdown.values()),
            "총_가산": sum(bonus_breakdown.values()),
        },
    })

    plan_info = {
        "파티": f"{plan.party_type} {plan.party_size}인",
        "여행_일수": plan.travel_days,
        "시작일": plan.date,
        "테마": plan.travel_type or "미지정",
    }

    scores_info: dict = {}
    if scores:
        scores_info = {
            "효율성(이동경로)": round(scores.efficiency, 3),
            "실현가능성": round(scores.feasibility, 3),
            "목적_적합성": round(scores.purpose_fit, 3),
            "동선_흐름": round(scores.flow, 3),
            "지역_집중도": round(scores.area_intensity, 3),
        }

    prompt_data = {
        "여행_계획": plan_info,
        "점수_세부": scores_info,
        "분석_이슈_목록": issues,
    }

    example_output = [
        {
            "item_type": "hard_fail",
            "item_key": "OPERATING_HOURS_CONFLICT",
            "fact": "경복궁 도착 예정 18:17, 운영 종료 18:00 — 17분 초과",
            "rule": "Hard Fail: 운영시간 종료 후 방문은 물리적으로 불가능합니다.",
            "risk": "CRITICAL",
            "suggestion": "경복궁 방문을 오전 첫 코스로 앞당기세요.",
        }
    ]

    return (
        "다음 여행 일정 검증 결과의 각 이슈 항목에 대해 4단계 설명을 JSON 배열로 생성하세요.\n\n"
        + json.dumps(prompt_data, ensure_ascii=False, indent=2)
        + f"\n\n출력 예시 (형식만 참고):\n{json.dumps(example_output, ensure_ascii=False, indent=2)}"
    )


def _parse_llm_response(raw: str) -> list[ExplanationItem]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "```"), len(lines))
        text = "\n".join(lines[1:end])

    data = json.loads(text)
    items: list[ExplanationItem] = []
    for obj in data:
        items.append(ExplanationItem(
            item_type=obj.get("item_type", "overall"),
            item_key=obj.get("item_key", "unknown"),
            fact=str(obj.get("fact", "")),
            rule=str(obj.get("rule", "")),
            risk=obj.get("risk", "WARNING"),
            suggestion=str(obj.get("suggestion", "")),
        ))
    return items


def _fallback(
    hard_fails: list[HardFail],
    warnings: list[Warning],
    penalty_breakdown: dict[str, int],
    final_score: int,
) -> list[ExplanationItem]:
    items: list[ExplanationItem] = []

    for hf in hard_fails:
        items.append(ExplanationItem(
            item_type="hard_fail",
            item_key=hf.fail_type,
            fact=f"[{hf.poi_name or '장소'}] {hf.message} (증거: {hf.evidence})",
            rule=_HARD_FAIL_RULES.get(hf.fail_type, hf.message),
            risk="CRITICAL",
            suggestion=_HARD_FAIL_SUGGESTIONS.get(hf.fail_type, "일정을 수정하세요."),
        ))

    for w in warnings:
        items.append(ExplanationItem(
            item_type="warning",
            item_key=w.warning_type,
            fact=w.message,
            rule=_WARNING_RULES.get(w.warning_type, w.message),
            risk="WARNING",
            suggestion=_WARNING_SUGGESTIONS.get(w.warning_type, "일정을 조정하세요."),
        ))

    for key, penalty in penalty_breakdown.items():
        items.append(ExplanationItem(
            item_type="penalty",
            item_key=key,
            fact=f"{key} 패널티 {penalty}점 감점",
            rule=_PENALTY_RULES.get(key, ""),
            risk="CRITICAL" if penalty > 5 else "WARNING",
            suggestion=_PENALTY_SUGGESTIONS.get(key, "동선을 최적화하세요."),
        ))

    passed = final_score >= 60 and not hard_fails
    items.append(ExplanationItem(
        item_type="overall",
        item_key="summary",
        fact=(
            f"종합 점수 {final_score}/100 — "
            f"Hard Fail {len(hard_fails)}건, Warning {len(warnings)}건, "
            f"패널티 {sum(penalty_breakdown.values())}점"
        ),
        rule="60점 이상이면 PASS. Hard Fail 존재 시 점수는 59점 이하로 제한됩니다.",
        risk="OK" if passed else "CRITICAL",
        suggestion=(
            "일정이 기준을 통과했습니다. 경고 항목을 개선하면 더 나은 여행이 됩니다."
            if passed else
            "Hard Fail을 먼저 해결한 후, Warning 항목을 순서대로 개선하세요."
        ),
    ))

    return items


class ExplainEngine:
    """LLM 기반 4단계 설명 생성 엔진. External I/O = Claude API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
    ) -> None:
        self._model = model
        self._timeout = timeout_sec
        self._max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = client
        if self._client is None and _ANTHROPIC_AVAILABLE and self._api_key:
            self._client = anthropic.Anthropic(api_key=self._api_key)

    def is_available(self) -> bool:
        return self._client is not None

    def generate(
        self,
        hard_fails: list[HardFail],
        warnings: list[Warning],
        penalty_breakdown: dict[str, int],
        bonus_breakdown: dict[str, int],
        scores: Scores | None,
        plan: ItineraryPlan,
        final_score: int,
    ) -> list[ExplanationItem]:
        # 이슈가 없으면 LLM 불필요 — 점수 강점을 반영한 긍정 overall 반환
        if not hard_fails and not warnings and not penalty_breakdown:
            strengths: list[str] = []
            improvement_hints: list[str] = []
            if scores:
                if scores.efficiency >= 0.8:
                    strengths.append(f"이동 효율성 {scores.efficiency:.0%}")
                if scores.feasibility >= 0.8:
                    strengths.append(f"실현 가능성 {scores.feasibility:.0%}")
                if scores.purpose_fit >= 0.8:
                    strengths.append(f"목적 적합성 {scores.purpose_fit:.0%}")
                if scores.flow >= 0.8:
                    strengths.append(f"동선 흐름 {scores.flow:.0%}")
                if scores.area_intensity >= 0.8:
                    strengths.append(f"지역 집중도 {scores.area_intensity:.0%}")
                if scores.efficiency < 0.7:
                    improvement_hints.append("이동 경로 최적화")
                if scores.flow < 0.7:
                    improvement_hints.append("장소 순서 재배치")
                if scores.area_intensity < 0.7:
                    improvement_hints.append("같은 구역끼리 묶어 지역 집중도 향상")

            bonus_total = sum(bonus_breakdown.values()) if bonus_breakdown else 0
            fact_parts = [f"종합 점수 {final_score}/100 — 모든 검증 항목 통과"]
            if strengths:
                fact_parts.append(f"강점: {'·'.join(strengths)}")
            if bonus_total > 0:
                fact_parts.append(f"보너스 +{bonus_total}점 반영")

            if improvement_hints:
                suggestion = f"{'·'.join(improvement_hints)}으로 점수를 추가로 높일 수 있습니다."
            elif final_score < 85:
                suggestion = "웰니스·무장애 장소를 추가하면 보너스 가산점으로 점수를 더 높일 수 있습니다."
            else:
                suggestion = "완성도 높은 일정입니다. 현재 구성을 유지하세요."

            return [ExplanationItem(
                item_type="overall",
                item_key="summary",
                fact=", ".join(fact_parts),
                rule="60점 이상이면 PASS. Hard Fail 없이 모든 항목을 통과했습니다.",
                risk="OK",
                suggestion=suggestion,
            )]

        # 폴백 (LLM 미사용)
        if not self.is_available():
            return _fallback(hard_fails, warnings, penalty_breakdown, final_score)

        # 캐시 조회
        key = _cache_key(hard_fails, warnings, penalty_breakdown, final_score)
        if key in _CACHE:
            return _CACHE[key]

        try:
            result = self._call_llm(
                hard_fails, warnings, penalty_breakdown, bonus_breakdown,
                scores, plan, final_score,
            )
            _CACHE[key] = result
            return result
        except Exception:
            return _fallback(hard_fails, warnings, penalty_breakdown, final_score)

    def _call_llm(
        self,
        hard_fails: list[HardFail],
        warnings: list[Warning],
        penalty_breakdown: dict[str, int],
        bonus_breakdown: dict[str, int],
        scores: Scores | None,
        plan: ItineraryPlan,
        final_score: int,
    ) -> list[ExplanationItem]:
        user_prompt = _build_user_prompt(
            hard_fails, warnings, penalty_breakdown,
            bonus_breakdown, scores, plan, final_score,
        )

        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            timeout=self._timeout,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )

        text_blocks = [b.text for b in message.content if hasattr(b, "text")]
        return _parse_llm_response("".join(text_blocks))
