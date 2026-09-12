<!-- updated: 2026-09-12 | hash: fcda23fc | summary: Hard Fail 탐지기 구현 (운영시간 충돌·이동 불가·시간 수행 불가) -->
# Step 0: hard-fail

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (Hard Fail 섹션, Confidence Level)
- `/docs/PRD.md` (검증 프레임워크)
- `/src/data/models.py`
- `/phases/4-validation/index.json`

## 작업

`src/validation/hard_fail.py`를 구현하고, `tests/test_hard_fail.py`를 작성하라.

### 1. `src/validation/hard_fail.py` 구현

```python
from src.data.models import POI, ItineraryPlan, HardFail

HARD_FAIL_TYPES = {
    "OPERATING_HOURS_CONFLICT": "도착 예상 시간이 POI 운영시간 외",
    "TRAVEL_TIME_IMPOSSIBLE": "이동시간이 이용 가능한 시간 창을 초과",
    "SCHEDULE_INFEASIBLE": "전체 일정이 시간 내 수행 불가능",
}

class HardFailDetector:
    def detect(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
    ) -> list[HardFail]:
        """
        Hard Fail 목록 반환. 없으면 빈 리스트.
        순서: 운영시간 충돌 → 이동 불가 → 전체 시간 불가
        """
        fails = []
        fails.extend(self._check_operating_hours(plan, pois, matrix))
        fails.extend(self._check_travel_impossible(plan, pois, matrix))
        fails.extend(self._check_schedule_infeasible(plan, pois, matrix))
        return fails

    def _check_operating_hours(
        self, plan: ItineraryPlan, pois: list[POI], matrix: dict
    ) -> list[HardFail]:
        """
        각 POI 도착 예상 시간이 운영시간(open_start ~ open_end) 밖이면 Hard Fail.
        도착 시간 계산: start_time + (이전 POI까지 이동시간 + 체류시간) 누적
        """
        ...

    def _check_travel_impossible(
        self, plan: ItineraryPlan, pois: list[POI], matrix: dict
    ) -> list[HardFail]:
        """
        이동시간이 이용 가능한 시간 창(다음 POI 운영 종료 - 현재 POI 출발)보다 크면 Hard Fail.
        """
        ...

    def _check_schedule_infeasible(
        self, plan: ItineraryPlan, pois: list[POI], matrix: dict
    ) -> list[HardFail]:
        """
        총 체류시간 + 총 이동시간이 24시간을 초과하면 Hard Fail.
        """
        ...

    @staticmethod
    def _time_to_min(hhmm: str) -> int:
        """"HH:MM" → 자정 기준 분."""
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m

    @staticmethod
    def _min_to_time(minutes: int) -> str:
        """자정 기준 분 → "HH:MM"."""
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
```

### 2. `tests/test_hard_fail.py` 작성

외부 I/O 없음 (순수 Python 계산). mock 불필요.

**Synthetic test 케이스 (의도적 Hard Fail 주입)**:

```python
import pytest
from src.data.models import POI, ItineraryPlan, PlaceInput
from src.validation.hard_fail import HardFailDetector

@pytest.fixture
def detector():
    return HardFailDetector()

@pytest.fixture
def open_poi():
    return POI(poi_id="1", name="A", lat=37.579, lng=126.977,
               category="14", open_start="09:00", open_end="18:00", duration_min=60)
```

테스트 케이스:
- 도착 시간 09:10 / 운영 09:00~18:00 → Hard Fail 없음
- 도착 시간 08:30 / 운영 09:00~18:00 → OPERATING_HOURS_CONFLICT Hard Fail
- 도착 시간 18:30 / 운영 09:00~18:00 → OPERATING_HOURS_CONFLICT Hard Fail
- 이동시간 200분 / 가용 시간 창 60분 → TRAVEL_TIME_IMPOSSIBLE Hard Fail
- 총 체류+이동 시간 25시간 → SCHEDULE_INFEASIBLE Hard Fail
- 정상 일정 (4개 장소, 합리적 시간) → 빈 리스트
- `_time_to_min("09:30")` → 570
- `_min_to_time(570)` → "09:30"

## Acceptance Criteria

```bash
python -m pytest tests/test_hard_fail.py -v
```

모든 테스트 통과. Hard Fail 탐지 정확도 ≥ 90% (Synthetic test 기준).

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/4-validation/index.json`의 step 0 status를 업데이트한다.

## 금지사항

- 외부 I/O(Neo4j, API)를 이 모듈에서 직접 호출하지 마라. 순수 Python 계산만.
- HardFail.confidence는 ARCHITECTURE.md Confidence Level 표를 따른다 ("High" for 이동불가, "Medium" for 운영시간).
- 운영시간을 "00:00"~"23:59"로 파싱한 경우 (폴백), OPERATING_HOURS_CONFLICT를 생성하지 마라 (운영시간 미확인으로 처리).
