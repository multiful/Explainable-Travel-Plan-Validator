"""Neo4j 지식그래프 리트리버 — Place/Region/NEAR_BY 그래프에서 근거 조회.

scripts/build_knowledge_graph.py + scripts/load_knowledge_graph_neo4j.py로 적재한
제주도 그래프(Aura)에서 장소명으로 검색하고, 도보 근접 대체 후보를 조회한다.
explain 엔진이 답변에 인용할 그라운딩 소스.

CLAUDE.md 규칙:
  - 외부 I/O는 data 레이어에서만 처리한다.
  - 키는 환경변수로만 관리한다.
  - 모듈 간 데이터는 Pydantic 모델(PlaceEvidence, AlternativePOI)로만 주고받는다.
"""
from __future__ import annotations

import os
import time

from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from src.data.models import AlternativePOI, PlaceEvidence

_UNREACHABLE_COOLDOWN_SEC = 60.0

_SEARCH_CYPHER = """
MATCH (p:Place)
WHERE toLower(p.name) CONTAINS toLower($q)
OPTIONAL MATCH (p)-[:IS_LOCATED_IN]->(r:Region)
RETURN p.id AS id, p.name AS name, p.place_type AS place_type,
       p.category_medium_name AS category_name, p.address AS address,
       p.lat AS lat, p.lng AS lng, r.name AS region_name
ORDER BY toLower(p.name) <> toLower($q), size(p.name)
LIMIT $limit
"""

_NEARBY_CYPHER = """
MATCH (p:Place {id: $place_id})-[rel:NEAR_BY]->(n:Place)
RETURN n.name AS name, n.category_medium_name AS category,
       n.lat AS lat, n.lng AS lng, rel.distance_m AS distance_m
ORDER BY rel.distance_m
LIMIT $limit
"""


class GraphRetriever:
    """제주 지식그래프(Neo4j Aura) 리트리버. 미설정/연결 실패 시 빈 결과로 폴백."""

    def __init__(self, uri: str, username: str, password: str, database: str = "neo4j") -> None:
        self._database = database
        self._driver = (
            GraphDatabase.driver(
                uri,
                auth=(username, password),
                connection_timeout=5.0,
                max_transaction_retry_time=5.0,
            )
            if uri
            else None
        )
        self._unreachable_until = 0.0

    @classmethod
    def from_env(cls) -> GraphRetriever:
        return cls(
            uri=os.environ.get("NEO4J_URI", ""),
            username=os.environ.get("NEO4J_USERNAME", ""),
            password=os.environ.get("NEO4J_PASSWORD", ""),
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
        )

    @property
    def enabled(self) -> bool:
        return self._driver is not None

    def _callable(self) -> bool:
        """호출 가능 여부. 최근 연결 실패 시 쿨다운 동안 재시도 백오프 비용 없이 즉시 빈 결과로 넘긴다."""
        return self.enabled and time.monotonic() >= self._unreachable_until

    def _mark_unreachable(self) -> None:
        self._unreachable_until = time.monotonic() + _UNREACHABLE_COOLDOWN_SEC

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

    def search_places(self, query: str, limit: int = 5) -> list[PlaceEvidence]:
        """장소명 부분일치 검색 — Region 컨텍스트 포함."""
        q = (query or "").strip()
        if not q or not self._callable():
            return []
        try:
            result = self._driver.execute_query(
                _SEARCH_CYPHER, q=q, limit=limit, database_=self._database
            )
        except (Neo4jError, DriverError):
            self._mark_unreachable()
            return []
        return [
            PlaceEvidence(
                place_id=rec["id"],
                name=rec["name"],
                place_type=rec["place_type"] or "",
                category_name=rec["category_name"] or "",
                region_name=rec["region_name"] or "",
                address=rec["address"] or "",
                lat=rec["lat"],
                lng=rec["lng"],
            )
            for rec in result.records
        ]

    def find_nearby(self, place_id: str, limit: int = 5) -> list[AlternativePOI]:
        """NEAR_BY 그래프에서 도보 근접 대체 후보 조회 (거리순)."""
        if not place_id or not self._callable():
            return []
        try:
            result = self._driver.execute_query(
                _NEARBY_CYPHER, place_id=place_id, limit=limit, database_=self._database
            )
        except (Neo4jError, DriverError):
            self._mark_unreachable()
            return []
        return [
            AlternativePOI(
                name=rec["name"],
                distance_km=round(rec["distance_m"] / 1000, 3),
                category=rec["category"] or "",
                lat=rec["lat"],
                lng=rec["lng"],
            )
            for rec in result.records
        ]
