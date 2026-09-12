<!-- updated: 2026-09-12 | hash: d61b378c | summary: 전체 검증 파이프라인 오케스트레이터 구현 (ValidationOrchestrator) -->
# Step 2: orchestrator

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (데이터 흐름 섹션)
- `/src/data/models.py`
- `/src/data/tour_api.py`
- `/src/data/kakao_client.py`
- `/src/matrix/travel_matrix.py`
- `/src/graph/builder.py`
- `/src/validation/hard_fail.py`
- `/src/validation/warning.py`
- `/src/validation/scoring.py`
- `/src/explain/explain_engine.py`
- `/phases/5-explain/index.json` (step 1 summary 확인)

## 작업

`src/explain/orchestrator.py`를 구현하고, `tests/test_orchestrator.py`를 작성하라.

### 1. `src/explain/orchestrator.py` 구현

```python
import asyncio
from src.data.models import Settings, ItineraryPlan, ValidationResult
from src.data.tour_api import TourAPIClient
from src.data.kakao_client import KakaoClient
from src.matrix.travel_matrix import TravelMatrixBuilder
from src.graph.neo4j_client import Neo4jClient
from src.graph.builder import ItineraryGraphBuilder
from src.validation.hard_fail import HardFailDetector
from src.validation.warning import WarningDetector
from src.validation.scoring import ScoreCalculator
from src.explain.explain_engine import ExplainEngine

class ValidationOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tour = TourAPIClient(settings.tour_api_key)
        self._kakao = KakaoClient(settings.kakao_rest_api_key, settings.kakao_mobility_key)
        self._hard_fail = HardFailDetector()
        self._warning = WarningDetector()
        self._score = ScoreCalculator()
        self._explain = ExplainEngine(settings)
        # Neo4j 연결 (실패 시 None, Graph 저장 skip)
        try:
            self._neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        except Exception:
            self._neo4j = None

    async def run(self, plan: ItineraryPlan) -> ValidationResult:
        """
        전체 파이프라인 실행:
        1. TourAPI → POI 메타데이터 (병렬)
        2. Kakao → 좌표 정규화 (병렬)
        3. TravelMatrix 빌드
        4. Neo4j 그래프 저장 (실패 시 skip)
        5. Hard Fail 탐지
        6. Warning 탐지
        7. 점수 계산
        8. 설명 + Repair 제안 생성
        → ValidationResult 반환
        """
        sorted_places = sorted(plan.places, key=lambda p: p.visit_order)

        # 1. POI 조회 (병렬)
        pois = await asyncio.gather(*[
            self._tour.get_poi(p.name) for p in sorted_places
        ])

        # 2. 좌표 정규화 (병렬) + POI 좌표 업데이트
        coords = await asyncio.gather(*[
            self._kakao.normalize_poi(poi.name) for poi in pois
        ])
        for poi, (lat, lng) in zip(pois, coords):
            if lat != 0.0 and lng != 0.0:
                object.__setattr__(poi, "lat", lat)
                object.__setattr__(poi, "lng", lng)

        # 3. 이동시간 행렬
        matrix_builder = TravelMatrixBuilder(self._kakao)
        matrix = await matrix_builder.build(list(pois), plan.transport)

        # 4. Neo4j 저장 (실패 시 skip)
        if self._neo4j:
            try:
                builder = ItineraryGraphBuilder(self._neo4j)
                builder.build(plan, list(pois), matrix)
            except Exception:
                pass  # Graph 저장 실패는 전체 파이프라인을 막지 않음

        # 5-7. Validation
        hard_fails = self._hard_fail.detect(plan, list(pois), matrix)
        warnings = self._warning.detect(plan, list(pois), matrix)
        scores, final_score = self._score.compute(plan, list(pois), matrix, hard_fails)

        # 8. 설명 생성
        explanation, repair_suggestions = await self._explain.explain(
            plan, list(pois), hard_fails, warnings, scores
        )

        return ValidationResult(
            plan_id=plan.plan_id,
            final_score=final_score,
            hard_fails=hard_fails,
            warnings=warnings,
            scores=scores,
            explanation=explanation,
            repair_suggestions=repair_suggestions,
        )
```

### 2. `tests/test_orchestrator.py` 작성

모든 외부 의존성(TourAPI, Kakao, Neo4j, Claude API)을 mock으로 대체:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.explain.orchestrator import ValidationOrchestrator
from src.data.models import Settings, ItineraryPlan, PlaceInput

@pytest.fixture
def settings():
    return Settings(
        anthropic_api_key="test", tour_api_key="test",
        kakao_rest_api_key="test", neo4j_password="test",
    )

@pytest.fixture
def plan():
    return ItineraryPlan(
        places=[
            PlaceInput(name="경복궁", stay_minutes=120, visit_order=1),
            PlaceInput(name="인사동", stay_minutes=60, visit_order=2),
            PlaceInput(name="남산서울타워", stay_minutes=90, visit_order=3),
            PlaceInput(name="명동", stay_minutes=60, visit_order=4),
        ],
        transport="transit",
        travel_type="cultural",
        date="2024-07-20",
    )
```

테스트 케이스:
- `orchestrator.run(plan)` → ValidationResult 반환, plan_id 일치 확인
- TourAPI 404 (ValueError) → HTTPException이 아닌 ValueError 전파
- Neo4j 연결 실패 → 오케스트레이터 초기화는 성공 (`_neo4j = None`)
- Neo4j 저장 실패 → 파이프라인 계속 진행 (skip)
- TourAPI가 POI 수만큼 호출되는지 확인

## Acceptance Criteria

```bash
python -m pytest tests/test_orchestrator.py -v
```

모든 테스트 통과. 모든 외부 의존성은 mock.

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 전체 테스트 스위트 실행:
   ```bash
   python -m pytest tests/ -v --tb=short
   ```
3. `phases/5-explain/index.json`의 step 2 status를 업데이트한다.

## 금지사항

- Neo4j 저장 실패 시 전체 파이프라인이 중단되면 안 된다. `try/except`로 skip 처리.
- `asyncio.gather`로 TourAPI와 Kakao를 병렬 호출하라. 순차 호출 금지.
- 설명 엔진 실패 시 예외를 그대로 전파하라 (API 503으로 처리됨).
