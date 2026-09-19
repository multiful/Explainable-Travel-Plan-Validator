"""외부 장소 resolver의 호출 우선순위와 정규화 테스트."""

from src.data.models import POI, KakaoPlace
from src.data.place_resolver import ExternalPlaceResolver


def test_resolver_prefers_tour_api_and_returns_pydantic_model():
    tour_poi = POI(
        poi_id="tour-1",
        name="테스트 관광지",
        lat=35.1,
        lng=129.0,
        open_start="10:00",
        open_end="19:00",
        duration_min=60,
        category="14",
    )

    class FakeTourAPI:
        def search_poi_sync(self, keyword, num_of_rows=10):
            assert keyword == "테스트관광지"
            assert num_of_rows == 5
            return [tour_poi]

    class FakeKakao:
        def search_keyword(self, _query):
            raise AssertionError("TourAPI 결과가 있으면 Kakao를 호출하지 않아야 한다")

    resolver = ExternalPlaceResolver(FakeKakao(), FakeTourAPI())
    result = resolver.resolve("테스트관광지", allow_tour_api=True)

    assert result is not None
    assert result.source == "tour_api"
    assert (result.lat, result.lng) == (35.1, 129.0)
    assert (result.open_start, result.open_end) == ("10:00", "19:00")


def test_resolver_falls_back_to_kakao_then_geocode():
    class FakeKakao:
        def search_keyword(self, _query):
            return KakaoPlace(
                name="카카오 장소",
                lat=35.2,
                lng=129.1,
                category_name="음식점 > 한식",
            )

        def geocode_address(self, _address):
            raise AssertionError("Kakao 키워드 결과가 있으면 지오코딩하지 않아야 한다")

    result = ExternalPlaceResolver(FakeKakao(), None).resolve("카카오 장소")

    assert result is not None
    assert result.source == "kakao"
    assert result.category_name == "음식점 > 한식"
