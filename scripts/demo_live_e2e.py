"""라이브 E2E 데모 — 실제 Claude API + 실제 Neo4j Aura를 동시에 호출한다.

mock 없음. .env의 ANTHROPIC_API_KEY / NEO4J_* 로 각각 실제 서비스에 접속해
제주 Hard Fail 1건을 ExplainEngine에 넣고, Aura 그래프에서 찾은 근거(지역·
도보권 대안)가 Claude 응답에 실제로 반영되는지 눈으로 확인한다.

Usage:
    python scripts/demo_live_e2e.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from src.data.graph_retriever import GraphRetriever
from src.data.models import DayPlan, HardFail, ItineraryPlan, PlaceInput
from src.explain.explain_engine import ExplainEngine

POI_NAME = "오설록티뮤지엄"


def main() -> None:
    graph = GraphRetriever.from_env()
    engine = ExplainEngine(graph_retriever=graph)

    print(f"[1/3] Neo4j Aura 연결: {'OK' if graph.enabled else 'FAIL — NEO4J_* .env 확인'}")
    print(f"[1/3] Claude API 연결: {'OK' if engine.is_available() else 'FAIL — ANTHROPIC_API_KEY .env 확인'}")
    assert graph.enabled, "Aura 미연결 — .env NEO4J_URI/USERNAME/PASSWORD 필요"
    assert engine.is_available(), "Claude 미연결 — .env ANTHROPIC_API_KEY 필요"

    places = graph.search_places(POI_NAME, limit=1)
    assert places, f"Aura 그래프에 '{POI_NAME}' 없음 — scripts/load_knowledge_graph_neo4j.py 적재 확인"
    place = places[0]
    nearby = graph.find_nearby(place.place_id, limit=3)
    print(f"\n[2/3] Aura 조회 결과: {place.name} ({place.region_name}, {place.category_name})")
    for alt in nearby:
        print(f"       도보권 대안: {alt.name} ({alt.distance_km}km)")

    plan = ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=POI_NAME), PlaceInput(name="카멜리아힐")])],
        party_size=2, party_type="연인", date="2026-06-01",
    )
    hard_fail = HardFail(
        fail_type="OPERATING_HOURS_CONFLICT",
        message=f"{POI_NAME} 도착 예정 18:30, 마감 18:00",
        evidence="도착 18:30 > 마감 18:00",
        confidence="High",
        poi_name=POI_NAME,
    )

    explanations = engine.generate(
        hard_fails=[hard_fail], warnings=[], penalty_breakdown={}, bonus_breakdown={},
        scores=None, plan=plan, final_score=45,
    )
    assert explanations, "Claude가 explanation을 반환하지 않음"

    print(f"\n[3/3] Claude 응답 ({len(explanations)}건):")
    for item in explanations:
        print(f"  - [{item.item_type}/{item.risk}] {item.fact}")
        print(f"    근거: {item.rule}")
        print(f"    제안: {item.suggestion}")

    grounded = any(
        place.region_name and place.region_name in (item.fact + item.rule + item.suggestion)
        for item in explanations
    )
    print(f"\n그래프 근거({place.region_name}) Claude 응답 반영: {'YES' if grounded else 'no (LLM이 문구를 바꿔 표현했을 수 있음)'}")

    graph.close()


if __name__ == "__main__":
    main()
