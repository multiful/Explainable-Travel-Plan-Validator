"""테마 분류 체계 (2축 18테마).

축 A: PLACE_TYPES   (9개) — 장소 유형 (산, 바다, 카페 등 구체적)
축 B: TRAVEL_STYLES (9개) — 여행 스타일 (힐링, 액티비티 등 추상적)

PLACE_TYPE은 lclsSystm 코드와 휴리스틱 매핑 (rule-based 검증용).
TRAVEL_STYLE은 매핑하지 않음 — LLM 판정에만 사용.

사용자 입력 모델은 UserPreferences로 묶어서 양 축 다중 선택을 허용.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── 축 A: 장소 유형 (List 1) ──────────────────────────────────────────
PLACE_TYPES: list[str] = [
    "산",
    "바다",
    "실내 여행지",
    "액티비티",
    "문화_역사",
    "테마파크",
    "카페",
    "전통시장",
    "축제",
]

# ── 축 B: 여행 스타일 (List 2) ────────────────────────────────────────
TRAVEL_STYLES: list[str] = [
    "체험_액티비티",
    "SNS 핫플레이스",
    "자연과 함께",
    "유명 관광지는 필수",
    "여유롭게 힐링",
    "문화_예술_역사",
    "여행지 느낌 물씬",
    "쇼핑은 열정적으로",
    "관광보다 먹방",
]


# ── PLACE_TYPE → lclsSystm 코드 prefix 매핑 ──────────────────────────
# 한 PLACE_TYPE에 여러 코드가 매핑될 수 있음 (OR 조건).
# 매핑은 코드의 prefix 매칭 (예: "NA04" → 산 → 모든 NA04로 시작하는 코드)
PLACE_TYPE_TO_LCLS: dict[str, list[str]] = {
    "산": ["NA04", "NA01"],  # 산, 국립공원
    "바다": ["NA12", "NA11", "NA13", "NA14"],  # 해수욕장, 해안절경, 섬, 항구
    "실내 여행지": ["VE01", "VE03", "VE04", "VE05"],  # 박물관, 전시관, 미술관, 체험관
    "액티비티": ["EX"],  # 레포츠 전체
    "문화_역사": ["VE01", "VE02", "HS"],  # 박물관, 기념관, 역사관광지
    "테마파크": ["EX21"],  # 테마파크 (레포츠 하위)
    "카페": ["FD02"],  # 카페·전통찻집
    "전통시장": ["SH01"],  # 5일·전통시장
    "축제": [],  # contentTypeId=15로 별도 매칭
}


# ── 축제는 contentTypeId 기반 ─────────────────────────────────────────
PLACE_TYPE_TO_CONTENT_TYPE: dict[str, list[int]] = {
    "축제": [15],
}


# ── TRAVEL_STYLE 메타 정보 (LLM 프롬프트 컨텍스트용) ─────────────────
# 각 스타일에 대한 한 줄 설명 — Claude API 호출 시 system 또는 user 프롬프트에 포함
TRAVEL_STYLE_DESCRIPTIONS: dict[str, str] = {
    "체험_액티비티": "직접 몸으로 부딪히는 체험형 활동 (서핑, 등산, ATV 등)",
    "SNS 핫플레이스": "사진 찍기 좋고 트렌디한 곳 (인스타 감성 카페, 포토존)",
    "자연과 함께": "자연 풍경 중심 (산, 바다, 숲, 공원)",
    "유명 관광지는 필수": "랜드마크·필수 코스 (경복궁, 해운대 등)",
    "여유롭게 힐링": "조용하고 편안한 휴식 (한적한 카페, 명상, 온천)",
    "문화_예술_역사": "박물관·미술관·고궁·전통 문화 체험",
    "여행지 느낌 물씬": "그 지역 고유의 분위기·전통 강하게 살아있는 곳",
    "쇼핑은 열정적으로": "쇼핑 위주 (백화점, 면세점, 시장, 쇼핑몰)",
    "관광보다 먹방": "유명 맛집·식도락 위주 (현지 음식, 노포)",
}


# ── 사용자 입력 모델 ──────────────────────────────────────────────────
@dataclass
class UserPreferences:
    """사용자가 선택한 테마. 두 축 모두 다중 선택 허용 (각 1개 이상)."""

    place_types: list[str] = field(default_factory=list)
    travel_styles: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 검증: 모든 항목이 정의된 테마인지 확인
        invalid_pt = [p for p in self.place_types if p not in PLACE_TYPES]
        if invalid_pt:
            raise ValueError(f"정의되지 않은 PLACE_TYPE: {invalid_pt}. 허용: {PLACE_TYPES}")
        invalid_ts = [s for s in self.travel_styles if s not in TRAVEL_STYLES]
        if invalid_ts:
            raise ValueError(f"정의되지 않은 TRAVEL_STYLE: {invalid_ts}. 허용: {TRAVEL_STYLES}")
        if not self.place_types and not self.travel_styles:
            raise ValueError("최소 하나의 PLACE_TYPE 또는 TRAVEL_STYLE을 선택해야 합니다.")

    def all_themes(self) -> list[str]:
        """두 축의 선택을 평탄화 (LLM 프롬프트용)."""
        return self.place_types + self.travel_styles


# ── PLACE_TYPE 매칭 유틸 (rule-based 빠른 필터) ──────────────────────
def matches_place_type(
    place_type: str,
    lcls_systm3: str | None = None,
    content_type_id: int | None = None,
) -> bool:
    """주어진 lcls_systm3 또는 content_type_id가 place_type에 부합하는지 판정.

    예) matches_place_type("산", lcls_systm3="NA0401")  → True
        matches_place_type("축제", content_type_id=15)  → True
    """
    if place_type not in PLACE_TYPES:
        return False

    # contentType 기반 매칭 (축제 등)
    if content_type_id is not None:
        ct_list = PLACE_TYPE_TO_CONTENT_TYPE.get(place_type, [])
        if content_type_id in ct_list:
            return True

    # lclsSystm prefix 기반 매칭
    if lcls_systm3:
        prefixes = PLACE_TYPE_TO_LCLS.get(place_type, [])
        for prefix in prefixes:
            if lcls_systm3.startswith(prefix):
                return True

    return False


def get_place_types_for(
    lcls_systm3: str | None = None,
    content_type_id: int | None = None,
) -> list[str]:
    """주어진 코드가 매칭되는 모든 PLACE_TYPE 반환 (한 POI가 여러 유형에 속할 수 있음)."""
    matched = []
    for pt in PLACE_TYPES:
        if matches_place_type(pt, lcls_systm3, content_type_id):
            matched.append(pt)
    return matched
