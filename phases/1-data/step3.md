<!-- updated: 2026-09-12 | hash: d671fb82 | summary: TourAPI 배치 수집 스크립트 data/collector.py 구현 -->
# Step 3: data-collector

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 기획·아키텍처·설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/DATA_COLLECTION.md` (TourAPI 수집 가이드 + collector.py 설계)
- `/src/data/tour_api.py`
- `/src/data/models.py`
- `/data/samples/` (기존 샘플 파일 확인)
- `/phases/1-data/index.json`

## 작업

### 1. `data/collector.py` 구현

`data/collector.py` 파일을 프로젝트 루트의 `data/` 디렉토리에 생성한다.  
(`src/` 패키지 외부의 운영 스크립트로, `pip install -e ".[dev]"` 이후 `src.*` import 가능.)

```python
# data/collector.py
import asyncio
import json
from pathlib import Path
from src.data.models import Settings
from src.data.tour_api import TourAPIClient

RECOMMENDED_PLACES = [
    "경복궁",
    "남산서울타워",
    "해운대해수욕장",
    "인사동",
    "제주 올레길",
]

class TourDataCollector:
    def __init__(self, client: TourAPIClient, output_dir: Path = Path("data/samples")):
        self.client = client
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def collect_place(self, place_name: str):
        """단일 관광지 수집"""
        return await self.client.get_place(place_name)

    async def collect_batch(self, place_names: list[str], delay: float = 1.0) -> list:
        """여러 관광지 순차 수집 (rate limiting 준수)"""
        results = []
        for name in place_names:
            if self._already_collected(name):
                print(f"[SKIP] {name}: 이미 수집됨")
                continue
            try:
                place = await self.collect_place(name)
                self._save_review_template(place)
                results.append(place)
                print(f"[OK]   {name} ({place.content_id})")
            except ValueError as e:
                print(f"[SKIP] {name}: {e}")
            except Exception as e:
                print(f"[ERR]  {name}: {e}")
            await asyncio.sleep(delay)
        return results

    def _already_collected(self, place_name: str) -> bool:
        # content_id를 모르므로 place_name 기반 파일명으로 확인 불가
        # → 이미 수집된 content_id 목록을 메모리에 유지하거나 skip 불필요
        return False

    def _save_review_template(self, place) -> None:
        path = self.output_dir / f"{place.content_id}.json"
        if path.exists():
            return
        template = {
            "place_id": place.content_id,
            "place_name": place.name,
            "official": {
                "usetime": "",
                "usefee": "",
                "parking": ""
            },
            "reviews": []
        }
        path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[SAVE] {path}")

async def main():
    settings = Settings()
    async with TourAPIClient(settings) as client:
        collector = TourDataCollector(client)
        places = await collector.collect_batch(RECOMMENDED_PLACES)
        print(f"\n수집 완료: {len(places)}개 관광지")

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. `tests/test_data_collector.py` 작성

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile
from data.collector import TourDataCollector
from src.data.models import Place

@pytest.fixture
def mock_place():
    return Place(
        content_id="126508",
        name="경복궁",
        overview="조선의 법궁",
        category="문화시설",
        lat=37.5796,
        lng=126.9770,
    )

@pytest.fixture
def collector(tmp_path):
    client = MagicMock()
    return TourDataCollector(client=client, output_dir=tmp_path)
```

테스트 케이스:
- `collect_batch` 호출 시 성공한 관광지만 반환, ValueError인 관광지는 skip
- `_save_review_template` 호출 시 `{content_id}.json` 파일 생성
- 파일이 이미 존재하면 `_save_review_template`이 덮어쓰지 않음
- `collect_batch` 에서 `asyncio.sleep` 이 `delay`초로 호출됨 (monkeypatch)

## Acceptance Criteria

```bash
python -m pytest tests/test_data_collector.py -v
ruff check data/collector.py
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. (선택) `.env`의 `TOUR_API_KEY`가 유효하면 실제 수집 테스트:
   ```bash
   python data/collector.py
   ```
   `data/samples/` 에 JSON 파일 생성 확인.
3. `phases/1-data/index.json`의 step 3 status를 업데이트한다.

## 금지사항

- `data/collector.py` 에서 `Settings()` 외에 API 키를 직접 참조하지 마라.
- `TourAPIClient`를 사용하지 않고 `httpx`를 직접 호출하지 마라.
- `data/samples/` 디렉토리의 기존 파일을 덮어쓰지 마라 (멱등성 보장).
- `src/` 패키지 내부에 이 스크립트를 넣지 마라 (`src/` 는 라이브러리 코드만).
