"""TourAPI areaBasedList2로 전국 POI 수집 → pois.csv에 누락분 추가."""
from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
import httpx

DATA_DIR = Path(__file__).parent.parent / "data"
POIS_CSV = DATA_DIR / "pois.csv"

AREA_CODES = {
    "서울": 1, "인천": 2, "대전": 3, "대구": 4, "광주": 5,
    "부산": 6, "울산": 7, "세종": 8, "경기": 31, "강원": 32,
    "충북": 33, "충남": 34, "경북": 35, "경남": 36,
    "전북": 37, "전남": 38, "제주": 39,
}

CONTENT_TYPES = [12, 14, 15, 25, 28, 32, 38, 39]

BASE_URL = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"
ROWS_PER_PAGE = 1000


def load_existing_ids() -> set[str]:
    ids: set[str] = set()
    if not POIS_CSV.exists():
        return ids
    with open(POIS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cid = row.get("contentid", "").strip()
            if cid:
                ids.add(cid)
    return ids


def load_api_key() -> str:
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TOUR_API_KEY="):
                return line.split("=", 1)[1].strip()
    import os
    return os.getenv("TOUR_API_KEY", "")


async def fetch_page(
    client: httpx.AsyncClient,
    api_key: str,
    area_code: int,
    content_type_id: int,
    page_no: int,
) -> tuple[list[dict], int]:
    params = {
        "serviceKey": api_key,
        "numOfRows": ROWS_PER_PAGE,
        "pageNo": page_no,
        "MobileOS": "ETC",
        "MobileApp": "TravelQA",
        "areaCode": area_code,
        "contentTypeId": content_type_id,
        "_type": "json",
        "arrange": "A",
    }
    for attempt in range(3):
        try:
            r = await client.get(BASE_URL, params=params, timeout=15.0)
            if r.status_code != 200:
                await asyncio.sleep(1)
                continue
            body = r.json().get("response", {}).get("body", {})
            total = int(body.get("totalCount", 0))
            raw = body.get("items", {})
            if not raw:
                return [], total
            items = raw.get("item", [])
            if isinstance(items, dict):
                items = [items]
            return list(items), total
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
    return [], 0


async def fetch_region_type(
    client: httpx.AsyncClient,
    api_key: str,
    area_name: str,
    area_code: int,
    content_type_id: int,
    existing_ids: set[str],
) -> list[dict]:
    new_items: list[dict] = []
    page = 1
    total = None

    while True:
        items, t = await fetch_page(client, api_key, area_code, content_type_id, page)
        if total is None:
            total = t

        for item in items:
            cid = str(item.get("contentid", "")).strip()
            if not cid or cid in existing_ids:
                continue
            mapx = str(item.get("mapx", "")).strip()
            mapy = str(item.get("mapy", "")).strip()
            new_items.append({
                "contentid":     cid,
                "contenttypeid": str(item.get("contenttypeid", content_type_id)),
                "title":         str(item.get("title", "")),
                "addr1":         str(item.get("addr1", "")),
                "addr2":         str(item.get("addr2", "")),
                "zipcode":       str(item.get("zipcode", "")),
                "lDongRegnCd":   "",
                "lDongSignguCd": "",
                "lclsSystm1":    "",
                "lclsSystm2":    "",
                "lclsSystm3":    "",
                "mapx":          mapx,
                "mapy":          mapy,
                "mlevel":        str(item.get("mlevel", "")),
                "tel":           str(item.get("tel", "")),
                "firstimage":    str(item.get("firstimage", "")),
                "firstimage2":   str(item.get("firstimage2", "")),
                "cpyrhtDivCd":   str(item.get("cpyrhtDivCd", "")),
                "createdtime":   str(item.get("createdtime", "")),
                "modifiedtime":  str(item.get("modifiedtime", "")),
            })

        fetched_so_far = (page - 1) * ROWS_PER_PAGE + len(items)
        if not items or fetched_so_far >= total:
            break
        page += 1
        await asyncio.sleep(0.05)

    return new_items


FIELDNAMES = [
    "contentid","contenttypeid","title","addr1","addr2","zipcode",
    "lDongRegnCd","lDongSignguCd","lclsSystm1","lclsSystm2","lclsSystm3",
    "mapx","mapy","mlevel","tel","firstimage","firstimage2",
    "cpyrhtDivCd","createdtime","modifiedtime",
]


async def main() -> None:
    api_key = load_api_key()
    if not api_key:
        print("❌ TOUR_API_KEY 없음")
        return

    existing_ids = load_existing_ids()
    print(f"기존 POI: {len(existing_ids):,}개")

    all_new: list[dict] = []
    t0 = time.time()

    async with httpx.AsyncClient() as client:
        for area_name, area_code in AREA_CODES.items():
            area_new: list[dict] = []
            for ct in CONTENT_TYPES:
                items = await fetch_region_type(
                    client, api_key, area_name, area_code, ct, existing_ids
                )
                for item in items:
                    existing_ids.add(item["contentid"])
                area_new.extend(items)
                await asyncio.sleep(0.08)

            all_new.extend(area_new)
            elapsed = time.time() - t0
            print(f"  {area_name}: +{len(area_new):,}개 신규 | 누적 {len(all_new):,}개 | {elapsed:.0f}s")

    if not all_new:
        print("추가할 장소 없음 (이미 최신 상태)")
        return

    # pois.csv에 추가
    with open(POIS_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        for row in all_new:
            writer.writerow(row)

    print(f"\n✅ {len(all_new):,}개 추가 완료 → {POIS_CSV}")
    print(f"   최종 POI 수: {len(existing_ids):,}개")
    print(f"   소요시간: {time.time()-t0:.0f}초")


if __name__ == "__main__":
    asyncio.run(main())
