"""한국관광공사 웰니스 관광 정보 API 클라이언트 (B551011/WellnessTursmService)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from src.data.models import Settings

_BASE_URL = "https://apis.data.go.kr/B551011/WellnessTursmService"
_LIST_OP = "getWellnessTursmList"


@dataclass(frozen=True)
class WellnessPlace:
    content_id: str
    title: str
    addr: str
    lat: float   # mapy
    lng: float   # mapx
    cat1: str = ""
    cat2: str = ""
    cat3: str = ""


def _extract_items(data: dict) -> list[dict]:
    try:
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            return [items]
        return list(items)
    except (KeyError, TypeError):
        return []


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class WellnessAPIClient:
    """웰니스 관광 정보 API — 비동기 클라이언트.

    Graceful Fallback: API 호출 실패 시 빈 리스트 반환.
    """

    def __init__(self, api_key: str, timeout_sec: float = 10.0) -> None:
        if not api_key:
            raise ValueError("wellness_api_key 없음. .env에 WELLNESS_API_KEY를 설정하세요.")
        self._key = api_key
        self._timeout = timeout_sec

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "WellnessAPIClient | None":
        if settings is None:
            settings = Settings()
        key = settings.wellness_api_key
        if not key:
            return None
        return cls(api_key=key)

    async def fetch_page(
        self,
        page_no: int = 1,
        num_of_rows: int = 100,
        area_code: str = "",
    ) -> list[WellnessPlace]:
        """웰니스 관광 목록 한 페이지 조회."""
        params: dict[str, Any] = {
            "serviceKey": self._key,
            "numOfRows": num_of_rows,
            "pageNo": page_no,
            "MobileOS": "ETC",
            "MobileApp": "TravelQA",
            "_type": "json",
        }
        if area_code:
            params["areaCode"] = area_code

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{_BASE_URL}/{_LIST_OP}", params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []

        places: list[WellnessPlace] = []
        for item in _extract_items(data):
            content_id = str(item.get("contentid", "") or item.get("contentId", ""))
            title = str(item.get("title", ""))
            addr = str(item.get("addr1", "") or item.get("addr", ""))
            lat = _safe_float(item.get("mapy") or item.get("lat"))
            lng = _safe_float(item.get("mapx") or item.get("lng"))
            if not content_id or lat == 0.0 or lng == 0.0:
                continue
            places.append(WellnessPlace(
                content_id=content_id,
                title=title,
                addr=addr,
                lat=lat,
                lng=lng,
                cat1=str(item.get("cat1", "")),
                cat2=str(item.get("cat2", "")),
                cat3=str(item.get("cat3", "")),
            ))
        return places

    async def fetch_all(self, num_of_rows: int = 100) -> list[WellnessPlace]:
        """전체 웰니스 관광 목록 조회 (페이지 순회)."""
        results: list[WellnessPlace] = []
        page = 1
        while True:
            page_items = await self.fetch_page(page_no=page, num_of_rows=num_of_rows)
            if not page_items:
                break
            results.extend(page_items)
            if len(page_items) < num_of_rows:
                break
            page += 1
        return results
