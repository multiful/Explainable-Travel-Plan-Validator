<!-- updated: 2026-09-12 | hash: aeb253c9 | summary: src/ 전체 모듈 스텁 파일 생성 (새 아키텍처 기준) -->
# Step 1: src-scaffold

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 구조와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/phases/0-setup/index.json` (step 0 summary 확인)

## 작업

`src/` 디렉토리 하위의 모든 모듈 파일을 **스텁(인터페이스만, 구현은 `raise NotImplementedError`)** 으로 생성하라.
이후 각 phase에서 실제 구현으로 교체한다.

### 생성할 파일 목록

**패키지 `__init__.py`** (각각 빈 파일):
`src/data/__init__.py`, `src/matrix/__init__.py`, `src/graph/__init__.py`,
`src/validation/__init__.py`, `src/explain/__init__.py`, `src/api/__init__.py`

---

**`src/data/models.py`** — Pydantic 모델 정의 (실제 구현, 스텁 아님)

```python
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

class POI(BaseModel):
    poi_id: str
    name: str
    lat: float
    lng: float
    category: str
    open_start: str  # "HH:MM"
    open_end: str    # "HH:MM"
    duration_min: int

class PlaceInput(BaseModel):
    name: str
    stay_minutes: int
    visit_order: int

class ItineraryPlan(BaseModel):
    plan_id: str
    places: list[PlaceInput]
    transport: str   # "transit" | "car" | "walk"
    travel_type: str # "cultural" | "nature" | "shopping" | "food" | "adventure"
    date: str        # "YYYY-MM-DD"
    start_time: str = "09:00"  # "HH:MM"

class HardFail(BaseModel):
    type: str
    message: str
    affected_places: list[str]
    confidence: str  # "High" | "Medium" | "Medium-Low"
    evidence: dict

class Warning(BaseModel):
    type: str
    message: str
    affected_places: list[str]
    confidence: str

class Scores(BaseModel):
    efficiency: float
    feasibility: float
    purpose_fit: float
    flow: float
    area_intensity: float

class RepairSuggestion(BaseModel):
    priority: int
    action: str
    affected_places: list[str]
    detail: str

class ValidationResult(BaseModel):
    plan_id: str
    final_score: int = Field(ge=0, le=100)
    hard_fails: list[HardFail]
    warnings: list[Warning]
    scores: Scores
    explanation: str
    repair_suggestions: list[RepairSuggestion]

class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    tour_api_key: str = ""
    kakao_rest_api_key: str = ""
    kakao_mobility_key: str = ""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

---

**`src/data/tour_api.py`** — 스텁

```python
class TourAPIClient:
    def __init__(self, api_key: str) -> None: ...
    async def get_poi(self, place_name: str) -> "POI": raise NotImplementedError
```

**`src/data/kakao_client.py`** — 스텁

```python
class KakaoClient:
    def __init__(self, rest_api_key: str, mobility_key: str = "") -> None: ...
    async def normalize_poi(self, place_name: str) -> tuple[float, float]: raise NotImplementedError
    async def get_travel_time(self, origin: tuple, dest: tuple, mode: str) -> dict: raise NotImplementedError
```

---

**`src/matrix/travel_matrix.py`** — 스텁

```python
class TravelMatrixBuilder:
    def __init__(self, kakao_client) -> None: ...
    async def build(self, pois: list, mode: str) -> dict: raise NotImplementedError
    # 반환: {i: {j: {"travel_min": float, "distance_km": float, "mode": str, "is_fallback": bool}}}
```

---

**`src/graph/neo4j_client.py`** — 스텁

```python
class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None: ...
    def __enter__(self) -> "Neo4jClient": raise NotImplementedError
    def __exit__(self, *args) -> None: raise NotImplementedError
    def run(self, query: str, **params) -> list[dict]: raise NotImplementedError
```

**`src/graph/schema.py`** — 상수 정의 (실제 구현)

```python
class NodeLabel:
    POI = "POI"
    AREA = "Area"
    TIME_SLOT = "TimeSlot"

class RelType:
    IN_AREA = "IN_AREA"
    SCHEDULED_AT = "SCHEDULED_AT"
    FOLLOWED_BY = "FOLLOWED_BY"
    TRAVELS_TO = "TRAVELS_TO"
```

**`src/graph/builder.py`** — 스텁

```python
class ItineraryGraphBuilder:
    def __init__(self, client) -> None: ...
    def build(self, plan, pois: list, matrix: dict) -> None: raise NotImplementedError
```

