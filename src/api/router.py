"""FastAPI 라우터 — /validate, /places 엔드포인트."""
from __future__ import annotations

import asyncio
import csv
import json
import re
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.api.schemas import (
    DayPlanWeb,
    ParsedPlanResponse,
    ParseTextRequest,
    PlaceItem,
    PlacesResponse,
    POIInfo,
    ValidateRequest,
    ValidateResponse,
)
from src.data.dwell_db import MANUAL_OVERRIDES as _DWELL_OVERRIDES
from src.data.graph_retriever import GraphRetriever
from src.data.hours_db import resolve_hours
from src.data.kakao_local import KakaoLocalClient
from src.data.models import POI, DayPlan, ItineraryPlan, PlaceInput
from src.explain.pipeline import ValidatorPipeline
from src.explain.plan_extractor import PlanExtractionError, PlanExtractor

router = APIRouter()

# 카카오 로컬 키워드 검색 (식당 등 pois.csv 미수록 장소의 좌표 보강).
# 키가 없으면 enabled=False 로 동작해 기존 폴백을 유지한다.
_KAKAO_LOCAL = KakaoLocalClient.from_env()

# Neo4j 지식그래프 — 지역/도보권 대안 근거. NEO4J_URI 미설정 시 enabled=False로 조용히 폴백.
_GRAPH = GraphRetriever.from_env()

# 일정표 업로드(PDF·이미지·복사 텍스트) 파싱 — Claude Vision + 쿼리 리라이팅.
_EXTRACTOR = PlanExtractor.from_env()
_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB
_ALLOWED_DOC_TYPES = {
    "application/pdf": "application/pdf",
    "image/png": "image/png",
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
}


def _kakao_hint(category_name: str) -> str | None:
    """카카오 category_name → hours_db 카테고리 힌트."""
    c = category_name or ""
    if "음식점" in c:
        return "식당"
    if "카페" in c:
        return "카페"
    if "문화" in c or "박물관" in c or "미술관" in c:
        return "문화시설"
    if "백화점" in c or "마트" in c or "쇼핑" in c:
        return "쇼핑"
    return None


def _kakao_cat_code(category_name: str) -> str:
    """카카오 category_name → 앱 카테고리 코드(12 관광지·14 문화·38 쇼핑·39 음식점·32 숙박)."""
    c = category_name or ""
    if "음식점" in c or "카페" in c:
        return "39"
    if "문화" in c or "박물관" in c or "미술관" in c:
        return "14"
    if "백화점" in c or "마트" in c or "쇼핑" in c:
        return "38"
    if "숙박" in c or "호텔" in c or "모텔" in c:
        return "32"
    return "12"

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DEFAULT_CENTER = (37.5665, 126.9780)  # 서울 시청

