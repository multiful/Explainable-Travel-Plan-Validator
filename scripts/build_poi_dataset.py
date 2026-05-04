"""웰니스·무장애 여행지 데이터셋 빌더.

공공데이터포털 API를 호출하여 전체 목록을 JSON으로 저장.
저장 경로: data/wellness_places.json, data/barrier_free_places.json

사용법:
    python scripts/build_poi_dataset.py

환경변수 (.env):
    TOUR_API_KEY=<공공데이터포털 인증키>
    또는
    WELLNESS_API_KEY=<공공데이터포털 인증키>
    BARRIER_FREE_API_KEY=<공공데이터포털 인증키>
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.barrier_free_api import BarrierFreeAPIClient
from src.data.models import Settings
from src.data.wellness_api import WellnessAPIClient

DATA_DIR = Path(__file__).parent.parent / "data"
WELLNESS_PATH = DATA_DIR / "wellness_places.json"
BARRIER_FREE_PATH = DATA_DIR / "barrier_free_places.json"


async def build_wellness(client: WellnessAPIClient) -> int:
    print("[웰니스] 전체 데이터 조회 중...")
    places = await client.fetch_all(num_of_rows=100)
    if not places:
        print("[웰니스] 데이터 없음 (API 응답 실패 또는 빈 결과)")
        return 0

    records = [asdict(p) for p in places]
    WELLNESS_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[웰니스] {len(records)}개 저장 → {WELLNESS_PATH}")
    return len(records)


async def build_barrier_free(client: BarrierFreeAPIClient) -> int:
    print("[무장애] 전체 데이터 조회 중...")
    places = await client.fetch_all(num_of_rows=100)
    if not places:
        print("[무장애] 데이터 없음 (API 응답 실패 또는 빈 결과)")
        return 0

    records = [asdict(p) for p in places]
    BARRIER_FREE_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[무장애] {len(records)}개 저장 → {BARRIER_FREE_PATH}")
    return len(records)


async def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    settings = Settings()

    wellness_client = WellnessAPIClient.from_settings(settings)
    barrier_free_client = BarrierFreeAPIClient.from_settings(settings)

    if wellness_client is None and barrier_free_client is None:
        print(
            "오류: API 키가 설정되지 않았습니다.\n"
            ".env 파일에 TOUR_API_KEY (또는 WELLNESS_API_KEY, BARRIER_FREE_API_KEY)를 설정하세요."
        )
        sys.exit(1)

    tasks = []
    if wellness_client:
        tasks.append(build_wellness(wellness_client))
    else:
        print("[웰니스] API 키 없음 — 스킵")

    if barrier_free_client:
        tasks.append(build_barrier_free(barrier_free_client))
    else:
        print("[무장애] API 키 없음 — 스킵")

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            print(f"오류 발생: {r}")

    print("\n완료.")


if __name__ == "__main__":
    asyncio.run(main())
