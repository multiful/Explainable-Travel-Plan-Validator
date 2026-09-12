<!-- updated: 2026-09-12 | hash: f9f6aa14 | summary: Pairwise 이동시간·거리 행렬 빌더 구현 (Kakao Mobility + 직선거리 폴백) -->
# Step 0: travel-matrix

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (Matrix 섹션)
- `/docs/DATA_COLLECTION.md` (Kakao Mobility 폴백 공식)
- `/src/data/models.py`
- `/src/data/kakao_client.py`
- `/phases/2-matrix/index.json`

## 작업

`src/matrix/travel_matrix.py`를 구현하고, `tests/test_travel_matrix.py`를 작성하라.

### 1. `src/matrix/travel_matrix.py` 구현

```python
import asyncio
from src.data.models import POI
from src.data.kakao_client import KakaoClient

class TravelMatrixBuilder:
    def __init__(self, kakao_client: KakaoClient) -> None:
        self._kakao = kakao_client

    async def build(self, pois: list[POI], mode: str) -> dict:
        """
        N개 POI의 Pairwise 이동시간·거리 행렬 반환.
        반환형:
        {
          i: {
            j: {"travel_min": float, "distance_km": float, "mode": str, "is_fallback": bool}
          }
        }
        i == j → travel_min=0, distance_km=0, is_fallback=False
        """
        n = len(pois)
        matrix: dict[int, dict] = {}
        for i in range(n):
            matrix[i] = {}
            for j in range(n):
                if i == j:
                    matrix[i][j] = {"travel_min": 0, "distance_km": 0, "mode": mode, "is_fallback": False}
                else:
                    result = await self._kakao.get_travel_time(
                        pois[i].lat, pois[i].lng,
                        pois[j].lat, pois[j].lng,
                        mode,
                    )
                    matrix[i][j] = {**result, "mode": mode}
        return matrix

    def get_travel_min(self, matrix: dict, from_idx: int, to_idx: int) -> float:
        """행렬에서 from_idx → to_idx 이동시간(분) 조회."""
        return matrix[from_idx][to_idx]["travel_min"]

    def total_travel_min(self, matrix: dict, ordered_indices: list[int]) -> float:
        """순서대로 방문할 때 총 이동시간(분) 계산."""
        total = 0.0
        for i in range(len(ordered_indices) - 1):
            total += self.get_travel_min(matrix, ordered_indices[i], ordered_indices[i + 1])
        return total

    def has_fallback(self, matrix: dict) -> bool:
        """행렬 내 폴백 데이터 존재 여부 확인."""
        for row in matrix.values():
            for cell in row.values():
                if cell.get("is_fallback"):
                    return True
        return False
```

### 2. `tests/test_travel_matrix.py` 작성

`KakaoClient.get_travel_time`을 mock으로 대체해야 한다.

아래 케이스를 커버하라:

- `build(pois=[A, B, C], mode="transit")` → 3×3 행렬 반환
- 대각선 요소 (i==j) → travel_min=0, distance_km=0
- `get_travel_min(matrix, 0, 1)` → 정상 조회
- `total_travel_min(matrix, [0, 1, 2])` → 0→1 + 1→2 이동시간 합계
- `has_fallback` → is_fallback=True인 셀 있으면 True
- KakaoClient.get_travel_time이 N×(N-1)번 호출되는지 확인 (자기 자신 제외)

```python
import pytest
from unittest.mock import AsyncMock
from src.matrix.travel_matrix import TravelMatrixBuilder
from src.data.models import POI

@pytest.fixture
def sample_pois():
    return [
        POI(poi_id="1", name="A", lat=37.579, lng=126.977, category="14",
            open_start="09:00", open_end="18:00", duration_min=60),
        POI(poi_id="2", name="B", lat=37.563, lng=126.983, category="12",
            open_start="10:00", open_end="22:00", duration_min=60),
    ]
```

## Acceptance Criteria

```bash
python -m pytest tests/test_travel_matrix.py -v
```

모든 테스트 통과. 실제 Kakao API 호출 없이 mock으로만 실행.

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/2-matrix/index.json`의 step 0 status를 업데이트한다.

## 금지사항

- 실제 KakaoClient 인스턴스를 테스트에서 사용하지 마라. 모두 mock.
- 행렬을 이중 루프로 순차 호출하되, asyncio.gather로 병렬화하면 더 좋다 (선택사항).
- mode는 "transit" / "car" / "walk" 중 하나만 유효하다. 다른 값이 들어오면 ValueError.
