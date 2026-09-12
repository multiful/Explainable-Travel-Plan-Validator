<!-- updated: 2026-09-12 | hash: 36f9d9c2 | summary: Pydantic 데이터 모델 완성 (POI, ItineraryPlan, ValidationResult, Settings) -->
# Step 0: data-models

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/docs/PRD.md`
- `/src/data/models.py` (phase 0에서 작성된 스텁)
- `/phases/0-setup/index.json`

## 작업

`src/data/models.py`의 Pydantic 모델을 완성하고, `tests/test_data_models.py`를 작성하라.

### 1. `src/data/models.py` 완성

기존 스텁을 아래 기준으로 완성하라:

- `POI`:
  - `poi_id`: 비어있으면 ValidationError
  - `lat`: ge=-90, le=90
  - `lng`: ge=-180, le=180
  - `open_start`, `open_end`: "HH:MM" 형식 검증 (regex)
  - `duration_min`: gt=0

- `PlaceInput`:
  - `stay_minutes`: gt=0, le=720 (12시간 이내)
  - `visit_order`: ge=1

- `ItineraryPlan`:
  - `places`: 4개 이상 8개 이하 검증 (validator)
  - `transport`: Literal["transit", "car", "walk"]
  - `travel_type`: Literal["cultural", "nature", "shopping", "food", "adventure"]
  - `plan_id` 자동 생성:
    ```python
    import hashlib
    @computed_field
    def plan_id(self) -> str:
        key = "_".join(p.name for p in sorted(self.places, key=lambda x: x.visit_order)) + self.date
        return hashlib.sha256(key.encode()).hexdigest()[:12]
    ```

- `ValidationResult`:
  - `final_score`: ge=0, le=100
  - Hard Fail 존재 시 final_score ≤ 59 검증 (model_validator)

- `Settings`:
  - `.env` 없어도 기본값으로 로드 (ValueError 발생하면 안 됨)

### 2. `tests/__init__.py` 생성 (빈 파일, 아직 없으면)

### 3. `tests/test_data_models.py` 작성

아래 케이스를 커버하는 pytest 테스트:

- `POI` 정상 생성
- `POI` 빈 poi_id → ValidationError
- `POI` lat 범위 초과 → ValidationError
- `PlaceInput` stay_minutes=0 → ValidationError
- `ItineraryPlan` places 3개 → ValidationError (최소 4개)
- `ItineraryPlan` places 9개 → ValidationError (최대 8개)
- `ItineraryPlan` transport 무효값 → ValidationError
- `ItineraryPlan` plan_id 자동 생성 확인 (동일 입력 → 동일 plan_id)
- `ValidationResult` hard_fails 있음 + final_score=70 → ValidationError (60 이상 불허)
- `ValidationResult` hard_fails 있음 + final_score=50 → 정상
- `Settings` 기본값 로드 (실제 .env 없이 기본값만 검증)

## Acceptance Criteria

```bash
python -m pytest tests/test_data_models.py -v
```

모든 테스트 통과 + 경고 없음.

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/1-data/index.json`의 step 0 status를 업데이트한다.

## 금지사항

- `src/data/tour_api.py`, `src/data/kakao_client.py`는 이 step에서 건드리지 마라.
- ORM 또는 DB 관련 코드를 models.py에 섞지 마라. 순수 Pydantic 모델만.