# TourAPI 실제 운영시간 캐시 (scripts/fetch_jeju_hours.py 로 미리 조회, contentid → {open, close}).
# 없는 곳은 기존처럼 hours_db.resolve_hours() 카테고리 추정값을 쓴다.
_JEJU_HOURS: dict[str, dict] = {}
_jeju_hours_path = _DATA_DIR / "jeju_hours.json"
if _jeju_hours_path.exists():
    with open(_jeju_hours_path, encoding="utf-8") as f:
        _JEJU_HOURS = json.load(f)

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
    "wellness": "웰니스", "bf": "무장애여행",
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
    # 대구
    "팔공산":         {"lat": 35.9991, "lng": 128.6966, "cat": "12", "region": "대구", "cat_name": "자연관광"},
    "동성로":         {"lat": 35.8664, "lng": 128.5955, "cat": "38", "region": "대구", "cat_name": "쇼핑"},
    "근대골목":       {"lat": 35.8692, "lng": 128.5967, "cat": "12", "region": "대구", "cat_name": "관광지"},
    "서문시장":       {"lat": 35.8688, "lng": 128.5808, "cat": "38", "region": "대구", "cat_name": "쇼핑"},
    "대구수목원":     {"lat": 35.8322, "lng": 128.5307, "cat": "12", "region": "대구", "cat_name": "자연관광"},
    "김광석다시그리기길": {"lat": 35.8682, "lng": 128.6020, "cat": "12", "region": "대구", "cat_name": "관광지"},
    # 광주
    "무등산":         {"lat": 35.1298, "lng": 126.9883, "cat": "12", "region": "광주", "cat_name": "자연관광"},
    "양림동":         {"lat": 35.1410, "lng": 126.8951, "cat": "12", "region": "광주", "cat_name": "관광지"},
    "국립아시아문화전당": {"lat": 35.1456, "lng": 126.9160, "cat": "14", "region": "광주", "cat_name": "문화시설"},
    "충장로":         {"lat": 35.1489, "lng": 126.9147, "cat": "38", "region": "광주", "cat_name": "쇼핑"},
    # 대전
    "대전엑스포과학공원": {"lat": 36.3736, "lng": 127.3865, "cat": "12", "region": "대전", "cat_name": "관광지"},
    "유성온천":       {"lat": 36.3625, "lng": 127.3367, "cat": "12", "region": "대전", "cat_name": "관광지"},
    "계룡산":         {"lat": 36.3462, "lng": 127.2113, "cat": "12", "region": "충남", "cat_name": "자연관광"},
    "한밭수목원":     {"lat": 36.3621, "lng": 127.3847, "cat": "12", "region": "대전", "cat_name": "자연관광"},
    "대전오월드":     {"lat": 36.3090, "lng": 127.3620, "cat": "15", "region": "대전", "cat_name": "테마파크"},
    # 충북
    "단양팔경":       {"lat": 36.9848, "lng": 128.3673, "cat": "12", "region": "충북", "cat_name": "자연관광"},
    "소백산":         {"lat": 36.9641, "lng": 128.4743, "cat": "12", "region": "충북", "cat_name": "자연관광"},
    "청남대":         {"lat": 36.4853, "lng": 127.5039, "cat": "12", "region": "충북", "cat_name": "관광지"},
}


_CHOSUNG_LIST = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
_JAMO_CHARS = set("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")


def _extract_chosung(text: str) -> str:
    result = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            result.append(_CHOSUNG_LIST[(code - 0xAC00) // (21 * 28)])
        elif ch in _JAMO_CHARS:
            result.append(ch)
    return "".join(result)


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


# data/jeju_places.csv (대한민국구석구석 제주특별자치도 통합, 25,377건) 대분류코드 → 앱 카테고리 코드
_JEJU_CAT_MAP: dict[str, str] = {
    "FD": "39", "AC": "32", "SH": "38", "VE": "14", "LS": "28", "EX": "12", "HS": "14",
}


def _parse_jeju_hours(raw: str) -> tuple[str, str] | None:
    """'09:00~18:00 (매표마감 17:00)' 같은 원문에서 첫 HH:MM~HH:MM 구간만 뽑아낸다."""
    s = (raw or "").strip()
    if not s:
        return None
    if "24시간" in s:
        return "00:00", "23:59"
    m = re.search(r'(\d{1,2}:\d{2})\s*~\s*(\d{1,2}:\d{2})', s)
    return (m.group(1), m.group(2)) if m else None


def _build_jeju_place_index() -> dict[str, dict]:
    """data/jeju_places.csv — 실측 좌표·영업시간을 가진 제주 전역 25,377건 통합 DB."""
    index: dict[str, dict] = {}
    path = _DATA_DIR / "jeju_places.csv"
    if not path.exists():
        return index
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("상호명") or "").strip()
            if not name:
                continue
            key = _normalize(name)
            if key in index:
                continue
            try:
                lat, lng = float(row["위도"]), float(row["경도"])
            except (ValueError, TypeError, KeyError):
                continue
            entry = {
                "name": name, "lat": lat, "lng": lng, "region": "제주",
                "cat": _JEJU_CAT_MAP.get(row.get("대분류코드", ""), "12"),
                "cat_name": row.get("대분류명", "관광지"),
                "addr": (row.get("도로명주소") or "").strip(),
                "has_coords": True,
                "source": "jeju_csv",
            }
            hrs = _parse_jeju_hours(row.get("영업시간", ""))
            if hrs:
                entry["open_start"], entry["open_end"] = hrs
            index[key] = entry
    return index


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
                            "contentid": row.get("contentid", ""),
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

    # pois.csv에서 firstimage 인덱스 빌드
    image_index: dict[str, str] = {}
    pois_path = _DATA_DIR / "pois.csv"
    if pois_path.exists():
        with open(pois_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                img = row.get("firstimage", "").strip()
                if img:
                    image_index[_normalize(row["title"])] = img

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
            "firstimage": image_index.get(norm_key, ""),
        })

    result.sort(key=lambda x: -x["annual_max"])
    return result


