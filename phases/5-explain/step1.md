<!-- updated: 2026-09-12 | hash: c03f1f3b | summary: Claude API 호출로 4단계 Evidence-based 설명 + Repair 제안 생성 -->
# Step 1: explain-engine

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (설명 엔진 출력 구조)
- `/src/data/models.py`
- `/src/explain/prompts.py`
- `/phases/5-explain/index.json` (step 0 summary 확인)

## 작업

`src/explain/explain_engine.py`를 구현하고, `tests/test_explain_engine.py`를 완성하라.

### 1. `src/explain/explain_engine.py` 구현

```python
import anthropic
from src.data.models import Settings, ItineraryPlan, POI, HardFail, Warning, Scores, RepairSuggestion
from src.explain.prompts import build_system_prompt, build_user_prompt, build_repair_prompt

class ExplainEngine:
    def __init__(self, settings: Settings) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model

    async def explain(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        hard_fails: list[HardFail],
        warnings: list[Warning],
        scores: Scores,
    ) -> tuple[str, list[RepairSuggestion]]:
        """
        Claude API로 4단계 설명 + Repair 제안 생성.
        반환: (explanation_text, repair_suggestions)
        """
        explanation = await self._generate_explanation(plan, pois, hard_fails, warnings, scores)
        repair_suggestions = await self._generate_repair(plan, hard_fails, warnings)
        return explanation, repair_suggestions

    async def _generate_explanation(self, plan, pois, hard_fails, warnings, scores) -> str:
        """
        Anthropic Messages API 호출.
        - system: build_system_prompt() with cache_control
        - user: build_user_prompt(...)
        - max_tokens: 1500
        """
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": build_system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": build_user_prompt(plan, pois, hard_fails, warnings, scores)}],
        )
        return response.content[0].text

    async def _generate_repair(self, plan, hard_fails, warnings) -> list[RepairSuggestion]:
        """
        Repair 제안 생성 → JSON 파싱 → list[RepairSuggestion].
        파싱 실패 시 빈 리스트 반환 (예외 발생 금지).
        """
        ...
```

### 2. `tests/test_explain_engine.py` 완성

`anthropic.AsyncAnthropic`을 mock으로 대체:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.explain.explain_engine import ExplainEngine
from src.data.models import Settings

@pytest.fixture
def mock_anthropic():
    with patch("src.explain.explain_engine.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="[설명 텍스트]")]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        yield mock_client
```

테스트 케이스:
- `explain(plan, pois, [], [], scores)` → (str, list) 반환
- `explain(plan, pois, [hard_fail], [], scores)` → explanation에 Hard Fail 관련 내용 포함
- Claude API 타임아웃 → 3회 재시도 후 예외 발생
- `_generate_repair` JSON 파싱 실패 → 빈 리스트 반환 (예외 없음)
- `messages.create` 호출 시 `cache_control` 포함 확인

## Acceptance Criteria

```bash
python -m pytest tests/test_explain_engine.py -v
```

모든 테스트 통과. 실제 Claude API 호출 없이 mock으로만 실행.

## 검증 절차

1. 위 AC 커맨드를 실행한다 (실제 API 키 없어도 통과해야 함).
2. `phases/5-explain/index.json`의 step 1 status를 업데이트한다.

## 금지사항

- `_generate_repair`에서 JSON 파싱 실패 시 예외를 raise하지 마라. 빈 리스트 반환.
- `system` 파라미터에 cache_control 없이 호출하지 마라 (ADR-004: prompt caching 필수).
- 실제 Claude API 호출하는 테스트를 작성하지 마라.
