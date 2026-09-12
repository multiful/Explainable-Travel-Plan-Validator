<!-- updated: 2026-09-12 | hash: bbad0bda | summary: 5개 지표(Efficiency·Feasibility·PurposeFit·Flow·AreaIntensity) → Final Score 계산 -->
# Step 2: scoring

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (점수 계산 공식 섹션)
- `/src/data/models.py`
- `/src/validation/hard_fail.py`
- `/src/validation/warning.py`
- `/phases/4-validation/index.json` (step 1 summary 확인)

## 작업

`src/validation/scoring.py`를 구현하고, `tests/test_scoring.py`를 작성하라.

### 1. `src/validation/scoring.py` 구현

```python
import math
from src.data.models import POI, ItineraryPlan, HardFail, Scores

WEIGHTS = {
    "efficiency":     0.30,
    "feasibility":    0.25,
    "purpose_fit":    0.20,
    "flow":           0.15,
    "area_intensity": 0.10,
}
HARD_FAIL_SCORE_CAP = 59

class ScoreCalculator:
    def compute(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
        hard_fails: list[HardFail],
    ) -> tuple[Scores, int]:
        """
        5개 지표 계산 + Final Score (0~100) 반환.
        hard_fails 있으면 Final Score ≤ 59.
        반환: (Scores, final_score)
        """
        efficiency     = self._calc_efficiency(pois, matrix)
        feasibility    = self._calc_feasibility(plan, pois, matrix, hard_fails)
        purpose_fit    = self._calc_purpose_fit(plan, pois)
        flow           = self._calc_flow(pois, matrix)
        area_intensity = self._calc_area_intensity(pois)

        scores = Scores(
            efficiency=round(efficiency, 4),
            feasibility=round(feasibility, 4),
            purpose_fit=round(purpose_fit, 4),
            flow=round(flow, 4),
            area_intensity=round(area_intensity, 4),
        )
        raw = sum(
            getattr(scores, k) * w
            for k, w in WEIGHTS.items()
        )
        final_score = round(raw * 100)
        if hard_fails:
            final_score = min(final_score, HARD_FAIL_SCORE_CAP)
        return scores, final_score

    def _calc_efficiency(self, pois: list[POI], matrix: dict) -> float:
        """
        Efficiency = baseline_heuristic_distance / actual_total_distance
        baseline: nearest-neighbor heuristic starting from poi[0]
        actual: 방문 순서 그대로의 이동 거리 합
        clamp 결과를 [0, 1] 범위로.
        """
        ...

    def _calc_feasibility(self, plan, pois, matrix, hard_fails) -> float:
        """
        hard_feasibility = 0 if hard_fails else 1
        temporal_feasibility = clamp(1 - excess_ratio, 0, 1)
        human_feasibility = 1 - clamp(total_km / 50, 0, 1)
        Feasibility = hard × 0.5 + temporal × 0.3 + human × 0.2
        """
        ...

    def _calc_purpose_fit(self, plan: ItineraryPlan, pois: list[POI]) -> float:
        """
        1 - cosine_distance(intent_vector, activity_vector)
        INTENT_VECTORS에서 travel_type별 기대 분포 사용.
        """
        ...

    def _calc_flow(self, pois: list[POI], matrix: dict) -> float:
        """
        1 - (backtracking_ratio × 0.5 + revisit_area_ratio × 0.3 + cluster_switch_ratio × 0.2)
        클수록 좋음 (비효율 낮음).
        """
        ...

    def _calc_area_intensity(self, pois: list[POI]) -> float:
        """
        1 - (동일 category 내 POI 비율)
        분산될수록 1에 가까움.
        """
        ...

    @staticmethod
    def _cosine_distance(v1: dict, v2: dict) -> float:
        """두 카테고리 분포 벡터의 코사인 거리 (0=동일, 1=완전 다름)."""
        keys = set(v1) | set(v2)
        dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in keys)
        norm1 = math.sqrt(sum(v ** 2 for v in v1.values()))
        norm2 = math.sqrt(sum(v ** 2 for v in v2.values()))
        if norm1 == 0 or norm2 == 0:
            return 1.0
        return 1.0 - (dot / (norm1 * norm2))
```

### 2. `tests/test_scoring.py` 작성

외부 I/O 없음. mock 불필요.

테스트 케이스:
- `compute(plan, pois, matrix, hard_fails=[])` → final_score 범위 0~100
- `compute(plan, pois, matrix, hard_fails=[HardFail(...)])` → final_score ≤ 59
- `_calc_efficiency` 최적 경로 = 실제 경로 → efficiency ≈ 1.0
- `_calc_feasibility` hard_fails=[] → hard_feasibility = 1
- `_calc_purpose_fit` travel_type="cultural" + 모든 POI category=14 → purpose_fit 높음
- `_cosine_distance` 동일 벡터 → 0.0, 완전 다른 벡터 → 1.0
- Scores 합산 가중치 총합 = 1.0 확인 (WEIGHTS 상수 검증)

## Acceptance Criteria

```bash
python -m pytest tests/test_scoring.py -v
```

모든 테스트 통과.

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 전체 validation 모듈 테스트:
   ```bash
   python -m pytest tests/test_hard_fail.py tests/test_warning.py tests/test_scoring.py -v
   ```
3. `phases/4-validation/index.json`의 step 2 status를 업데이트한다.

## 금지사항

- 외부 I/O를 이 모듈에서 직접 호출하지 마라. 순수 Python + math 계산만.
- WEIGHTS 딕셔너리의 합계가 1.0이 되어야 한다. 변경 시 반드시 합계 검증.
- Hard Fail 없을 때 final_score > 59 가능해야 한다 (cap은 Hard Fail 존재 시에만 적용).
