<!-- updated: 2026-09-12 | hash: fa4058f8 | summary: Kakao Local + Mobility API 비동기 클라이언트 구현 및 직선거리 폴백 -->
# Step 2: kakao-client

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/docs/DATA_COLLECTION.md`
- `/src/data/models.py`
- `/phases/1-data/index.json` (step 1 summary 확인)

## 작업

`src/data/kakao_client.py`를 구현하고, `tests/test_kakao_client.py`를 작성하라.

### 1. `src/data/kakao_client.py` 구현

```python
import math
import httpx

LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
MOBILITY_URL = "https://apis-navi.kakaomobility.com/v1/directions"

SPEED_KMH = {"transit": 20.0, "car": 40.0, "walk": 4.0}
ROUTE_FACTOR = {"transit": 1.3, "car": 1.1, "walk": 1.0}

class KakaoClient:
    def __init__(self, rest_api_key: str, mobility_key: str = "") -> None:
        self._rest_key = rest_api_key
        self._mob_key = mobility_key
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "KakaoClient":
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def normalize_poi(self, place_name: str) -> tuple[float, float]:
        """
        Kakao Local API로 장소명 → (lat, lng) 반환.
        실패 시 (0.0, 0.0) 반환 (호출자가 TourAPI 좌표로 폴백).
        """
        ...

    async def get_travel_time(
        self,
        origin_lat: float, origin_lng: float,
        dest_lat: float, dest_lng: float,
        mode: str,
    ) -> dict:
        """
        Kakao Mobility API로 이동시간 계산.
        mobility_key 없거나 실패 시 직선거리 폴백.
        반환: {"travel_min": float, "distance_km": float, "is_fallback": bool}
        """
        if not self._mob_key:
            return self._fallback(origin_lat, origin_lng, dest_lat, dest_lng, mode)
        ...

    @staticmethod
    def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlng / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    @classmethod
    def _fallback(cls, lat1, lng1, lat2, lng2, mode: str) -> dict:
        dist_km = cls._haversine_km(lat1, lng1, lat2, lng2) * ROUTE_FACTOR[mode]
        travel_min = (dist_km / SPEED_KMH[mode]) * 60
        return {"travel_min": round(travel_min, 1), "distance_km": round(dist_km, 2), "is_fallback": True}
```

### 2. `tests/test_kakao_client.py` 작성

아래 케이스를 커버하라:

- `normalize_poi` 정상 응답 → (lat, lng) 반환
- `normalize_poi` API 실패 → (0.0, 0.0) 반환 (예외 발생 금지)
- `get_travel_time` mobility_key 없음 → 폴백 결과 반환, `is_fallback=True`
- `get_travel_time` Mobility API 정상 → `is_fallback=False`
- `get_travel_time` Mobility API 실패 → 폴백 결과 반환
- `_haversine_km` 단위 테스트: 서울(37.566, 126.978)-부산(35.179, 129.075) ≈ 325km ±10%
- `_fallback` mode별 travel_min 계산 검증

## Acceptance Criteria

```bash
python -m pytest tests/test_kakao_client.py -v
```

모든 테스트 통과. 실제 Kakao API 호출 없이 mock으로만 실행.

## 검증 절차

1. 위 AC 커맨드를 실행한다 (실제 API 키 없어도 통과해야 함).
2. `phases/1-data/index.json`의 step 2 status를 업데이트한다.

## 금지사항

- `normalize_poi` 실패 시 예외를 raise하지 마라. (0.0, 0.0) 폴백 반환.
- 실제 Kakao API 호출하는 테스트를 작성하지 마라.
- mobility_key가 빈 문자열이면 Mobility API를 호출하지 말고 직접 폴백으로 진입하라.
