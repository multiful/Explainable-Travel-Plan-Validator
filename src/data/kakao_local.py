"""카카오 로컬 키워드 장소 검색 클라이언트 (httpx + Graceful Fallback).

식당·카페 등 TourAPI POI(`pois.csv`)에 없는 임의 장소의 좌표·카테고리·주소를
같은 KAKAO_REST_API_KEY 로 조회한다. 키가 없거나 호출 실패 시 None 을 반환해
상위 resolver 가 기존 폴백(서울시청 좌표)으로 자연스럽게 떨어지도록 한다.

CLAUDE.md 규칙:
  - 외부 I/O 는 data 레이어에서만 처리한다.
  - 키는 환경변수로만 관리한다.
  - 모듈 간 데이터는 Pydantic 모델(KakaoPlace)로 주고받는다.
"""
from __future__ import annotations

import os

import httpx

from src.data.models import KakaoPlace

_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class KakaoLocalClient:
    """카카오 로컬 키워드 검색. 인메모리 캐시로 동일 질의 중복 호출을 막는다."""

    def __init__(self, api_key: str | None = None, timeout_sec: float = 3.0) -> None:
        self._api_key = (api_key or "").strip()
        self._timeout = timeout_sec
        self._cache: dict[str, KakaoPlace | None] = {}
        self.stats: dict[str, int] = {"hit": 0, "miss": 0, "api_ok": 0, "api_fail": 0}

    @classmethod
    def from_env(cls) -> KakaoLocalClient:
        return cls(api_key=os.environ.get("KAKAO_REST_API_KEY", ""))

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def search_keyword(self, query: str) -> KakaoPlace | None:
        """장소명으로 가장 관련도 높은 1건을 조회. 실패 시 None."""
        q = (query or "").strip()
        if not q or not self.enabled:
            return None
        if q in self._cache:
            self.stats["hit"] += 1
            return self._cache[q]

        self.stats["miss"] += 1
        result: KakaoPlace | None = None
        try:
            resp = httpx.get(
                _KEYWORD_URL,
                params={"query": q, "size": 1},
                headers={"Authorization": f"KakaoAK {self._api_key}"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            docs = resp.json().get("documents", [])
            if docs:
                d = docs[0]
                result = KakaoPlace(
                    name=d.get("place_name", q),
                    lat=float(d["y"]),
                    lng=float(d["x"]),
                    category_name=d.get("category_name", ""),
                    address=d.get("road_address_name") or d.get("address_name", ""),
                    phone=d.get("phone", ""),
                    place_url=d.get("place_url", ""),
                )
            self.stats["api_ok"] += 1
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            self.stats["api_fail"] += 1
            result = None

        self._cache[q] = result
        return result
