"""로컬 장소 근거 리트리버 테스트."""

from pathlib import Path

from src.data.evidence_retriever import LocalEvidenceRetriever
from src.data.models import AlternativePOI, PlaceEvidence


def _catalog(tmp_path: Path) -> Path:
    path = tmp_path / "places.csv"
    path.write_text(
        "ID,대분류,상호명,도로명주소,위도,경도,중분류명\n"
        "1,관광지,성산일출봉,제주특별자치도 서귀포시 성산읍,33.458,126.942,자연관광지\n"
        "2,관광지,섭지코지,제주특별자치도 서귀포시 성산읍,33.43,126.93,자연관광지\n",
        encoding="utf-8",
    )
    return path


def test_missing_catalog_is_disabled(tmp_path: Path) -> None:
    retriever = LocalEvidenceRetriever(tmp_path / "missing.csv")
    assert retriever.enabled is False
    assert retriever.search_places("성산일출봉") == []


def test_search_places_reads_local_catalog(tmp_path: Path) -> None:
    retriever = LocalEvidenceRetriever(_catalog(tmp_path))
    places = retriever.search_places("일출봉")
    assert len(places) == 1
    assert isinstance(places[0], PlaceEvidence)
    assert places[0].name == "성산일출봉"
    assert places[0].region_name == "제주특별자치도 서귀포시"


def test_find_nearby_returns_local_alternatives(tmp_path: Path) -> None:
    retriever = LocalEvidenceRetriever(_catalog(tmp_path))
    alternatives = retriever.find_nearby("1")
    assert len(alternatives) == 1
    assert isinstance(alternatives[0], AlternativePOI)
    assert alternatives[0].name == "섭지코지"
    assert alternatives[0].distance_km > 0
