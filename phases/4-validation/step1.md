<!-- updated: 2026-09-12 | hash: 3bdb3574 | summary: Warning 탐지기 구현 (동선 비효율·일정 과밀·체력 부담·경험 편향·구역 재방문) -->
# Step 1: warning

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (Soft Warning 섹션)
- `/docs/PRD.md` (검증 프레임워크)
- `/src/data/models.py`
- `/src/validation/hard_fail.py`
- `/phases/4-validation/index.json` (step 0 summary 확인)

## 작업

`src/validation/warning.py`를 구현하고, `tests/test_warning.py`를 작성하라.

### 1. `src/validation/warning.py` 구현

```python
from src.data.models import POI, ItineraryPlan, Warning

WARNING_TYPES = {
    "DENSE_SCHEDULE":    ("일정 과밀",        "Medium"),
    "INEFFICIENT_ROUTE": ("동선 비효율",       "Medium"),
    "PHYSICAL_STRAIN":   ("체력 부담",        "Medium"),
    "PURPOSE_MISMATCH":  ("목적 부적합",      "Medium-Low"),
    "AREA_REVISIT":      ("구역 재방문",      "Medium"),
}

# 여행 타입별 기대 카테고리 분포 (POI category 코드 기준)
INTENT_VECTORS: dict[str, dict[str, float]] = {
    "cultural":   {"14": 0.6, "12": 0.2, "15": 0.1, "other": 0.1},
    "nature":     {"12": 0.5, "15": 0.3, "14": 0.1, "other": 0.1},
    "shopping":   {"38": 0.5, "12": 0.3, "14": 0.1, "other": 0.1},
    "food":       {"39": 0.6, "12": 0.2, "14": 0.1, "other": 0.1},
    "adventure":  {"15": 0.6, "12": 0.2, "14": 0.1, "other": 0.1},
}

class WarningDetector:
    DENSE_THRESHOLD_MIN = 480   # 8시간 초과 시 과밀 경고
    STRAIN_THRESHOLD_KM = 30    # 이동 거리 30km 초과 시 체력 부담
    BACKTRACK_THRESHOLD = 0.3   # backtracking 비율 30% 초과

    def detect(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
    ) -> list[Warning]:
        warns = []
        warns.extend(self._check_dense_schedule(plan, pois, matrix))
        warns.extend(self._check_inefficient_route(plan, pois, matrix))
        warns.extend(self._check_physical_strain(plan, pois, matrix))
        warns.extend(self._check_purpose_mismatch(plan, pois))
        warns.extend(self._check_area_revisit(pois))
        return warns

    def _check_dense_schedule(self, plan, pois, matrix) -> list[Warning]:
        """총 체류시간 + 이동시간이 DENSE_THRESHOLD_MIN 초과 시 Warning."""
        ...

    def _check_inefficient_route(self, plan, pois, matrix) -> list[Warning]:
        """
        Backtracking 탐지: 방문 순서가 최근접 이웃 순서 대비 이동거리가 BACKTRACK_THRESHOLD 이상 초과 시.
        """
        ...

    def _check_physical_strain(self, plan, pois, matrix) -> list[Warning]:
        """총 이동 거리가 STRAIN_THRESHOLD_KM 초과 시 Warning."""
        ...

    def _check_purpose_mismatch(self, plan, pois) -> list[Warning]:
        """
        여행 타입의 intent_vector와 POI 카테고리 분포 불일치 시 Warning.
        PurposeFit < 0.5이면 경고.
        """
        ...

    def _check_area_revisit(self, pois) -> list[Warning]:
        """
        동일 category(구역 대리 지표)를 연속으로 2회 이상 방문 시 Warning.
        """
        ...
```

### 2. `tests/test_warning.py` 작성

외부 I/O 없음. mock 불필요.

테스트 케이스:
- 총 시간 600분 (체류+이동) → DENSE_SCHEDULE Warning
- 총 시간 400분 → Warning 없음
- 총 이동 거리 35km → PHYSICAL_STRAIN Warning
- travel_type="cultural", POI 전부 레포츠(15) → PURPOSE_MISMATCH Warning
- travel_type="cultural", POI 전부 문화시설(14) → PURPOSE_MISMATCH 없음
- 동일 category 3개 연속 → AREA_REVISIT Warning
- 모두 다른 category → AREA_REVISIT 없음

## Acceptance Criteria

```bash
python -m pytest tests/test_warning.py -v
```

모든 테스트 통과.

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/4-validation/index.json`의 step 1 status를 업데이트한다.

## 금지사항

- 외부 I/O를 이 모듈에서 직접 호출하지 마라. 순수 Python 계산만.
- Warning.confidence는 `WARNING_TYPES` 딕셔너리에서 가져와야 한다. 하드코딩 금지.
- INTENT_VECTORS는 MVP 초기값이며 코드에 상수로 정의한다. DB 또는 파일에서 로드하지 마라.
