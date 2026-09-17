"""TourAPI runtime adapter tests."""

from src.data.models import POI
from src.data.tour_api import TourAPIClient


def test_search_poi_sync_adapts_async_client(monkeypatch):
    client = TourAPIClient(api_key="test-key")
    expected = [
        POI(
            poi_id="1",
            name="테스트 관광지",
            lat=33.5,
            lng=126.5,
            open_start="09:00",
            open_end="18:00",
            duration_min=60,
            category="12",
        )
    ]

    async def fake_search(keyword: str, content_type_id=None, num_of_rows=10):
        return expected

    monkeypatch.setattr(client, "search_poi", fake_search)
    assert client.search_poi_sync("테스트") == expected
