<!-- updated: 2026-09-12 | hash: 40ca89b7 | summary: TourAPI v2 비동기 클라이언트 구현 (searchKeyword1 + detailIntro1) -->
# Step 1: tour-api-client

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/docs/DATA_COLLECTION.md`
- `/src/data/models.py`
- `/phases/1-data/index.json` (step 0 summary 확인)

## 작업

`src/data/tour_api.py`를 구현하고, `tests/test_tour_api.py`를 작성하라.

### 1. `src/data/tour_api.py` 구현

```python
import re
import httpx
from src.data.models import POI

BASE_URL = "http://apis.data.go.kr/B551011/KorService1"
COMMON_PARAMS = {"MobileOS": "ETC", "MobileApp": "travel-validator", "_type": "json"}

class TourAPIClient:
    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TourAPIClient":
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def get_poi(self, place_name: str) -> POI:
        """장소명으로 POI 조회. 없으면 ValueError."""
        basic = await self._search_keyword(place_name)
        intro = await self._detail_intro(basic["contentid"], basic["contenttypeid"])
        return self._build_poi(basic, intro)

    async def _search_keyword(self, keyword: str) -> dict:
        """searchKeyword1 호출 → 첫 번째 결과. 없으면 ValueError."""
        ...

    async def _detail_intro(self, content_id: str, content_type_id: str) -> dict:
        """detailIntro1 호출 → usetime 등 반환."""
        ...

    @staticmethod
    def _parse_open_hours(usetime: str) -> tuple[str, str]:
        """
        "09:00~18:00(입장마감 17:00)" → ("09:00", "18:00")
        파싱 실패 시 ("00:00", "23:59") 반환
        """
        m = re.search(r"(\d{2}:\d{2})\s*[~～]\s*(\d{2}:\d{2})", usetime or "")
        if m:
            return m.group(1), m.group(2)
        return "00:00", "23:59"

    def _build_poi(self, basic: dict, intro: dict) -> POI:
        open_start, open_end = self._parse_open_hours(intro.get("usetime", ""))
        return POI(
            poi_id=basic["contentid"],
            name=basic["title"],
            lat=float(basic["mapy"]),
            lng=float(basic["mapx"]),
            category=basic.get("contenttypeid", "12"),
            open_start=open_start,
            open_end=open_end,
            duration_min=60,
        )
```

**재시도**: HTTP 5xx / 연결 오류 시 최대 3회 지수 백오프 (1s → 2s → 4s).

### 2. `tests/test_tour_api.py` 작성

`httpx.AsyncClient`를 mock으로 대체해야 한다 (`pytest-mock` 사용).

아래 케이스를 커버하라:

- 정상 응답 → POI 반환 (poi_id, name, lat, lng 일치)
- 운영시간 파싱 "09:00~18:00" → open_start="09:00", open_end="18:00"
- 운영시간 파싱 실패(빈 문자열) → ("00:00", "23:59")
- searchKeyword1 결과 없음 (totalCount=0) → ValueError
- HTTP 503 → 3회 재시도 후 예외 발생
- `_parse_open_hours` 단위 테스트 (다양한 형식)

## Acceptance Criteria

```bash
python -m pytest tests/test_tour_api.py -v
```

모든 테스트 통과. 실제 TourAPI 호출 없이 mock으로만 실행.

## 검증 절차

1. 위 AC 커맨드를 실행한다 (실제 API 키 없어도 통과해야 함).
2. `phases/1-data/index.json`의 step 1 status를 업데이트한다.

## 금지사항

- 실제 TourAPI 호출하는 테스트를 작성하지 마라. 모든 HTTP는 mock.
- `api_key`를 테스트 코드에 하드코딩하지 마라.
- `httpx.Client` (동기) 대신 `httpx.AsyncClient` (비동기)만 사용하라.
- `requests` 라이브러리를 사용하지 마라.
