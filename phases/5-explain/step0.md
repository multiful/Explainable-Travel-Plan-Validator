<!-- updated: 2026-09-12 | hash: 4cde10b4 | summary: LLM 프롬프트 템플릿 구현 (4단계 Evidence-based 설명 + Repair 제안) -->
# Step 0: prompts

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (설명 엔진 출력 구조, Repair 우선순위)
- `/docs/PRD.md`
- `/src/data/models.py`
- `/phases/5-explain/index.json`

## 작업

`src/explain/prompts.py`를 구현하고, `tests/test_explain_engine.py`의 프롬프트 테스트 부분을 작성하라.

### 1. `src/explain/prompts.py` 구현

```python
from src.data.models import ItineraryPlan, POI, HardFail, Warning, Scores

SYSTEM_PROMPT = """당신은 여행 일정 검증 전문 AI입니다.
주어진 여행 일정의 검증 결과를 바탕으로, 아래 4단계 구조로 설명을 작성하세요:

1. 발견된 사실: 구체적 수치 (도착 시간, 운영시간, 이동시간 등)
2. 적용된 규칙: 판정 기준
3. 위험 판정: Hard Fail / Warning 분류 + Confidence
4. 개선 제안: 구체적이고 실행 가능한 수정 방법

Hard Fail이 있으면 해당 내용을 먼저 설명하세요.
모든 수치는 정확하게 인용하세요. 추측하지 마세요.
한국어로 작성하세요.
"""

def build_system_prompt() -> str:
    return SYSTEM_PROMPT

def build_user_prompt(
    plan: ItineraryPlan,
    pois: list[POI],
    hard_fails: list[HardFail],
    warnings: list[Warning],
    scores: Scores,
) -> str:
    """
    검증 결과 전체를 LLM에게 전달하는 사용자 프롬프트.
    포함 내용:
    - 일정 개요 (장소, 이동수단, 날짜)
    - POI별 운영시간 + 도착 예상 시간
    - Hard Fail 목록 (type, message, evidence)
    - Warning 목록 (type, message, confidence)
    - 5개 지표 점수
    - Repair 제안 요청
    """
    ...

def build_repair_prompt(
    plan: ItineraryPlan,
    hard_fails: list[HardFail],
    warnings: list[Warning],
) -> str:
    """
    Repair 제안 생성을 위한 별도 프롬프트.
    우선순위: Hard Fail 제거 → 재방문 제거 → 일정 과밀 완화 → 목적 적합성 → 효율
    """
    ...
```

**Prompt Caching 적용**: `build_system_prompt()`는 변경이 없으므로 Anthropic API 호출 시 `cache_control: {"type": "ephemeral"}`을 적용한다.

### 2. 프롬프트 품질 테스트 추가 (`tests/test_explain_engine.py`에 포함)

```python
from src.explain.prompts import build_system_prompt, build_user_prompt, build_repair_prompt

def test_system_prompt_not_empty():
    assert len(build_system_prompt()) > 100

def test_user_prompt_includes_plan_info(sample_plan, sample_pois, sample_hard_fails, ...):
    prompt = build_user_prompt(...)
    assert "경복궁" in prompt
    assert "09:00" in prompt  # 운영시간 포함 확인

def test_user_prompt_includes_hard_fail_if_present(...):
    prompt = build_user_prompt(... hard_fails=[hard_fail] ...)
    assert "OPERATING_HOURS_CONFLICT" in prompt or "운영시간" in prompt

def test_repair_prompt_includes_priority_order(...):
    prompt = build_repair_prompt(...)
    assert len(prompt) > 50
```

## Acceptance Criteria

```bash
python -m pytest tests/test_explain_engine.py::test_system_prompt_not_empty -v
python -m pytest tests/test_explain_engine.py::test_user_prompt_includes_plan_info -v
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/5-explain/index.json`의 step 0 status를 업데이트한다.

## 금지사항

- 프롬프트에 실제 API 키나 민감 정보를 포함하지 마라.
- 프롬프트 내에서 LLM에게 Hard Fail이 없을 때 Hard Fail이 있는 것처럼 쓰도록 유도하지 마라.
- 시스템 프롬프트는 변경 없이 재사용되므로 동적 데이터를 포함하지 마라.
