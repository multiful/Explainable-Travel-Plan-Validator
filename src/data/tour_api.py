"""한국관광공사 TourAPI v2 비동기 클라이언트 (httpx + Graceful Fallback)."""
from __future__ import annotations

import re
from typing import Any

import httpx

from src.data.models import POI, Settings

_BASE_URL = "https://apis.data.go.kr/B551011/KorService2"
_FALLBACK_OPEN = "00:00"
_FALLBACK_CLOSE = "23:59"

_USETIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[~\-～]\s*(\d{1,2}):(\d{2})")


def _parse_usetime(usetime: str) -> tuple[str, str]:
    """'09:00 ~ 18:00' 형태에서 (open, close) 파싱. 실패 시 폴백."""
    m = _USETIME_RE.search(usetime or "")
    if not m:
        return _FALLBACK_OPEN, _FALLBACK_CLOSE
    h1, m1, h2, m2 = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"{int(h1):02d}:{m1}", f"{int(h2):02d}:{m2}"


def _extract_items(data: dict) -> list[dict]:
    """TourAPI 응답 JSON에서 item 리스트 추출."""
    try:
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            return [items]
        return list(items)
    except (KeyError, TypeError):
        return []


class TourAPIClient:
    """한국관광공사 TourAPI v2 비동기 클라이언트.

    모든 호출은 실패 시 Graceful Fallback:
    - search_poi → 빈 리스트
    - get_operating_hours → ("00:00", "23:59")

    캐시: content_id별 in-memory 캐시로 반복 detailIntro 호출 방지.
    """

    def __init__(
        self,
        api_key: str,
        timeout_sec: float = 5.0,
        mobile_app: str = "TravelQA",
    ) -> None:
        if not api_key:
            raise ValueError("TourAPI 키 없음. .env에 TOUR_API_KEY를 설정하세요.")
        self._key = api_key
        self._timeout = timeout_sec
        self._mobile_app = mobile_app
        self._hours_cache: dict[str, tuple[str, str]] = {}

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "TourAPIClient | None":
        """Settings에서 키 로드. 키 없으면 None 반환 (Graceful Fallback 진입점)."""
        if settings is None:
            settings = Settings()
        if not settings.tour_api_key:
            return None
        return cls(api_key=settings.tour_api_key)

    async def search_poi(
        self,
        keyword: str,
        content_type_id: int | None = None,
        num_of_rows: int = 10,
    ) -> list[POI]:
        """키워드로 POI 검색. 실패 시 빈 리스트 반환."""
        params: dict[str, Any] = {
            "serviceKey": self._key,
            "numOfRows":  num_of_rows,
            "pageNo":     1,
            "MobileOS":   "ETC",
            "MobileApp":  self._mobile_app,
            "arrange":    "A",
            "keyword":    keyword,
            "_type":      "json",
        }
        if content_type_id is not None:
            params["contentTypeId"] = content_type_id

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(f"{_BASE_URL}/searchKeyword2", params=params)
            if r.status_code != 200:
                return []
            items = _extract_items(r.json())
        except Exception:
            return []

        pois: list[POI] = []
        for item in items:
            try:
                content_id = str(item.get("contentid", ""))
                ctype = int(item.get("contenttypeid", 12))
                lat = float(item.get("mapy", 0) or 0)
                lng = float(item.get("mapx", 0) or 0)
                if not lat or not lng:
                    continue
                open_s, close_s = await self.get_operating_hours(content_id, ctype)
                pois.append(POI(
                    poi_id=content_id,
                    name=str(item.get("title", keyword)),
                    lat=lat,
                    lng=lng,
                    open_start=open_s,
                    open_end=close_s,
                    duration_min=60,
                    category=str(ctype),
                ))
            except Exception:
                continue
        return pois

    async def get_operating_hours(
        self,
        content_id: str,
        content_type_id: int,
    ) -> tuple[str, str]:
        """운영시간 조회. 실패 또는 데이터 없으면 ("00:00", "23:59") 반환."""
        if content_id in self._hours_cache:
            return self._hours_cache[content_id]

        params: dict[str, Any] = {
            "serviceKey":    self._key,
            "contentId":     content_id,
            "contentTypeId": content_type_id,
            "MobileOS":      "ETC",
            "MobileApp":     self._mobile_app,
            "_type":         "json",
        }

        result = (_FALLBACK_OPEN, _FALLBACK_CLOSE)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(f"{_BASE_URL}/detailIntro2", params=params)
            if r.status_code == 200:
                items = _extract_items(r.json())
                if items:
                    usetime = str(items[0].get("usetime", "") or "")
                    if usetime:
                        result = _parse_usetime(usetime)
        except Exception:
            pass

        self._hours_cache[content_id] = result
        return result

    def clear_cache(self) -> None:
        self._hours_cache.clear()
