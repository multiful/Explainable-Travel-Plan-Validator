"""_resolve_poi() 좌표 해석 폴백 순서 테스트 (카탈로그 → csv → kakao 키워드 → 지오코딩 → 서울 폴백)."""
from __future__ import annotations

from unittest.mock import patch

import openpyxl
import pytest
from fastapi.testclient import TestClient

from src.api import router
from src.api.main import app

_XLSX_HEADER = [
    "상호명", "도로명주소", "위도", "경도", "대분류코드", "대분류명", "영업시간",
    "TourAPI_contentid", "TourAPI_영업시간", "반려동물동반",
]


def _write_jeju_xlsx(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_XLSX_HEADER)
    for row in rows:
        ws.append([row.get(col, "") for col in _XLSX_HEADER])
    wb.save(path)


@pytest.fixture
def jeju_xlsx_index(tmp_path, monkeypatch):
    """data/제주특별자치도_통합_TourAPI병합.xlsx 를 임시 파일로 대체해 _build_jeju_place_index()를 격리 실행."""
    _write_jeju_xlsx(
        tmp_path / "제주특별자치도_통합_TourAPI병합.xlsx",
        [
            {  # TourAPI 매칭 성공 — 실측 영업시간·contentid 우선 사용, 반려동물 동반 가능
                "상호명": "제주아트센터", "도로명주소": "제주시 어딘가", "위도": "33.4", "경도": "126.5",
                "대분류코드": "VE", "대분류명": "문화관광",
                "영업시간": "10:00~19:00", "TourAPI_contentid": 1755806,
                "TourAPI_영업시간": "09:30~18:30 (휴게 12:00~13:00)", "반려동물동반": "Y",
            },
            {  # TourAPI 미매칭 — 기존 영업시간 원문 텍스트로 폴백, 반려동물 동반 정보 없음
                "상호명": "클리프홀", "도로명주소": "서귀포시 어딘가", "위도": "33.38", "경도": "126.23",
                "대분류코드": "VE", "대분류명": "문화관광",
                "영업시간": "10:00~24:00", "TourAPI_contentid": "", "TourAPI_영업시간": "", "반려동물동반": "",
            },
        ],
    )
    monkeypatch.setattr(router, "_DATA_DIR", tmp_path)
    return router._build_jeju_place_index()


def test_jeju_index_prefers_tourapi_hours_over_legacy_text(jeju_xlsx_index):
    entry = jeju_xlsx_index[router._normalize("제주아트센터")]
    assert (entry["open_start"], entry["open_end"]) == ("09:30", "18:30")


def test_jeju_index_sets_contentid_when_tourapi_matched(jeju_xlsx_index):
    entry = jeju_xlsx_index[router._normalize("제주아트센터")]
    assert entry["contentid"] == "1755806"


def test_jeju_index_falls_back_to_legacy_hours_when_unmatched(jeju_xlsx_index):
    entry = jeju_xlsx_index[router._normalize("클리프홀")]
    assert (entry["open_start"], entry["open_end"]) == ("10:00", "24:00")
    assert "contentid" not in entry


def test_jeju_index_sets_pet_friendly_flag_when_y(jeju_xlsx_index):
    entry = jeju_xlsx_index[router._normalize("제주아트센터")]
    assert entry["pet_friendly"] is True


def test_jeju_index_defaults_pet_friendly_false_when_blank(jeju_xlsx_index):
    entry = jeju_xlsx_index[router._normalize("클리프홀")]
    assert entry.get("pet_friendly", False) is False


def test_resolve_poi_propagates_pet_friendly_flag(monkeypatch):
    """_resolve_poi()가 place dict의 pet_friendly 속성을 POI·POIInfo로 전달한다."""
    monkeypatch.setitem(
        router._JEJU_CSV_INDEX,
        router._normalize("반려동반테스트장소"),
        {
            "name": "반려동반테스트장소", "lat": 33.4, "lng": 126.5,
            "region": "제주", "cat": "12", "cat_name": "관광지",
            "addr": "", "has_coords": True, "source": "jeju_csv",
            "pet_friendly": True,
        },
    )
    poi, info = router._resolve_poi("반려동반테스트장소", 0)
    assert poi.pet_friendly is True
    assert info.pet_friendly is True


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
