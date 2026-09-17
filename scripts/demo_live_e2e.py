"""라이브 E2E 데모: 로컬 근거 카탈로그와 실제 Claude API를 점검한다."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from src.data.evidence_retriever import LocalEvidenceRetriever
from src.data.models import DayPlan, HardFail, ItineraryPlan, PlaceInput
from src.explain.explain_engine import ExplainEngine

POI_NAME = "오설록티뮤지엄"


def main() -> None:
    catalog = LocalEvidenceRetriever.from_settings()
    engine = ExplainEngine(graph_retriever=catalog)

    print(f"[1/3] 로컬 근거 카탈로그: {'OK' if catalog.enabled else 'FAIL'}")
    print(f"[1/3] Claude API: {'OK' if engine.is_available() else 'FAIL'}")
    if not catalog.enabled:
        raise RuntimeError("로컬 근거 카탈로그를 사용할 수 없습니다.")
    if not engine.is_available():
        raise RuntimeError("ANTHROPIC_API_KEY를 설정해야 합니다.")

    places = catalog.search_places(POI_NAME, limit=1)
    if not places:
        raise RuntimeError(f"근거 카탈로그에 '{POI_NAME}'이 없습니다.")
    place = places[0]
    nearby = catalog.find_nearby(place.place_id, limit=3)
    print(f"[2/3] {place.name} ({place.region_name}, {place.category_name})")
    print("  인근 대안:", ", ".join(item.name for item in nearby) or "없음")

    plan = ItineraryPlan(
        days=[DayPlan(places=[PlaceInput(name=POI_NAME), PlaceInput(name="카멜리아힐")])],
        party_size=2,
        party_type="연인",
        date="2026-06-01",
    )
    hard_fail = HardFail(
        fail_type="OPERATING_HOURS_CONFLICT",
        message=f"{POI_NAME} 도착 예정 18:30, 마감 18:00",
        evidence="도착 18:30 마감 18:00",
        confidence="High",
        poi_name=POI_NAME,
    )
    explanations = engine.generate(
        hard_fails=[hard_fail],
        warnings=[],
        penalty_breakdown={},
        bonus_breakdown={},
        scores=None,
        plan=plan,
        final_score=45,
    )
    if not explanations:
        raise RuntimeError("Claude가 explanation을 반환하지 않았습니다.")
    print(f"[3/3] Claude 응답: {len(explanations)}건")
    for item in explanations:
        print(f" - [{item.item_type}/{item.risk}] {item.fact}")


if __name__ == "__main__":
    main()
