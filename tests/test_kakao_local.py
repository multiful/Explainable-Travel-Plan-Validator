"""KakaoLocalClient 테스트 (실제 API 호출 X — 모두 mock)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.data.kakao_local import KakaoLocalClient
from src.data.models import KakaoPlace


def _ok_response() -> MagicMock:
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = {
        "documents": [
            {
                "place_name": "개성만두 궁",
                "x": "126.9701",
                "y": "37.5725",
                "category_name": "음식점 > 한식 > 만두",
                "road_address_name": "서울 종로구 ...",
                "phone": "02-000-0000",
                "place_url": "http://place.map.kakao.com/1",
            }
        ]
    }
    return m


def test_disabled_without_key_returns_none() -> None:
    client = KakaoLocalClient(api_key="")
    assert client.enabled is False
    assert client.search_keyword("개성만두 궁") is None


def test_search_parses_first_document() -> None:
    client = KakaoLocalClient(api_key="dummy")
    with patch("src.data.kakao_local.httpx.get", return_value=_ok_response()) as g:
        place = client.search_keyword("개성만두 궁")
        assert g.called
    assert isinstance(place, KakaoPlace)
    assert place.lat == 37.5725
    assert place.lng == 126.9701
    assert "음식점" in place.category_name


def test_result_is_cached() -> None:
    client = KakaoLocalClient(api_key="dummy")
    with patch("src.data.kakao_local.httpx.get", return_value=_ok_response()) as g:
        client.search_keyword("개성만두 궁")
        client.search_keyword("개성만두 궁")
        assert g.call_count == 1  # 두 번째는 캐시 hit
    assert client.stats["hit"] == 1


def test_empty_documents_returns_none() -> None:
    client = KakaoLocalClient(api_key="dummy")
    empty = MagicMock()
    empty.raise_for_status.return_value = None
    empty.json.return_value = {"documents": []}
    with patch("src.data.kakao_local.httpx.get", return_value=empty):
        assert client.search_keyword("존재하지않는장소") is None


def test_http_error_falls_back_to_none() -> None:
    import httpx

    client = KakaoLocalClient(api_key="dummy")
    with patch("src.data.kakao_local.httpx.get", side_effect=httpx.ConnectTimeout("x")):
        assert client.search_keyword("개성만두 궁") is None
    assert client.stats["api_fail"] == 1
