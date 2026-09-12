"""로컬 장소 근거 리트리버.

검증 요청이 외부 그래프 서버에 의존하지 않도록 배포물의 장소 CSV를 인덱싱한다.
장소 검색과 좌표 기반 근접 대안 조회를 같은 데이터 레이어에서 제공한다.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.data.models import AlternativePOI, PlaceEvidence
from src.utils.geo import haversine_km

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CSV = _PROJECT_ROOT / "data" / "jeju_places.csv"


class LocalEvidenceRetriever:
    """장소명 검색과 근접 대안 조회를 제공하는 로컬 리트리버."""

    def __init__(self, catalog_path: str | Path | None = None) -> None:
        self._catalog_path = Path(catalog_path or _DEFAULT_CSV)
        self._places = self._load_places()
        self._by_id = {place.place_id: place for place in self._places}
        self.enabled = bool(self._places)

    def _load_places(self) -> list[PlaceEvidence]:
        if not self._catalog_path.exists():
            return []
        places: list[PlaceEvidence] = []
        try:
            with self._catalog_path.open(encoding="utf-8-sig", newline="") as file:
                for row in csv.DictReader(file):
                    try:
                        name = (row.get("상호명") or row.get("name") or "").strip()
                        if not name:
                            continue
                        address = (row.get("도로명주소") or row.get("address") or "").strip()
                        places.append(
                            PlaceEvidence(
                                place_id=(row.get("ID") or row.get("id") or name).strip(),
                                name=name,
                                place_type=(
                                    row.get("대분류") or row.get("place_type") or ""
                                ).strip(),
                                category_name=(
                                    row.get("중분류명") or row.get("카테고리") or ""
                                ).strip(),
                                region_name=" ".join(address.split()[:2]),
                                address=address,
                                lat=float(row.get("위도") or row.get("lat") or 0),
                                lng=float(row.get("경도") or row.get("lng") or 0),
                            )
                        )
                    except (TypeError, ValueError):
                        continue
        except (OSError, UnicodeError):
            return []
        return places

    @classmethod
    def from_settings(cls, catalog_path: str | Path | None = None) -> LocalEvidenceRetriever:
        """설정 기반 생성자. 외부 환경변수나 네트워크를 읽지 않는다."""
        return cls(catalog_path=catalog_path)

    def search_places(self, query: str, limit: int = 5) -> list[PlaceEvidence]:
        query = (query or "").strip().casefold()
        if not query or limit <= 0:
            return []
        matches = [place for place in self._places if query in place.name.casefold()]
        return sorted(
            matches,
            key=lambda place: (place.name.casefold() != query, len(place.name)),
        )[:limit]

    def find_nearby(self, place_id: str, limit: int = 5) -> list[AlternativePOI]:
        origin = self._by_id.get(place_id)
        if origin is None or limit <= 0:
            return []
        candidates = [place for place in self._places if place.place_id != place_id]
        candidates.sort(
            key=lambda place: haversine_km(origin.lat, origin.lng, place.lat, place.lng)
        )
        return [
            AlternativePOI(
                name=place.name,
                distance_km=round(haversine_km(origin.lat, origin.lng, place.lat, place.lng), 3),
                category=place.category_name,
                lat=place.lat,
                lng=place.lng,
            )
            for place in candidates[:limit]
        ]
