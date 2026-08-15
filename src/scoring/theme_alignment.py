"""테마 일치성 LLM 판정 (모듈 ⑦) — Anthropic Claude API 기반.

요구사항: 사용자가 선택한 테마(예: 액티비티)와 일정 장소들이 의미적으로
일치하는지 AI가 판정. rule-based 코사인 대신 LLM의 의미 이해를 활용.

설계 원칙
---------
- API 키 없으면 정보성 DeepDive만 출력 (전체 검증은 진행)
- 캐시: (테마 + 정렬된 장소명) 해시 기준 메모리 캐시
- Prompt Caching: system 프롬프트는 cache_control: ephemeral 적용
- Timeout: 10초, 실패 시 정보성 DeepDive
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from src.data.models import DeepDiveItem
from src.data.theme_taxonomy import TRAVEL_STYLE_DESCRIPTIONS, UserPreferences

# Anthropic SDK는 선택적 의존성
try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


# ── 패널티 임계값 ─────────────────────────────────────────────────────
WARN_THRESHOLD: float = 0.8     # 0.6 ≤ score < 0.8 → -5
RISK_THRESHOLD: float = 0.6     # 0.4 ≤ score < 0.6 → -10
CRIT_THRESHOLD: float = 0.4     # score < 0.4 → -20

PENALTY_WARN: int = 5
PENALTY_RISK: int = 10
PENALTY_CRIT: int = 20

# ── LLM 설정 ─────────────────────────────────────────────────────────
DEFAULT_MODEL: str = "claude-haiku-4-5"
DEFAULT_TIMEOUT_SEC: float = 10.0
DEFAULT_MAX_TOKENS: int = 500


SYSTEM_PROMPT = """당신은 한국 여행 일정 평가 전문가입니다.
사용자가 선택한 여행 테마/스타일과 추천된 일정의 일치도를 0.0~1.0으로 평가하세요.

평가 기준:
- 1.0 : 모든 장소가 선택 테마에 부합
- 0.8 : 거의 모두 부합, 1개 정도 약간 어긋남
- 0.6 : 대체로 부합하나 1~2개 명확히 안 맞음
- 0.4 : 절반 정도만 부합
- 0.2 : 대부분 어긋남
- 0.0 : 전혀 다른 테마