def _build_full_place_list(coord_index: dict[str, dict]) -> list[dict]:
    """pois.csv(20,168) + wellness(175) + barrier_free(1,799) 통합 장소 목록."""
    result: list[dict] = []
    seen: set[str] = set()

    # 1) pois.csv
    pois_path = _DATA_DIR / "pois.csv"
    if pois_path.exists():
        with open(pois_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = row["title"].strip()
                norm = _normalize(name)
                if norm in seen or not name:
                    continue
                seen.add(norm)
                try:
                    lat = float(row["mapy"])
                    lng = float(row["mapx"])
                    has_c = True
                except (ValueError, TypeError):
                    lat, lng = None, None
                    has_c = False
                region = _addr_to_region(row.get("addr1", ""))
                cat = row.get("contenttypeid", "12")
                result.append({
                    "name": name,
                    "lat": lat,
                    "lng": lng,
                    "region": region,
                    "cat": cat,
                    "cat_name": _TYPEID_LABEL.get(cat, "관광지"),
                    "annual_max": 0.0,
                    "has_coords": has_c,
                    "firstimage": row.get("firstimage", "").strip(),
                    "addr": row.get("addr1", "").strip(),
                    "tags": [],
                })

    # 2) wellness_places.json
    wl_path = _DATA_DIR / "wellness_places.json"
    if wl_path.exists():
        with open(wl_path, encoding="utf-8") as f:
            wellness_list = json.load(f)
        for item in wellness_list:
            name = item.get("title", "").strip()
            norm = _normalize(name)
            if not name or norm in seen:
                continue
            seen.add(norm)
            try:
                lat = float(item["lat"]); lng = float(item["lng"]); has_c = True
            except (ValueError, TypeError):
                lat, lng = None, None; has_c = False
            result.append({
                "name": name,
                "lat": lat, "lng": lng,
                "region": _addr_to_region(item.get("addr", "")),
                "cat": "wellness",
                "cat_name": "웰니스",
                "annual_max": 0.0,
                "has_coords": has_c,
                "firstimage": "",
                "addr": item.get("addr", "").strip(),
                "tags": ["웰니스", "힐링"],
            })

    # 3) barrier_free_places.json
    bf_path = _DATA_DIR / "barrier_free_places.json"
    if bf_path.exists():
        with open(bf_path, encoding="utf-8") as f:
            bf_list = json.load(f)
        for item in bf_list:
            name = item.get("title", "").strip()
            norm = _normalize(name)
            if not name or norm in seen:
                continue
            seen.add(norm)
            try:
                lat = float(item["lat"]); lng = float(item["lng"]); has_c = True
            except (ValueError, TypeError):
                lat, lng = None, None; has_c = False
            bf_tags = ["무장애"]
            if item.get("wheelchair"): bf_tags.append("휠체어")
            if item.get("elevator"): bf_tags.append("엘리베이터")
            if item.get("stroller"): bf_tags.append("유모차")
            if item.get("parking"): bf_tags.append("주차가능")
            result.append({
                "name": name,
                "lat": lat, "lng": lng,
                "region": _addr_to_region(item.get("addr", "")),
                "cat": "bf",
                "cat_name": "무장애여행",
                "annual_max": 0.0,
                "has_coords": has_c,
                "firstimage": "",
                "addr": item.get("addr", "").strip(),
                "tags": bf_tags,
            })

    return result


def _build_monthly_congestion() -> dict[str, dict[int, float]]:
    """congestion_stats.csv의 월별 혼잡도 점수 인덱스."""
    result: dict[str, dict[int, float]] = {}
    cong_path = _DATA_DIR / "congestion_stats.csv"
    if not cong_path.exists():
        return result
    with open(cong_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["poi_name"]
            try:
                month = int(row["month"])
                score = float(row.get("congestion_score") or row.get("avg_visitors") or 0)
                if name not in result:
                    result[name] = {}
                result[name][month] = score
            except (ValueError, TypeError):
                pass
    return result


# ── 모듈 로드 시 1회 빌드 ──────────────────────────────────────────────────
_JEJU_CSV_INDEX: dict[str, dict] = _build_jeju_place_index()
_COORD_INDEX: dict[str, dict] = _build_coord_index()
for _k, _v in _JEJU_CSV_INDEX.items():
    _COORD_INDEX.setdefault(_k, _v)  # pois.csv/naver_metadata/카탈로그 미매칭 시에만 보강
_PLACE_LIST: list[dict] = _build_place_list(_COORD_INDEX)
_FULL_PLACE_LIST: list[dict] = _build_full_place_list(_COORD_INDEX)
_seen_full = {_normalize(p["name"]) for p in _FULL_PLACE_LIST}
_FULL_PLACE_LIST += [
    {
        "name": e["name"], "lat": e["lat"], "lng": e["lng"],
        "region": e["region"], "cat": e["cat"], "cat_name": e["cat_name"],
        "annual_max": 0.0, "has_coords": True,
        "firstimage": "", "addr": e.get("addr", ""), "tags": [],
    }
    for k, e in _JEJU_CSV_INDEX.items() if k not in _seen_full
]
_MONTHLY_CONG: dict[str, dict[int, float]] = _build_monthly_congestion()
# 이름 정규화 → place dict 역방향 인덱스
_PLACE_NORM_INDEX: dict[str, dict] = {_normalize(p["name"]): p for p in _PLACE_LIST}
# _COORD_CATALOG 수동 큐레이션 목록 정규화 키 집합 (신뢰도 High 판정용)
_COORD_CATALOG_NORM: frozenset[str] = frozenset(_normalize(k) for k in _COORD_CATALOG)


def _lookup_place(name: str) -> dict | None:
    """이름으로 place dict 조회. 정확 → 부분 순으로 시도.
    congestion 기반 인기 장소(_PLACE_NORM_INDEX) 우선, 없으면 제주 통합 DB(_JEJU_CSV_INDEX)."""
    norm = _normalize(name)
    if norm in _PLACE_NORM_INDEX:
        return _PLACE_NORM_INDEX[norm]
    if norm in _JEJU_CSV_INDEX:
        return _JEJU_CSV_INDEX[norm]
    if len(norm) >= 4:
        for k, v in _PLACE_NORM_INDEX.items():
            if norm in k or k in norm:
                return v
        # jeju_places.csv는 "해녀"·"카페" 같은 짧은 상호가 많아 후보 쪽도 4자 이상만 허용
        for k, v in _JEJU_CSV_INDEX.items():
            if len(k) >= 4 and (norm in k or k in norm):
                return v
    return None


def _resolve_poi(name: str, idx: int, address: str = "") -> tuple[POI, POIInfo]:
    place = _lookup_place(name)
    has_coords = place is not None and place.get("has_coords", False)
    norm = _normalize(name)

    # 신뢰도 3단계:
    #   High   — 수동 큐레이션 카탈로그(_COORD_CATALOG) 매칭 (86건 검증된 좌표)
    #   Medium — pois.csv / naver_metadata 매칭 (TourAPI 수집 좌표)
    #   Low    — 서울 시청 폴백 (좌표 신뢰 불가)
    hint: str | None = None
    contentid = ""
    if norm in _COORD_CATALOG_NORM:
        confidence: str = "High"
        source = "catalog"
        lat = _COORD_CATALOG[next(k for k in _COORD_CATALOG if _normalize(k) == norm)]["lat"]
        lng = _COORD_CATALOG[next(k for k in _COORD_CATALOG if _normalize(k) == norm)]["lng"]
        category = _COORD_CATALOG[next(k for k in _COORD_CATALOG if _normalize(k) == norm)]["cat"]
    elif has_coords:
        confidence = "Medium"
        source = place.get("source", "pois")
        lat, lng = place["lat"], place["lng"]
        category = place["cat"]
        contentid = str(place.get("contentid") or "")
    else:
        # pois.csv·카탈로그 미매칭 → 카카오 로컬 키워드 검색으로 좌표 보강
        # (식당·카페 등). 실패 시에만 서울시청 폴백으로 떨어진다.
        kp = _KAKAO_LOCAL.search_keyword(name)
        if kp is not None:
            confidence = "Medium"
            source = "kakao"
            lat, lng = kp.lat, kp.lng
            category = "12"
            hint = _kakao_hint(kp.category_name)
        else:
            # 카카오 키워드 검색도 실패 — 파싱된 주소가 있으면 지오코딩으로 최후 보강
            # (4·3길 등 사업장이 아닌 장소는 키워드 검색에 잡히지 않는다).
            geo = _KAKAO_LOCAL.geocode_address(address) if address else None
            if geo is not None:
                confidence = "Medium"
                source = "geocode"
                lat, lng = geo
                category = "12"
            else:
                confidence = "Low"
                source = "fallback"
                lat, lng = _DEFAULT_CENTER
                category = "12"

    # 운영시간: TourAPI 실측(jeju_hours.json) → jeju_places.csv 실측 영업시간 →
    # 카테고리·키워드 추정(hours_db) 순으로 폴백.
    real_hours = _JEJU_HOURS.get(contentid) if contentid else None
    if not real_hours and place and place.get("open_start"):
        real_hours = {"open": place["open_start"], "close": place["open_end"]}
    if real_hours:
        open_start, open_end = real_hours["open"], real_hours["close"]
        hours_estimated = False
    else:
        hours = resolve_hours(name, hint)
        open_start, open_end = hours.open_, hours.close_
        hours_estimated = True
    dwell = _guess_dwell(name)

    # 지식그래프 근거 — 지역·도보권 대안. 그래프 미설정/미매칭 시 조용히 생략.
    graph_region, graph_nearby = "", []
    graph_places = _GRAPH.search_places(name, limit=1)
    if graph_places:
        gp = graph_places[0]
        graph_region = gp.region_name
        graph_nearby = [a.name for a in _GRAPH.find_nearby(gp.place_id, limit=3)]

    poi = POI(
        poi_id=f"web_{idx:04d}",
        name=name, lat=lat, lng=lng,
        open_start=open_start, open_end=open_end,
        duration_min=dwell, category=category,
        hours_estimated=hours_estimated,
    )
    info = POIInfo(
        name=name, found=(confidence != "Low"), source=source,
        confidence=confidence,
        lat=lat, lng=lng,
        open_start=open_start, open_end=open_end,
        duration_min=dwell,
        hours_estimated=hours_estimated,
        graph_region=graph_region,
        graph_nearby=graph_nearby,
    )
    return poi, info


_RELIABILITY_WEIGHTS: dict[str, int] = {"High": 100, "Medium": 70, "Low": 40}


def _calc_reliability_score(poi_info_list: list[POIInfo]) -> int:
    if not poi_info_list:
        return 100
    total = sum(_RELIABILITY_WEIGHTS.get(info.confidence, 70) for info in poi_info_list)
    return round(total / len(poi_info_list))


_pipeline: ValidatorPipeline | None = None


def _get_pipeline() -> ValidatorPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ValidatorPipeline()
    return _pipeline


@router.get("/places", response_model=PlacesResponse)
async def list_places(
    q: str = "", region: str = "", extended: bool = False, cat: str = "",
    offset: int = 0, limit: int = 2000,
) -> PlacesResponse:
    """등록 장소 목록.
    q=검색어, region=지역 필터, cat=카테고리 코드, extended=전체DB 초기 로드.
    offset/limit으로 서버 측 페이지네이션 지원.
    q/cat/region 없이 호출 시 congestion 기반 인기 장소 4,174건 반환.
    """
    use_full = bool(q or extended or region or cat)
    source = _FULL_PLACE_LIST if use_full else _PLACE_LIST
    filtered = source
    if region:
        filtered = [p for p in filtered if p.get("region", "") == region]
    if cat and cat not in ("all", "fav"):
        filtered = [p for p in filtered if p.get("cat", "") == cat]
    q_is_jamo = bool(q) and all(ch in _JAMO_CHARS for ch in q if ch.strip())
    if q:
        ql = q.lower()
        # 초성 검색: q가 자모로만 구성된 경우(예: 'ㄱㅂㄱ') 초성 매칭 사용
        if q_is_jamo:
            qcho = _extract_chosung(q)
            filtered = [p for p in filtered if _extract_chosung(p["name"]).startswith(qcho)]
        else:
            filtered = [p for p in filtered if ql in p["name"].lower()]

    # 로컬 DB(pois.csv)에 결과가 적으면 카카오 키워드 검색으로 보강(식당 등 미수록 장소).
    if q and not q_is_jamo and len(filtered) < 8 and _KAKAO_LOCAL.enabled:
        existing = {_normalize(p["name"]) for p in filtered}
        for kp in _KAKAO_LOCAL.search_keyword_list(q, size=15):
            nm = _normalize(kp.name)
            if not nm or nm in existing:
                continue
            kp_region = _addr_to_region(kp.address) or "기타"
            if region and kp_region != region:
                continue
            code = _kakao_cat_code(kp.category_name)
            if cat and cat not in ("all", "fav") and code != cat:
                continue
            existing.add(nm)
            filtered = filtered + [{
                "name": kp.name,
                "region": kp_region,
                "cat": code,
                "cat_name": (kp.category_name.split(">")[-1].strip() if kp.category_name else "장소"),
                "has_coords": True,
                "annual_max": 0.0,
                "firstimage": "",
                "addr": kp.address,
                "tags": ["카카오"],
            }]

    total_count = len(filtered)
    page_size = min(limit, 2000) if use_full else total_count
    paged = filtered[offset : offset + page_size]

    items = [
        PlaceItem(
            name=p["name"],
            region=p["region"] or "기타",
            category_name=p["cat_name"],
            category_code=p["cat"],
            has_coords=p["has_coords"],
            annual_max=p["annual_max"],
            firstimage=p.get("firstimage", ""),
            addr=p.get("addr", ""),
            tags=p.get("tags", []),
        )
        for p in paged
    ]
    return PlacesResponse(places=items, total=total_count)


@router.get("/monthly/{name}")
async def monthly_congestion(name: str) -> dict:
    """특정 장소의 월별 혼잡도 데이터."""
    monthly = _MONTHLY_CONG.get(name, {})
    if not monthly:
        for raw_name, data in _MONTHLY_CONG.items():
            if _normalize(raw_name) == _normalize(name):
                monthly = data
                break
    return {"name": name, "monthly": {str(k): round(v, 1) for k, v in monthly.items()}}


@router.get("/regions")
async def list_regions() -> dict:
    """지역별 장소 수 통계."""
    from collections import Counter
    counts: Counter[str] = Counter()
    for p in _FULL_PLACE_LIST:
        r = p.get("region") or "기타"
        if r:
            counts[r] += 1
    return {"regions": [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]}


@router.post("/parse/text", response_model=ParsedPlanResponse)
async def parse_text(req: ParseTextRequest) -> ParsedPlanResponse:
    """추천 경로를 복사한 텍스트 → 쿼리 리라이팅으로 day/place 구조 추출."""
    try:
        return await asyncio.to_thread(_EXTRACTOR.extract_from_text, req.text)
    except PlanExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/parse/document", response_model=ParsedPlanResponse)
async def parse_document(file: UploadFile = File(...)) -> ParsedPlanResponse:
    """AI 플래너 결과 PDF·스크린샷(PNG/JPG) → Claude Vision으로 day/place 구조 추출."""
    media_type = _ALLOWED_DOC_TYPES.get((file.content_type or "").lower())
    if media_type is None:
        raise HTTPException(status_code=415, detail="PDF, PNG, JPG 파일만 지원합니다.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일입니다.")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (최대 15MB).")
    try:
        return await asyncio.to_thread(_EXTRACTOR.extract_from_document, data, media_type)
    except PlanExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/resolve-coords", response_model=list[POI])
async def resolve_coords(req: DayPlanWeb) -> list[POI]:
    """빌더(Step2) 지도용 좌표 조회. 검증 파이프라인(Hard Fail/스코어링/LLM 설명) 없이
    좌표 해석만 수행해 빠르게 응답한다."""
    resolved = await asyncio.gather(
        *(
            asyncio.to_thread(_resolve_poi, place.name, idx, place.address)
            for idx, place in enumerate(req.places)
        )
    )
    return [poi for poi, _info in resolved]


@router.post("/validate", response_model=ValidateResponse)
async def validate_plan(req: ValidateRequest) -> ValidateResponse:
    if not req.days:
        raise HTTPException(status_code=422, detail="days must not be empty")

    # _resolve_poi는 Kakao/Neo4j 블로킹 I/O를 포함한다 — 장소별로 순차 실행하면
    # 지연이 선형으로 누적되고 이벤트 루프까지 막힌다. to_thread로 동시 실행한다.
    flat_places = [
        (day_idx, place.name, place.address)
        for day_idx, day in enumerate(req.days)
        for place in day.places
    ]
    resolved = await asyncio.gather(
        *(
            asyncio.to_thread(_resolve_poi, name, idx, address)
            for idx, (_, name, address) in enumerate(flat_places)
        )
    )

    per_day_pois: list[list[POI]] = [[] for _ in req.days]
    poi_info_list: list[POIInfo] = []
    for (day_idx, _, _addr), (poi, info) in zip(flat_places, resolved, strict=True):
        info = info.model_copy(update={"day_index": day_idx, "category": poi.category})
        per_day_pois[day_idx].append(poi)
        poi_info_list.append(info)

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

    result = await asyncio.to_thread(
        _get_pipeline().run,
        plan=plan,
        per_day_pois=per_day_pois,
        matrix={},
    )

    data_reliability_score = _calc_reliability_score(poi_info_list)

    # ── 월별 혼잡도 경고 생성 ──────────────────────────────────────
    congestion_warnings: list[dict] = []
    try:
        travel_month = int(req.date.split("-")[1])
    except (IndexError, ValueError):
        travel_month = 5

    MONTH_NAMES = {1:"1월",2:"2월",3:"3월",4:"4월",5:"5월",6:"6월",
                   7:"7월",8:"8월",9:"9월",10:"10월",11:"11월",12:"12월"}

    for info in poi_info_list:
        monthly = _MONTHLY_CONG.get(info.name)
        if not monthly:
            continue
        score = monthly.get(travel_month, 0)
        if not score:
            continue
        max_score = max(monthly.values())
        min_score = min(monthly.values())
        if max_score <= 0:
            continue
        ratio = score / max_score
        # 연중 최대 대비 85% 이상이면 경고
        if ratio >= 0.85:
            level = "high" if ratio >= 0.95 else "medium"
            best_month = min(monthly, key=monthly.get)
            congestion_warnings.append({
                "poi_name": info.name,
                "month": travel_month,
                "level": level,
                "ratio": round(ratio, 2),
                "message": (
                    f"{MONTH_NAMES[travel_month]}은 연중 가장 붐비는 시기예요. "
                    f"예약이나 이른 방문을 추천해요."
                    if level == "high" else
                    f"{MONTH_NAMES[travel_month]}은 사람이 꽤 많은 편이에요. "
                    f"여유 있게 시간을 잡으세요."
                ),
                "best_month": best_month,
            })

    return ValidateResponse(
        plan_id=result.plan_id,
        final_score=result.final_score,
        base_score=result.base_score,
        passed=(
            result.final_score >= 60
            and not [hf for hf in result.hard_fails if not getattr(hf, "estimated", False)]
        ),
        data_reliability_score=data_reliability_score,
        hard_fails=[hf.model_dump() for hf in result.hard_fails],
        warnings=[w.model_dump() for w in result.warnings],
        scores=result.scores.model_dump() if result.scores else None,
        explanations=[e.model_dump() for e in result.explanations],
        penalty_breakdown=result.penalty_breakdown,
        bonus_breakdown=result.bonus_breakdown,
        rewards=result.rewards,
        alternatives={k: [a.model_dump() for a in v] for k, v in result.alternatives.items()},
        poi_info=poi_info_list,
        repair_suggestions=result.repair or None,
        optimal_route=(
            [r.model_dump() for r in result.vrptw_optimal_route]
            if result.vrptw_optimal_route else None
        ),
        vrptw_efficiency_gap=result.vrptw_efficiency_gap,
        congestion_warnings=congestion_warnings,
    )
