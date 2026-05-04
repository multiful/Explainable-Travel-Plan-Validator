"""한국관광공사 무장애 여행 정보 API 클라이언트 (B551011/KorWithService2).

오퍼레이션:
  areaBasedList2   — 지역기반 관광정보 목록 조회 (좌표 포함)
  detailWithTour2  — 무장애여행 상세정보 조회 (접근성 세부 항목)

참고: 한국관광공사_개방데이터_활용매뉴얼(무장애여행)_v4.3
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from src.data.models import Settings

_BASE_URL = "https://apis.data.go.kr/B551011/KorWithService2"
_LIST_OP = "areaBasedList2"       # 지역기반 목록 조회
_DETAIL_OP = "detailWithTour2"    # 무장애여행 상세 조회


@dataclass(frozen=True)
class BarrierFreePlace:
    """areaBasedList2 기반 기본 POI + detailWithTour2 접근성 세부 항목."""
    content_id: str
    title: str
    addr: str
    lat: float    # mapy (WGS84 위도)
    lng: float    # mapx (WGS84 경도)
    # ── detailWithTour2 지체장애 항목 (선택 보강) ──────────────────
    wheelchair: str = ""    # 휠체어 대여/접근 여부 (텍스트, 예: "대여가능(수동휠체어 2대)")
    elevator: str = ""      # 엘리베이터 여부 (텍스트)
    parking: str = ""       # 장애인 주차 여부 (텍스트)
    # ── detailWithTour2 영유아가족 항목 ─────────────────────────────
    stroller: str = ""      # 유모차 여부 (텍스트)
    lactation_room: str = ""  # 수유실 여부 (텍스트)
    # ── detailWithTour2 시각장애 항목 ───────────────────────────────
    help_dog: str = ""      # 보조견 동반 여부 (텍스트)


@dataclass(frozen=True)
class BarrierFreeDetail:
    """detailWithTour2 응답 전체 필드 (필요 시 개별 조회용)."""
    content_id: str
    # 지체장애
    parking: str = ""
    public_transport: str = ""
    route: str = ""
    wheelchair: str = ""
    exit: str = ""
    elevator: str = ""
    restroom: str = ""
    # 시각장애
    braile_block: str = ""
    help_dog: str = ""
    guide_human: str = ""
    audio_guide: str = ""
    # 청각장애
    sign_guide: str = ""
    video_guide: str = ""
    # 영유아가족
    stroller: str = ""
    lactation_room: str = ""
    baby_spare_chair: str = ""


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


def _str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


class BarrierFreeAPIClient:
    """무장애 여행 정보 API — 비동기 클라이언트.

    Graceful Fallback: API 호출 실패 시 빈 리스트/None 반환.
    """

    def __init__(self, api_key: str, timeout_sec: float = 10.0) -> None:
        if not api_key:
            raise ValueError("barrier_free_api_key 없음. .env에 BARRIER_FREE_API_KEY를 설정하세요.")
        self._key = api_key
        self._timeout = timeout_sec

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "BarrierFreeAPIClient | None":
        if settings is None:
            settings = Settings()
        key = settings.barrier_free_api_key
        if not key:
            return None
        return cls(api_key=key)

    async def fetch_page(
        self,
        page_no: int = 1,
        num_of_rows: int = 100,
        area_code: str = "",
        content_type_id: str = "",
    ) -> list[BarrierFreePlace]:
        """areaBasedList2 — 무장애 여행 POI 목록 한 페이지 조회.

        반환 필드: contentid, title, addr1, mapx, mapy, cat1/2/3, sigungucode 등
        접근성 세부 항목(wheelchair, stroller 등)은 fetch_detail() 로 별도 조회.
        """
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
        if content_type_id:
            params["contentTypeId"] = content_type_id

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{_BASE_URL}/{_LIST_OP}", params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []

        places: list[BarrierFreePlace] = []
        for item in _extract_items(data):
            content_id = _str(item.get("contentid") or item.get("contentId"))
            title = _str(item.get("title"))
            addr = _str(item.get("addr1") or item.get("addr2"))
            lat = _safe_float(item.get("mapy") or item.get("lat"))
            lng = _safe_float(item.get("mapx") or item.get("lng"))
            if not content_id or lat == 0.0 or lng == 0.0:
                continue
            places.append(BarrierFreePlace(
                content_id=content_id,
                title=title,
                addr=addr,
                lat=lat,
                lng=lng,
            ))
        return places

    async def fetch_detail(self, content_id: str) -> BarrierFreeDetail | None:
        """detailWithTour2 — 단일 콘텐츠 무장애 접근성 상세 조회.

        지체장애·시각장애·청각장애·영유아가족 항목을 텍스트로 반환.
        build_poi_dataset.py 에서 좌표 외 접근성 세부 정보 보강 시 사용.
        """
        params: dict[str, Any] = {
            "serviceKey": self._key,
            "numOfRows": 1,
            "pageNo": 1,
            "MobileOS": "ETC",
            "MobileApp": "TravelQA",
            "_type": "json",
            "contentId": content_id,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{_BASE_URL}/{_DETAIL_OP}", params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None

        items = _extract_items(data)
        if not items:
            return None
        item = items[0]
        return BarrierFreeDetail(
            content_id=_str(item.get("contentid")),
            parking=_str(item.get("parking")),
            public_transport=_str(item.get("publictransport")),
            route=_str(item.get("route")),
            wheelchair=_str(item.get("wheelchair")),
            exit=_str(item.get("exit")),
            elevator=_str(item.get("elevator")),
            restroom=_str(item.get("restroom")),
            braile_block=_str(item.get("braileblock")),
            help_dog=_str(item.get("helpdog")),
            guide_human=_str(item.get("guidehuman")),
            audio_guide=_str(item.get("audioguide")),
            sign_guide=_str(item.get("signguide")),
            video_guide=_str(item.get("videoguide")),
            stroller=_str(item.get("stroller")),
            lactation_room=_str(item.get("lactationroom")),
            baby_spare_chair=_str(item.get("babysparechair")),
        )

    async def fetch_all(self, num_of_rows: int = 100) -> list[BarrierFreePlace]:
        """전체 무장애 여행 POI 목록 조회 (페이지 순회, areaBasedList2)."""
        results: list[BarrierFreePlace] = []
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