**`src/graph/queries.py`** — 스텁

```python
def get_total_travel_time(client, slot_ids: list) -> float: raise NotImplementedError
def get_area_revisits(client, poi_ids: list) -> list[dict]: raise NotImplementedError
def get_operating_conflicts(client, poi_ids: list) -> list[dict]: raise NotImplementedError
```

---

**`src/validation/hard_fail.py`** — 스텁

```python
class HardFailDetector:
    def detect(self, plan, pois: list, matrix: dict) -> list["HardFail"]: raise NotImplementedError
```

**`src/validation/warning.py`** — 스텁

```python
class WarningDetector:
    def detect(self, plan, pois: list, matrix: dict) -> list["Warning"]: raise NotImplementedError
```

**`src/validation/scoring.py`** — 스텁

```python
class ScoreCalculator:
    def compute(self, plan, pois: list, matrix: dict, hard_fails: list) -> "Scores": raise NotImplementedError
```

---

**`src/explain/prompts.py`** — 스텁

```python
def build_system_prompt() -> str: raise NotImplementedError
def build_user_prompt(plan, pois, hard_fails, warnings, scores) -> str: raise NotImplementedError
```

**`src/explain/explain_engine.py`** — 스텁

```python
class ExplainEngine:
    def __init__(self, settings) -> None: ...
    async def explain(self, plan, hard_fails, warnings, scores) -> tuple[str, list]: raise NotImplementedError
    # 반환: (explanation_text, repair_suggestions)
```

**`src/explain/orchestrator.py`** — 스텁

```python
class ValidationOrchestrator:
    def __init__(self, settings) -> None: ...
    async def run(self, plan: "ItineraryPlan") -> "ValidationResult": raise NotImplementedError
```

---

**`src/api/schemas.py`** — 스텁

```python
from pydantic import BaseModel
class ValidateRequest(BaseModel): ...
class ValidateResponse(BaseModel): ...
class RepairResponse(BaseModel): ...
class HealthResponse(BaseModel): ...
```

**`src/api/routes.py`** — 스텁  
**`src/api/main.py`** — 스텁

## Acceptance Criteria

```bash
python -c "
from src.data.models import POI, ItineraryPlan, ValidationResult, Settings
from src.data.tour_api import TourAPIClient
from src.data.kakao_client import KakaoClient
from src.matrix.travel_matrix import TravelMatrixBuilder
from src.graph.neo4j_client import Neo4jClient
from src.graph.schema import NodeLabel, RelType
from src.graph.builder import ItineraryGraphBuilder
from src.graph.queries import get_total_travel_time
from src.validation.hard_fail import HardFailDetector
from src.validation.warning import WarningDetector
from src.validation.scoring import ScoreCalculator
from src.explain.prompts import build_system_prompt
from src.explain.explain_engine import ExplainEngine
from src.explain.orchestrator import ValidationOrchestrator
from src.api.main import app
print('All stubs import OK')
"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `src/data/models.py`의 Pydantic 모델이 ARCHITECTURE.md 스키마와 일치하는지 확인한다.
3. 결과에 따라 `phases/0-setup/index.json`의 step 1 status를 업데이트한다.

## 금지사항

- `src/data/models.py`와 `src/graph/schema.py` 외 다른 파일에 실제 로직을 구현하지 마라.
- 구현 없는 함수에 `pass`를 쓰지 마라. 반드시 `raise NotImplementedError`로 명시한다.
- `tests/` 디렉토리는 이 step에서 만들지 마라.




==========================

  ┌──────────────┬─────────────────────────────────────────────────┐
  │     차트     │                    말하는 것                    │
  ├──────────────┼─────────────────────────────────────────────────┤
  │ ① 히스토그램 │ 이동 비율 분포 — 꼬리가 두껍고 위험11 구간이 존재 │
  ├──────────────┼─────────────────────────────────────────────────┤
  │ ② 박스플롯   │ 2박3일 일정의 분산이 심각 — 이상값 다수         │
  ├──────────────┼─────────────────────────────────────────────────┤
  │ ③ 파이차트   │ 1/6이 경고 이상 — 검증 없이 신뢰 불가           │
  ├──────────────┼─────────────────────────────────────────────────┤
  │ ④ 산점도     │ AI가 50km+ 떨어진 장소를 같은 날 배치하는 패턴  │
  └──────────────┴─────────────────────────────────────────────────┘
