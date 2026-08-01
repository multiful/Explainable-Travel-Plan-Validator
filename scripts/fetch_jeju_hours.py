"""제주 POI(pois.csv) 전체에 대해 TourAPI 실제 운영시간을 미리 조회해 캐시 파일로 저장한다.

TourAPIClient.get_operating_hours()는 이미 구현돼 있지만 라이브 요청 경로에서
호출된 적이 없었다(사용자 요청마다 외부 API를 부르면 느리고 불안정하므로).
대신 이 스크립트를 미리 한 번 돌려 data/jeju_hours.json 에 캐시해두고,
router.py는 그 파일을 읽기만 한다 — data/pois.csv 와 동일한 패턴.

usetime이 없거나 파싱 실패해 폴백값(00:00~23:59)이 나온 곳은 캐시에 남기지 않는다
(가짜로 "진짜 데이터"인 척하지 않기 위함) — 그런 곳은 기존처럼 hours_db.py 추정을 쓴다.

Usage:
    python scripts/fetch_jeju_hours.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.data.models import Settings
from src.data.tour_api import TourAPIClient, _FALLBACK_CLOSE, _FALLBACK_OPEN

OUT_PATH = ROOT / "data" / "jeju_hours.json"
CONCURRENCY = 10


async def _fetch_one(client: TourAPIClient, sem: asyncio.Semaphore, content_id: str, ctype: int) -> tuple[str, str, str] | None:
    async with sem:
        open_s, close_s = await client.get_operating_hours(content_id, ctype)
    if (open_s, close_s) == (_FALLBACK_OPEN, _FALLBACK_CLOSE):
        return None
    return content_id, open_s, close_s


async def main() -> None:
    client = TourAPIClient.from_settings(Settings())
    if client is None:
        print("TOUR_API_KEY 없음 — .env 확인")
        return

    df = pd.read_csv(ROOT / "data" / "pois.csv", low_memory=False)
    jeju = df[df["addr1"].astype(str).str.startswith("제주특별자치도")]
    print(f"제주 POI {len(jeju)}건 조회 시작 (동시 {CONCURRENCY}개)")

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        _fetch_one(client, sem, str(row.contentid), int(row.contenttypeid))
        for row in jeju.itertuples()
    ]
    results = await asyncio.gather(*tasks)

    hours = {cid: {"open": o, "close": c} for r in results if r for cid, o, c in [r]}
    OUT_PATH.write_text(json.dumps(hours, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"실제 운영시간 확보: {len(hours)}/{len(jeju)}건 → {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
