"""GraphRetriever 테스트 (실제 Neo4j 호출 X — 모두 mock)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from neo4j.exceptions import Neo4jError

from src.data.graph_retriever import GraphRetriever
from src.data.models import AlternativePOI, PlaceEvidence


def test_disabled_without_uri_returns_empty() -> None:
    retriever = GraphRetriever(uri="", username="", password="")
    assert retriever.enabled is False
    assert retriever.search_places("성산일출봉") == []
    assert retriever.find_nearby("kakao_1") == []


def test_search_places_parses_records() -> None:
    with patch("src.data.graph_retriever.GraphDatabase.driver", return_value=MagicMock()):
        retriever = GraphRetriever(uri="neo4j+s://x", username="u", password="p", database="db")
        fake_result = MagicMock()
        fake_result.records = [
            {
                "id": "kakao_1", "name": "성산일출봉", "place_type": "ACTIVITY",
                "category_name": "자연관광지", "address": "제주 서귀포시 ...",
                "lat": 33.458, "lng": 126.942, "region_name": "성산읍",
            }
        ]
        retriever._driver.execute_query.return_value = fake_result
        places = retriever.search_places("일출봉")

    assert len(places) == 1
    assert isinstance(places[0], PlaceEvidence)
    assert places[0].name == "성산일출봉"
    assert places[0].region_name == "성산읍"


def test_search_places_empty_query_skips_call() -> None:
    with patch("src.data.graph_retriever.GraphDatabase.driver", return_value=MagicMock()):
        retriever = GraphRetriever(uri="neo4j+s://x", username="u", password="p")
        assert retriever.search_places("   ") == []
        retriever._driver.execute_query.assert_not_called()


def test_search_places_neo4j_error_returns_empty() -> None:
    with patch("src.data.graph_retriever.GraphDatabase.driver", return_value=MagicMock()):
        retriever = GraphRetriever(uri="neo4j+s://x", username="u", password="p")
        retriever._driver.execute_query.side_effect = Neo4jError("boom")
        assert retriever.search_places("일출봉") == []


def test_find_nearby_parses_and_converts_distance() -> None:
    with patch("src.data.graph_retriever.GraphDatabase.driver", return_value=MagicMock()):
        retriever = GraphRetriever(uri="neo4j+s://x", username="u", password="p")
        fake_result = MagicMock()
        fake_result.records = [
            {"name": "우도", "category": "자연관광지", "lat": 33.5, "lng": 126.95, "distance_m": 250.0},
        ]
        retriever._driver.execute_query.return_value = fake_result
        alts = retriever.find_nearby("kakao_1")

    assert len(alts) == 1
    assert isinstance(alts[0], AlternativePOI)
    assert alts[0].distance_km == 0.25


def test_close_closes_driver() -> None:
    with patch("src.data.graph_retriever.GraphDatabase.driver", return_value=MagicMock()):
        retriever = GraphRetriever(uri="neo4j+s://x", username="u", password="p")
        retriever.close()
    retriever._driver.close.assert_called_once()


def test_from_env_reads_variables(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://x")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "db")
    with patch("src.data.graph_retriever.GraphDatabase.driver", return_value=MagicMock()) as create:
        retriever = GraphRetriever.from_env()

    create.assert_called_once_with("neo4j+s://x", auth=("u", "p"))
    assert retriever._database == "db"
