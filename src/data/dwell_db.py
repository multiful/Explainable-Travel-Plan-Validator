"""권장 체류시간 데이터베이스 (하이브리드 룩업).

5단계 폴백 우선순위로 (min, max) 분 단위 권장 체류시간을 반환:
  1. MANUAL_OVERRIDES   — 주요 POI 이름 기반 수동 큐레이션
  2. BY_LCLS3           — TourAPI lclsSystm3 (3-depth 분류) 룩업
  3. BY_LCLS1           — TourAPI lclsSystm1 (1-depth 대분류) 룩업
  4. BY_CONTENT_TYPE    — contentTypeId 룩업
  5. DEFAULT_DWELL      — 마지막 폴백

사용자가 입력한 stay_duration이 권장 min의 50% 미만이면 비현실적으로 짧은 일정으로 간주.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DwellSource = Literal["manual", "lcls3", "lcls1", "content_type", "default"]


@dataclass(frozen=True)
class DwellRecommendation:
    """권장 체류시간 (분 단위)."""

    min_minutes: int
    max_minutes: int
    source: DwellSource

    def is_too_short(self, user_minutes: int, ratio: float = 0.5) -> bool:
        """사용자 입력이 권장 min의 ratio(기본 50%) 미만이면 True."""
        return user_minutes < int(self.min_minutes * ratio)


# ── 1순위: 주요 POI 수동 큐레이션 ────────────────────────────────────
# 키: POI 이름의 정확한 매칭 (대소문자/공백 정규화 후 비교)
# 값: (권장 최소, 권장 최대) 분 단위
# 출처: 한국관광공사 추천, 여행 블로그, 공식 안내자료 종합
MANUAL_OVERRIDES: dict[str, tuple[int, int]] = {
    # 서울 — 주요 고궁·관광지
    "경복궁": (90, 150),
    "창덕궁": (90, 150),
    "덕수궁": (60, 120),
    "창경궁": (60, 120),
    "종묘": (45, 90),
    "남산서울타워": (90, 180),
    "N서울타워": (90, 180),
    "롯데월드타워": (120, 240),
    "63빌딩": (60, 120),
    "북촌한옥마을": (60, 120),
    "인사동": (60, 120),
    "명동": (60, 120),
    "이태원": (60, 120),
    "홍대": (90, 180),
    "강남역": (60, 120),
    "동대문디자인플라자": (60, 120),
    # 박물관·미술관
    "국립중앙박물관": (120, 240),
    "국립현대미술관": (120, 180),
    "리움미술관": (120, 180),
    "전쟁기념관": (120, 180),
    # 자연·공원
    "한강공원": (60, 180),
    "남산공원": (60, 120),
    "올림픽공원": (90, 180),
    "북한산": (240, 480),
    "관악산": (240, 480),
    # 부산
    "해운대해수욕장": (90, 240),
    "광안리해수욕장": (90, 240),
    "감천문화마을": (60, 120),
    "태종대": (90, 150),
    "용두산공원": (45, 90),
    "자갈치시장": (45, 90),
    "BIFF광장": (45, 90),
    "센텀시티": (90, 180),
    # 제주
    "한라산": (300, 600),
    "성산일출봉": (90, 150),
    "우도": (240, 480),
    "협재해수욕장": (60, 180),
    "함덕해수욕장": (60, 180),
    "만장굴": (60, 90),
    "올레길": (180, 360),
    # 경주
    "불국사": (90, 150),
    "석굴암": (45, 90),
    "첨성대": (30, 60),
    "안압지": (45, 90),
    "동궁과월지": (45, 90),
    "대릉원": (60, 120),
    # 강원·기타
    "설악산": (300, 600),
    "오대산": (240, 480),
    "정동진": (60, 120),
    # 테마파크
    "에버랜드": (480, 720),
    "롯데월드": (480, 720),
    "서울랜드": (300, 480),
    "캐리비안베이": (300, 600),
}


# ── 2순위: lclsSystm3 (3-depth 분류) 기반 ────────────────────────────
# 코드 명세는 TourAPI lclsSystmCode2 응답 참조
# 주요 분류만 명시 (커버 못한 코드는 lclsSystm1 폴백)
BY_LCLS3: dict[str, tuple[int, int]] = {
    # 자연관광지 (NA)
    "NA0101": (180, 480),  # 국립공원
    "NA0201": (120, 360),  # 도립공원
    "NA0401": (180, 480),  # 산
    "NA0501": (90, 180),  # 자연생태관광지
    "NA0601": (120, 240),  # 자연휴양림
    "NA0701": (90, 150),  # 수목원
    "NA0801": (45, 90),  # 폭포
    "NA0901": (60, 120),  # 계곡
    "NA1101": (60, 120),  # 해안절경
    "NA1201": (90, 240),  # 해수욕장
    "NA1301": (240, 480),  # 섬
    # 인문관광지 (VE)
    "VE0101": (90, 180),  # 박물관
    "VE0201": (60, 120),  # 기념관
    "VE0301": (60, 120),  # 전시관
    "VE0401": (90, 180),  # 미술관
    "VE0501": (90, 180),  # 체험관
    "VE0701": (60, 120),  # 기타문화시설
    # 역사관광지 (HS)
    "HS0101": (90, 150),  # 고궁
    "HS0201": (60, 120),  # 사찰
    "HS0301": (60, 120),  # 유적지
    # 레포츠 (EX)
    "EX0101": (180, 360),  # 육상레포츠
    "EX0201": (120, 240),  # 수상레포츠
    "EX0301": (180, 480),  # 항공레포츠
    "EX0401": (240, 480),  # 복합레포츠
    "EX2101": (300, 600),  # 테마파크 (추정 코드)
    # 음식점 (FD)
    "FD0101": (45, 75),  # 한식
    "FD0102": (45, 75),  # 양식
    "FD0103": (45, 75),  # 일식
    "FD0104": (45, 75),  # 중식
    "FD0201": (30, 60),  # 카페
    "FD0202": (30, 60),  # 카페·전통찻집
    # 쇼핑 (SH)
    "SH0101": (45, 90),  # 5일장·전통시장
    "SH0201": (60, 180),  # 백화점
    "SH0301": (60, 120),  # 면세점
    "SH0401": (60, 120),  # 대형마트
    # 숙박 (AC) — depot이라 체류시간 의미 없음, 형식상 정의
    "AC0101": (0, 0),  # 호텔
    "AC0301": (0, 0),  # 한옥
}


# ── 3순위: lclsSystm1 (1-depth 대분류) 기반 ──────────────────────────
BY_LCLS1: dict[str, tuple[int, int]] = {
    "NA": (90, 240),  # 자연관광지
    "VE": (75, 150),  # 인문관광지
    "HS": (60, 120),  # 역사관광지
    "EX": (180, 360),  # 레포츠
    "FD": (45, 75),  # 음식점
    "SH": (60, 120),  # 쇼핑
    "AC": (0, 0),  # 숙박
}


# ── 4순위: contentTypeId 기반 ─────────────────────────────────────────
BY_CONTENT_TYPE: dict[int, tuple[int, int]] = {
    12: (90, 150),  # 관광지
    14: (90, 150),  # 문화시설
    15: (120, 240),  # 축제공연행사
    25: (480, 720),  # 여행코스 (하루 단위)
    28: (180, 360),  # 레포츠
    32: (0, 0),  # 숙박
    38: (60, 120),  # 쇼핑
    39: (45, 75),  # 음식점
}


# ── 5순위: 최후 폴백 ──────────────────────────────────────────────────
DEFAULT_DWELL: tuple[int, int] = (60, 120)


def _normalize_name(name: str) -> str:
    """이름 정규화: 공백·특수문자 제거 후 소문자."""
    return "".join(name.split()).lower().replace("(", "").replace(")", "")


# 정규화된 이름 룩업 테이블 (모듈 로드 시 한 번만 빌드)
_NORMALIZED_OVERRIDES: dict[str, tuple[int, int]] = {
    _normalize_name(k): v for k, v in MANUAL_OVERRIDES.items()
}


def get_recommended_dwell(
    name: str,
    lcls_systm3: str | None = None,
    lcls_systm1: str | None = None,
    content_type_id: int | None = None,
) -> DwellRecommendation:
    """5단계 폴백으로 권장 체류시간 반환.

    인자
    ----
    name           : POI 이름 (필수)
    lcls_systm3    : "VE0101" 같은 3-depth 분류 코드 (선택)
    lcls_systm1    : "VE" 같은 1-depth 대분류 (선택)
    content_type_id: 12, 14, 39 등 (선택)

    반환
    ----
    DwellRecommendation(min_minutes, max_minutes, source)
    """
    # 1순위: 수동 오버라이드
    norm = _normalize_name(name)
    if norm in _NORMALIZED_OVERRIDES:
        mn, mx = _NORMALIZED_OVERRIDES[norm]
        return DwellRecommendation(mn, mx, "manual")

    # 2순위: lcls_systm3
    if lcls_systm3 and lcls_systm3 in BY_LCLS3:
        mn, mx = BY_LCLS3[lcls_systm3]
        return DwellRecommendation(mn, mx, "lcls3")

    # 3순위: lcls_systm1 (lcls_systm3에서 앞 2글자 추출 시도)
    if not lcls_systm1 and lcls_systm3 and len(lcls_systm3) >= 2:
        lcls_systm1 = lcls_systm3[:2]
    if lcls_systm1 and lcls_systm1 in BY_LCLS1:
        mn, mx = BY_LCLS1[lcls_systm1]
        return DwellRecommendation(mn, mx, "lcls1")

    # 4순위: content_type_id
    if content_type_id is not None and content_type_id in BY_CONTENT_TYPE:
        mn, mx = BY_CONTENT_TYPE[content_type_id]
        return DwellRecommendation(mn, mx, "content_type")

    # 5순위: 기본값
    mn, mx = DEFAULT_DWELL
    return DwellRecommendation(mn, mx, "default")
