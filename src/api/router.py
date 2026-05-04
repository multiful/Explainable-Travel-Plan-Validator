"""FastAPI 라우터 — /validate, /places 엔드포인트."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    PlaceItem,
    PlacesResponse,
    POIInfo,
    ValidateRequest,
    ValidateResponse,
)
from src.data.dwell_db import MANUAL_OVERRIDES as _DWELL_OVERRIDES
from src.data.hours_db import resolve_hours
from src.data.models import DayPlan, ItineraryPlan, PlaceInput, POI
from src.explain.pipeline import ValidatorPipeline

router = APIRouter()

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DEFAULT_CENTER = (37.5665, 126.9780)  # 서울 시청

# ── sido 단축 매핑 ─────────────────────────────────────────────────────────
_SIDO_MAP: dict[str, str] = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
    "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원",
    "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남",
    "제주특별자치도": "제주",
}

# TourAPI type_label → category code
_TYPE_MAP: dict[str, str] = {
    "관광지": "12", "문화시설": "14", "레저스포츠": "28",
    "숙박": "32", "쇼핑": "38", "음식점": "39", "여행코스": "25",
}

# TourAPI contenttypeid → 한글 레이블
_TYPEID_LABEL: dict[str, str] = {
    "12": "관광지", "14": "문화시설", "15": "축제/행사",
    "25": "여행코스", "28": "레저스포츠", "32": "숙박",
    "38": "쇼핑", "39": "음식점",
}

# ── 하드코딩 좌표 DB (고품질 기준값) ──────────────────────────────────────
_COORD_CATALOG: dict[str, dict] = {
    "경복궁":         {"lat": 37.5796, "lng": 126.9770, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "창덕궁":         {"lat": 37.5793, "lng": 126.9910, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "덕수궁":         {"lat": 37.5658, "lng": 126.9752, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "창경궁":         {"lat": 37.5789, "lng": 126.9950, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "종묘":           {"lat": 37.5751, "lng": 126.9942, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "국립중앙박물관": {"lat": 37.5234, "lng": 126.9806, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "국립민속박물관": {"lat": 37.5820, "lng": 126.9790, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "국립현대미술관": {"lat": 37.5789, "lng": 126.9741, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "리움미술관":     {"lat": 37.5383, "lng": 126.9988, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "전쟁기념관":     {"lat": 37.5376, "lng": 126.9770, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "동대문디자인플라자": {"lat": 37.5669, "lng": 127.0091, "cat": "14", "region": "서울", "cat_name": "문화시설"},
    "한강공원":       {"lat": 37.5279, "lng": 126.9985, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "반포한강공원":   {"lat": 37.5069, "lng": 126.9943, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "여의도한강공원": {"lat": 37.5265, "lng": 126.9322, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "뚝섬한강공원":   {"lat": 37.5315, "lng": 127.0614, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "서울숲":         {"lat": 37.5445, "lng": 127.0374, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "남산공원":       {"lat": 37.5512, "lng": 126.9882, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "올림픽공원":     {"lat": 37.5220, "lng": 127.1217, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "북한산":         {"lat": 37.6589, "lng": 126.9764, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "관악산":         {"lat": 37.4443, "lng": 126.9634, "cat": "12", "region": "서울", "cat_name": "자연관광"},
    "남산타워":       {"lat": 37.5512, "lng": 126.9882, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "N서울타워":      {"lat": 37.5512, "lng": 126.9882, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "북촌한옥마을":   {"lat": 37.5826, "lng": 126.9830, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "서촌":           {"lat": 37.5809, "lng": 126.9690, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "광화문광장":     {"lat": 37.5720, "lng": 126.9768, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "청계천":         {"lat": 37.5695, "lng": 126.9784, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "63빌딩":         {"lat": 37.5198, "lng": 126.9407, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "롯데월드타워":   {"lat": 37.5126, "lng": 127.1026, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "익선동":         {"lat": 37.5755, "lng": 126.9999, "cat": "12", "region": "서울", "cat_name": "관광지"},
    "명동":           {"lat": 37.5636, "lng": 126.9838, "cat": "38", "region": "서울", "cat_name": "쇼핑"},
    "인사동":         {"lat": 37.5742, "lng": 126.9858, "cat": "38", "region": "서울", "cat_name": "쇼핑"},
    "동대문":         {"lat": 37.5660, "lng": 127.0098, "cat": "38", "region": "서울", "cat_name": "쇼핑"},
    "코엑스":         {"lat": 37.5115, "lng": 127.0596, "cat": "38", "region": "서울", "cat_name": "쇼핑"},
    "홍대":           {"lat": 37.5563, "lng": 126.9235, "cat": "39", "region": "서울", "cat_name": "음식/카페"},
    "이태원":         {"lat": 37.5347, "lng": 126.9940, "cat": "39", "region": "서울", "cat_name": "음식/카페"},
    "강남역":         {"lat": 37.4979, "lng": 127.0276, "cat": "39", "region": "서울", "cat_name": "음식/카페"},
    "성수동":         {"lat": 37.5444, "lng": 127.0558, "cat": "39", "region": "서울", "cat_name": "음식/카페"},
    "연남동":         {"lat": 37.5619, "lng": 126.9244, "cat": "39", "region": "서울", "cat_name": "음식/카페"},
    "망원동":         {"lat": 37.5555, "lng": 126.9094, "cat": "39", "region": "서울", "cat_name": "음식/카페"},
    "롯데월드":       {"lat": 37.5111, "lng": 127.0985, "cat": "15", "region": "서울", "cat_name": "테마파크"},
    "서울랜드":       {"lat": 37.4277, "lng": 127.0048, "cat": "15", "region": "서울", "cat_name": "테마파크"},
    "에버랜드":       {"lat": 37.2930, "lng": 127.2025, "cat": "15", "region": "경기", "cat_name": "테마파크"},
    "캐리비안베이":   {"lat": 37.2930, "lng": 127.2025, "cat": "15", "region": "경기", "cat_name": "테마파크"},
    "수원화성":       {"lat": 37.2871, "lng": 127.0145, "cat": "14", "region": "경기", "cat_name": "문화시설"},
    "해운대해수욕장": {"lat": 35.1586, "lng": 129.1603, "cat": "12", "region": "부산", "cat_name": "자연관광"},
    "광안리해수욕장": {"lat": 35.1531, "lng": 129.1191, "cat": "12", "region": "부산", "cat_name": "자연관광"},
    "감천문화마을":   {"lat": 35.0976, "lng": 129.0099, "cat": "12", "region": "부산", "cat_name": "관광지"},
    "태종대":         {"lat": 35.0456, "lng": 129.0845, "cat": "12", "region": "부산", "cat_name": "자연관광"},
    "용두산공원":     {"lat": 35.1007, "lng": 129.0324, "cat": "12", "region": "부산", "cat_name": "자연관광"},
    "자갈치시장":     {"lat": 35.0966, "lng": 129.0302, "cat": "38", "region": "부산", "cat_name": "쇼핑"},
    "BIFF광장":       {"lat": 35.0977, "lng": 129.0227, "cat": "12", "region": "부산", "cat_name": "관광지"},
    "센텀시티":       {"lat": 35.1693, "lng": 129.1323, "cat": "38", "region": "부산", "cat_name": "쇼핑"},
    "제주국제공항":   {"lat": 33.5104, "lng": 126.4926, "cat": "14", "region": "제주", "cat_name": "교통"},
    "성산일출봉":     {"lat": 33.4580, "lng": 126.9424, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "한라산":         {"lat": 33.3617, "lng": 126.5338, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "협재해수욕장":   {"lat": 33.3941, "lng": 126.2397, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "함덕해수욕장":   {"lat": 33.5430, "lng": 126.6697, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "월정리해변":     {"lat": 33.5605, "lng": 126.7958, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "우도":           {"lat": 33.5000, "lng": 126.9517, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "섭지코지":       {"lat": 33.4286, "lng": 126.9283, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "김녕해수욕장":   {"lat": 33.5561, "lng": 126.7547, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "새별오름":       {"lat": 33.3664, "lng": 126.2931, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "산굼부리":       {"lat": 33.4279, "lng": 126.6165, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "사려니숲길":     {"lat": 33.3726, "lng": 126.5953, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "쇠소깍":         {"lat": 33.2419, "lng": 126.6328, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "보롬왓":         {"lat": 33.3653, "lng": 126.7530, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "만장굴":         {"lat": 33.5280, "lng": 126.7720, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "올레길":         {"lat": 33.2489, "lng": 126.5641, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "카멜리아힐":     {"lat": 33.2920, "lng": 126.4057, "cat": "12", "region": "제주", "cat_name": "자연관광"},
    "오설록티뮤지엄": {"lat": 33.3059, "lng": 126.2909, "cat": "14", "region": "제주", "cat_name": "문화시설"},
    "아르떼뮤지엄":   {"lat": 33.4486, "lng": 126.3256, "cat": "14", "region": "제주", "cat_name": "문화시설"},
    "빛의벙커":       {"lat": 33.4450, "lng": 126.9210, "cat": "14", "region": "제주", "cat_name": "문화시설"},
    "에코랜드":       {"lat": 33.4571, "lng": 126.7016, "cat": "15", "region": "제주", "cat_name": "테마파크"},
    "스누피가든":     {"lat": 33.5070, "lng": 126.7250, "cat": "15", "region": "제주", "cat_name": "테마파크"},
    "아쿠아플라넷제주": {"lat": 33.4333, "lng": 126.9213, "cat": "15", "region": "제주", "cat_name": "테마파크"},
    "9.81파크":       {"lat": 33.3803, "lng": 126.3020, "cat": "15", "region": "제주", "cat_name": "테마파크"},
    "동문재래시장":   {"lat": 33.5126, "lng": 126.5291, "cat": "38", "region": "제주", "cat_name": "쇼핑"},
    "서귀포올레시장": {"lat": 33.2489, "lng": 126.5641, "cat": "38", "region": "제주", "cat_name": "쇼핑"},
    "불국사":         {"lat": 35.7897, "lng": 129.3317, "cat": "14", "region": "경주", "cat_name": "문화시설"},
    "석굴암":         {"lat": 35.7953, "lng": 129.3465, "cat": "14", "region": "경주", "cat_name": "문화시설"},
    "첨성대":         {"lat": 35.8347, "lng": 129.2191, "cat": "14", "region": "경주", "cat_name": "문화시설"},
    "동궁과월지":     {"lat": 35.8351, "lng": 129.2248, "cat": "14", "region": "경주", "cat_name": "문화시설"},
    "대릉원":         {"lat": 35.8364, "lng": 129.2147, "cat": "14", "region": "경주", "cat_name": "문화시설"},
    "설악산":         {"lat": 38.1190, "lng": 128.4654, "cat": "12", "region": "강원", "cat_name": "자연관광"},
    "오대산":         {"lat": 37.7947, "lng": 128.5369, "cat": "12", "region": "강원", "cat_name": "자연관광"},
    "정동진":         {"lat": 37.6844, "lng": 129.0559, "cat": "12", "region": "강원", "cat_name": "자연관광"},
}


def _normalize(name: str) -> str:
    # 1. 괄호 안 내용 제거: "한강공원(뚝섬지구)" → "한강공원"
    s = re.sub(r'[\(（\[【][^\)）\]】]*[\)）\]】]', '', name)
    # 2. 지점명 분리: "스타벅스 강남점" → "스타벅스", "CGV 홍대점" → "CGV"
    s = re.sub(r'\s+[가-힣]{1,5}(점|지점|본점)\s*$', '', s)
    # 3. 특수문자·공백 제거, 소문자화
    return re.sub(r'[\s·ㆍ\-\/\(\)（）「」\.,]+', '', s).lower()


def _guess_dwell(name: str) -> int:
    norm = _normalize(name)
    for key_raw, (mn, _) in _DWELL_OVERRIDES.items():
        if _normalize(key_raw) == norm:
            return mn
    hints = [
        ("공항", 60), ("시장", 60), ("카페", 60), ("마을", 60),
        ("해수욕장", 90), ("해변", 90), ("오름", 90), ("숲길", 90),
        ("박물관", 90), ("기념관", 90), ("미술관", 90), ("뮤지엄", 90),
        ("궁", 90), ("성", 90), ("타워", 90), ("전망대", 90), ("공원", 60),
        ("파크", 120), ("테마", 120), ("랜드", 120), ("산", 240),
        ("호텔", 480), ("리조트", 480), ("펜션", 480),
    ]
    for kw, m in hints:
        if kw in name:
            return m
    return 60


def _addr_to_region(addr: str) -> str:
    first = addr.strip().split()[0] if addr.strip() else ""
    return _SIDO_MAP.get(first, first[:2] if first else "")


def _build_coord_index() -> dict[str, dict]:
    """좌표 인덱스 빌드.
    1차: data/pois.csv          — TourAPI 벌크 수집 (20,168 POI, 전국 좌표 주소원본)
    2차: naver_metadata.json    — 보조 (1,000 POI)
    보정: _COORD_CATALOG (86건) — 소수 수동 보정값, 동명 충돌 시 pois.csv 값을 덮어씀
    """
    index: dict[str, dict] = {}

    # 1차: pois.csv (주 좌표 DB)
    pois_path = _DATA_DIR / "pois.csv"
    if pois_path.exists():
        with open(pois_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key = _normalize(row["title"])
                if key not in index:
                    try:
                        index[key] = {
                            "lat": float(row["mapy"]),
                            "lng": float(row["mapx"]),
                            "region": _addr_to_region(row.get("addr1", "")),
                            "cat": row.get("contenttypeid", "12"),
                            "cat_name": _TYPEID_LABEL.get(row.get("contenttypeid", ""), "관광지"),
                        }
                    except (ValueError, TypeError):
                        pass

    # 2차: naver_metadata.json (보조)
    naver_path = _DATA_DIR / "naver" / "naver_metadata.json"
    if naver_path.exists():
        with open(naver_path, encoding="utf-8") as f:
            naver_list = json.load(f)
        for n in naver_list:
            key = _normalize(n["title"])
            if key not in index:
                try:
                    index[key] = {
                        "lat": float(n["mapy"]),
                        "lng": float(n["mapx"]),
                        "region": _SIDO_MAP.get(n.get("sido", ""), n.get("sido", "")),
                        "cat": _TYPE_MAP.get(n.get("type_label", ""), "12"),
                        "cat_name": n.get("type_label", "관광지"),
                    }
                except (ValueError, TypeError):
                    pass

    # 보정: 수동 큐레이션 값이 pois.csv 값을 덮어씀 (소수 보정용)
    for k, v in _COORD_CATALOG.items():
        index[_normalize(k)] = v

    return index


def _build_place_list(coord_index: dict[str, dict]) -> list[dict]:
    """congestion_stats.csv 에서 고유 장소 + annual_max 집계 → 좌표 결합 → 정렬."""
    cong_path = _DATA_DIR / "congestion_stats.csv"
    if not cong_path.exists():
        return []

    place_max: dict[str, float] = {}
    with open(cong_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["poi_name"]
            try:
                v = float(row["annual_max"] or 0)
                if name not in place_max or v > place_max[name]:
                    place_max[name] = v
            except (ValueError, TypeError):
                pass

    result: list[dict] = []
    for name, annual_max in place_max.items():
        norm_key = _normalize(name)
        entry: dict | None = None

        # 1) 정확 일치
        if norm_key in coord_index:
            entry = coord_index[norm_key]
        else:
            # 2) 부분 문자열 일치 (4자 이상)
            if len(norm_key) >= 4:
                for ck, ce in coord_index.items():
                    if norm_key in ck or ck in norm_key:
                        entry = ce
                        break

        result.append({
            "name": name,
            "lat": entry["lat"] if entry else None,
            "lng": entry["lng"] if entry else None,
            "region": entry.get("region", "") if entry else "",
            "cat": entry.get("cat", "12") if entry else "12",
            "cat_name": entry.get("cat_name", "관광지") if entry else "관광지",
            "annual_max": annual_max,
            "has_coords": entry is not None,
        })

    result.sort(key=lambda x: -x["annual_max"])
    return result


# ── 모듈 로드 시 1회 빌드 ──────────────────────────────────────────────────
_COORD_INDEX: dict[str, dict] = _build_coord_index()
_PLACE_LIST: list[dict] = _build_place_list(_COORD_INDEX)
# 이름 정규화 → place dict 역방향 인덱스
_PLACE_NORM_INDEX: dict[str, dict] = {_normalize(p["name"]): p for p in _PLACE_LIST}


def _lookup_place(name: str) -> dict | None:
    """이름으로 place dict 조회. 정확 → 부분 순으로 시도."""
    norm = _normalize(name)
    if norm in _PLACE_NORM_INDEX:
        return _PLACE_NORM_INDEX[norm]
    if len(norm) >= 4:
        for k, v in _PLACE_NORM_INDEX.items():
            if norm in k or k in norm:
                return v
    return None


def _resolve_poi(name: str, idx: int) -> tuple[POI, POIInfo]:
    place = _lookup_place(name)
    has_coords = place is not None and place.get("has_coords", False)

    if has_coords:
        lat, lng = place["lat"], place["lng"]
        category = place["cat"]
        source = "hardcoded"
    else:
        lat, lng = _DEFAULT_CENTER
        category = "12"
        source = "fallback"

    hours = resolve_hours(name)
    dwell = _guess_dwell(name)

    poi = POI(
        poi_id=f"web_{idx:04d}",
        name=name, lat=lat, lng=lng,
        open_start=hours.open_, open_end=hours.close_,
        duration_min=dwell, category=category,
    )
    info = POIInfo(
        name=name, found=has_coords, source=source,
        lat=lat, lng=lng,
        open_start=hours.open_, open_end=hours.close_,
        duration_min=dwell,
    )
    return poi, info


_pipeline: ValidatorPipeline | None = None


def _get_pipeline() -> ValidatorPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ValidatorPipeline()
    return _pipeline


@router.get("/places", response_model=PlacesResponse)
async def list_places(q: str = "", region: str = "") -> PlacesResponse:
    """등록 장소 목록. q=검색어, region=지역 필터."""
    filtered = _PLACE_LIST
    if region:
        filtered = [p for p in filtered if p["region"] == region]
    if q:
        ql = q.lower()
        filtered = [p for p in filtered if ql in p["name"].lower()]

    items = [
        PlaceItem(
            name=p["name"],
            region=p["region"] or "기타",
            category_name=p["cat_name"],
            category_code=p["cat"],
            has_coords=p["has_coords"],
            annual_max=p["annual_max"],
        )
        for p in filtered
    ]
    return PlacesResponse(places=items, total=len(items))


@router.post("/validate", response_model=ValidateResponse)
async def validate_plan(req: ValidateRequest) -> ValidateResponse:
    if not req.days:
        raise HTTPException(status_code=422, detail="days must not be empty")

    per_day_pois: list[list[POI]] = []
    poi_info_list: list[POIInfo] = []
    global_idx = 0

    for day in req.days:
        day_pois: list[POI] = []
        for place in day.places:
            poi, info = _resolve_poi(place.name, global_idx)
            day_pois.append(poi)
            poi_info_list.append(info)
            global_idx += 1
        per_day_pois.append(day_pois)

    plan = ItineraryPlan(
        days=[
            DayPlan(places=[PlaceInput(name=p.name) for p in day.places])
            for day in req.days
        ],
        party_size=req.party_size,
        party_type=req.party_type,
        travel_type=req.travel_type,
        date=req.date,
    )

    result = _get_pipeline().run(
        plan=plan,
        per_day_pois=per_day_pois,
        matrix={},
    )

    return ValidateResponse(
        plan_id=result.plan_id,
        final_score=result.final_score,
        passed=(result.final_score >= 60 and not result.hard_fails),
        hard_fails=[hf.model_dump() for hf in result.hard_fails],
        warnings=[w.model_dump() for w in result.warnings],
        scores=result.scores.model_dump() if result.scores else None,
        penalty_breakdown=result.penalty_breakdown,
        bonus_breakdown=result.bonus_breakdown,
        rewards=result.rewards,
        poi_info=poi_info_list,
        repair_suggestions=result.repair or None,
    )
