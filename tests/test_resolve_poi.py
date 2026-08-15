"""_resolve_poi() 좌표 해석 폴백 순서 테스트 (카탈로그 → csv → kakao 키워드 → 지오코딩 → 서울 폴백)."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import router
from src.api.main import app


def test_geocode_fallback_used_when_keyword_search_fails():
    """카카오 키워드 검색이 실패해도 주소가 있으면 지오코딩으로 좌표를 보강한다."""
    with (
        patch.object(router._KAKAO_LOCAL, "search_keyword", return_value=None),
        patch.object(router._KAKAO_LOCAL, "geocode_address", return_value=(33.546, 126.688)),
    ):
        poi, info = router._resolve_poi(
            "존재하지않는장소12345", 0, address="제주특별자치도 제주시 조천읍 북촌3길 3"
        )

    assert info.source == "geocode"
    assert info.confidence == "Medium"
    assert poi.lat == 33.546
    assert poi.lng == 126.688


def test_seoul_fallback_when_geocode_also_fails():
    """지오코딩까지 실패하면 기존과 동일하게 서울 폴백으로 떨어진다."""
    with (
        patch.object(router._KAKAO_LOCAL, "search_keyword", return_value=None),
        patch.object(router._KAKAO_LOCAL, "geocode_address", return_value=None),
    ):
        poi, info = router._resolve_poi("존재하지않는장소12345", 0, address="이상한주소")

    assert info.source == "fallback"
    assert info.confidence == "Low"
    assert (poi.lat, poi.lng) == router._DEFAULT_CENTER


def test_resolve_coords_endpoint_returns_poi_per_place():
    """POST /api/resolve-coords — Step2 빌더 지도용 좌표 조회 (검증 파이프라인 없이 좌표만)."""
    client = TestClient(app)
    with (
        patch.object(router._KAKAO_LOCAL, "search_keyword", return_value=None),
        patch.object(router._KAKAO_LOCAL, "geocode_address", return_value=(33.5, 126.9)),
    ):
        res = client.post(
            "/api/resolve-coords",
            json={"places": [{"name": "존재하지않는장소12345", "address": "제주 어딘가"}]},
        )

    assert res.status_code == 200
    pois = res.json()
    assert len(pois) == 1
    assert pois[0]["name"] == "존재하지않는장소12345"
    assert (pois[0]["lat"], pois[0]["lng"]) == (33.5, 126.9)