응답은 반드시 다음 JSON 형식만 출력하세요 (다른 텍스트 금지):
{
  "score": <0.0~1.0 사이 소수>,
  "reasoning": "<한국어 한 문장 평가>",
  "mismatched_places": [<테마와 안 맞는 장소명 문자열 리스트>]
}
"""


@dataclass
class POIWithCategory:
    """LLM에게 전달할 POI 정보 (카테고리 명 포함)."""
    name: str
    category_name: str = ""    # 예: "자연관광지/산", "음식점/카페"
    visit_order: int = 0
    stay_minutes: int = 0


@dataclass(frozen=True)
class ThemeJudgment:
    """LLM 평가 결과."""
    score: float                       # 0.0 ~ 1.0
    reasoning: str
    mismatched_places: list[str] = field(default_factory=list)
    api_used: bool = True              # False = LLM 호출 없이 폴백


@dataclass(frozen=True)
class ThemeAlignmentReport:
    judgment: ThemeJudgment | None     # None = LLM 미호출
    penalty: int
    deep_dive: list[DeepDiveItem]


# ── 메모리 캐시 (모듈 단위) ──────────────────────────────────────────
_CACHE: dict[str, ThemeJudgment] = {}


def _cache_key(prefs: UserPreferences, places: list[POIWithCategory]) -> str:
    """캐시 키: 테마 + 정렬된 장소명 해시."""
    payload = {
        "place_types": sorted(prefs.place_types),
        "travel_styles": sorted(prefs.travel_styles),
        "places": sorted([(p.name, p.category_name) for p in places]),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _build_user_prompt(
    prefs: UserPreferences,
    places: list[POIWithCategory],
) -> str:
    """LLM에게 전달할 user 메시지 구성."""
    style_lines = []
    for s in prefs.travel_styles:
        desc = TRAVEL_STYLE_DESCRIPTIONS.get(s, "")
        style_lines.append(f"  - {s}: {desc}" if desc else f"  - {s}")

    place_lines = []
    for p in sorted(places, key=lambda x: x.visit_order):
        cat = f" ({p.category_name})" if p.category_name else ""
        stay = f" — {p.stay_minutes}분" if p.stay_minutes else ""
        place_lines.append(f"  {p.visit_order}. {p.name}{cat}{stay}")

    return (
        "[사용자 선택 테마]\n"
        f"- 장소 유형: {', '.join(prefs.place_types) if prefs.place_types else '(없음)'}\n"
        f"- 여행 스타일:\n" + "\n".join(style_lines) + "\n\n"
        "[일정 (방문 순서)]\n" + "\n".join(place_lines) + "\n\n"
        "위 일정의 테마 일치도를 평가하세요. JSON으로만 응답하세요."
    )


def _classify_score(score: float) -> tuple[int, str]:
    """일치도 점수 → (패널티, risk_label)."""
    if score < CRIT_THRESHOLD:
        return PENALTY_CRIT, "CRITICAL"
    if score < RISK_THRESHOLD:
        return PENALTY_RISK, "WARNING"
    if score < WARN_THRESHOLD:
        return PENALTY_WARN, "WARNING"
    return 0, "OK"


def _parse_llm_response(raw_text: str) -> ThemeJudgment:
    """Claude 응답 텍스트에서 JSON 추출."""
    # 응답이 ```json ... ``` 코드 블록으로 감싸진 경우 처리
    text = raw_text.strip()
    if text.startswith("```"):
        # 첫 줄과 마지막 ``` 제거
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(text)
    score = float(data.get("score", 0.5))
    score = max(0.0, min(1.0, score))   # clamp
    return ThemeJudgment(
        score=score,
        reasoning=str(data.get("reasoning", "")),
        mismatched_places=list(data.get("mismatched_places", [])),
        api_used=True,
    )


class ThemeAlignmentJudge:
    """LLM 기반 테마 일치성 판정기.

    사용 예:
        judge = ThemeAlignmentJudge()  # ANTHROPIC_API_KEY 자동 로드
        report = judge.evaluate(prefs, places)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,                    # 테스트에서 주입 가능
    ) -> None:
        self._model = model
        self._timeout = timeout_sec
        self._max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = client
        if self._client is None and _ANTHROPIC_AVAILABLE and self._api_key:
            self._client = anthropic.Anthropic(api_key=self._api_key)

    def is_available(self) -> bool:
        """LLM 호출 가능 여부 (SDK + 키 + 클라이언트 모두 준비된 경우 True)."""
        return self._client is not None

    def evaluate(
        self,
        prefs: UserPreferences,
        places: list[POIWithCategory],
    ) -> ThemeAlignmentReport:
        """테마 일치도 평가 + 패널티 산출."""
        # ── LLM 사용 불가 케이스: 정보성 DeepDive만 ──
        if not self.is_available():
            reason = (
                "ANTHROPIC_API_KEY 미설정" if not self._api_key
                else "anthropic SDK 미설치"
            )
            return ThemeAlignmentReport(
                judgment=None,
                penalty=0,
                deep_dive=[DeepDiveItem(
                    fact=f"테마 일치성 평가 미수행 — {reason}",
                    rule="theme_alignment_skipped",
                    risk="OK",
                    suggestion="ANTHROPIC_API_KEY 환경변수 설정 후 재실행하세요.",
                )],
            )

        # ── 캐시 조회 ──
        cache_key = _cache_key(prefs, places)
        if cache_key in _CACHE:
            judgment = _CACHE[cache_key]
        else:
            try:
                judgment = self._call_llm(prefs, places)
                _CACHE[cache_key] = judgment
            except Exception as e:
                return ThemeAlignmentReport(
                    judgment=None,
                    penalty=0,
                    deep_dive=[DeepDiveItem(
                        fact=f"LLM 호출 실패 — {type(e).__name__}: {str(e)[:100]}",
                        rule="theme_alignment_error",
                        risk="OK",
                        suggestion="네트워크/API 키 확인 후 재시도하세요.",
                    )],
                )

        # ── 패널티 + DeepDive 생성 ──
        penalty, risk = _classify_score(judgment.score)
        deep_dive: list[DeepDiveItem] = []
        if penalty > 0:
            mismatched_str = (
                f" 어긋난 장소: {', '.join(judgment.mismatched_places)}"
                if judgment.mismatched_places else ""
            )
            deep_dive.append(DeepDiveItem(
                fact=(
                    f"테마 일치도 {judgment.score:.2f}/1.0 — "
                    f"{judgment.reasoning}{mismatched_str}"
                ),
                rule="theme_alignment",
                risk=risk,  # type: ignore[arg-type]
                suggestion=(
                    "선택하신 테마에 맞지 않는 장소들을 더 적합한 곳으로 교체하거나, "
                    "테마를 다시 선택해 보세요."
                ),
            ))

        return ThemeAlignmentReport(
            judgment=judgment,
            penalty=penalty,
            deep_dive=deep_dive,
        )

    def _call_llm(
        self,
        prefs: UserPreferences,
        places: list[POIWithCategory],
    ) -> ThemeJudgment:
        """Claude API 실제 호출."""
        user_prompt = _build_user_prompt(prefs, places)

        # Prompt Caching: system을 cache_control로 표시
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

        # Claude의 응답 텍스트 추출
        text_blocks = [b.text for b in message.content if hasattr(b, "text")]
        raw_text = "".join(text_blocks)
        return _parse_llm_response(raw_text)
