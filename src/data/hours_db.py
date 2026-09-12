"""hours_db — 카테고리·키워드 기반 운영시간 룩업.

사용:
    from src.data.hours_db import resolve_hours
    spec = resolve_hours("경복궁", "관광지")
    # spec.open_, spec.close_, spec.off_days, spec.break_start, spec.break_end
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HoursSpec:
    label: str
    open_: str
    close_: str
    break_start: str | None = None
    break_end: str | None = None
    off_days: list[int] = field(default_factory=list)  # 0=월, ..., 6=일


# ── 카테고리 표준값 (category_hours.xlsx 와 동기화) ──────────
SUB_CATEGORIES: dict[str, HoursSpec] = {
    "nature_outdoor": HoursSpec(
        label="자연 · 산·해변·공원",
        open_="00:00",
        close_="23:59",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "palace": HoursSpec(
        label="궁궐 · 종묘",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[1],
    ),
    "tomb_historic": HoursSpec(
        label="왕릉 · 유적지 · 성곽",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[0],
    ),
    "temple": HoursSpec(
        label="사찰 · 사찰림",
        open_="04:00",
        close_="19:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "traditional_village": HoursSpec(
        label="한옥마을 · 민속촌",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "street_plaza": HoursSpec(
        label="거리 · 광장 · 골목",
        open_="00:00",
        close_="23:59",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "market_traditional": HoursSpec(
        label="전통시장",
        open_="09:00",
        close_="21:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "market_seafood": HoursSpec(
        label="수산시장",
        open_="04:00",
        close_="21:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "night_market": HoursSpec(
        label="야시장",
        open_="18:00",
        close_="23:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "tower_observatory": HoursSpec(
        label="타워 · 전망대",
        open_="10:00",
        close_="22:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "museum": HoursSpec(
        label="박물관 · 미술관 · 기념관",
        open_="10:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[0],
    ),
    "library_culture_center": HoursSpec(
        label="도서관 · 문화회관",
        open_="09:00",
        close_="21:00",
        break_start=None,
        break_end=None,
        off_days=[0],
    ),
    "theme_park": HoursSpec(
        label="테마파크 · 놀이공원",
        open_="10:00",
        close_="22:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "aquarium_zoo": HoursSpec(
        label="수족관 · 동물원",
        open_="09:30",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "korean_restaurant": HoursSpec(
        label="한식당",
        open_="11:00",
        close_="21:30",
        break_start="15:00",
        break_end="17:00",
        off_days=[],
    ),
    "bbq_restaurant": HoursSpec(
        label="고기집 · 바비큐",
        open_="11:30",
        close_="23:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "noodle_restaurant": HoursSpec(
        label="면 · 분식",
        open_="10:30",
        close_="21:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "general_restaurant": HoursSpec(
        label="일반 식당",
        open_="11:00",
        close_="21:00",
        break_start="15:00",
        break_end="17:00",
        off_days=[],
    ),
    "cafe": HoursSpec(
        label="카페 · 디저트",
        open_="09:00",
        close_="22:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "bakery": HoursSpec(
        label="베이커리",
        open_="08:00",
        close_="21:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "department_store": HoursSpec(
        label="백화점 · 쇼핑몰",
        open_="10:30",
        close_="20:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "outlet": HoursSpec(
        label="아울렛",
        open_="10:30",
        close_="21:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "leisure_sport": HoursSpec(
        label="레포츠 · 체험",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "lodging": HoursSpec(
        label="숙박",
        open_="00:00",
        close_="23:59",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "religious_site": HoursSpec(
        label="성당 · 교회",
        open_="06:00",
        close_="21:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "scenic_spot": HoursSpec(
        label="명승지 · 절경",
        open_="00:00",
        close_="23:59",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "cave": HoursSpec(
        label="동굴 (관광)",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "cable_car": HoursSpec(
        label="케이블카 · 모노레일",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "ranch_farm": HoursSpec(
        label="목장 · 체험농장",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
    "default_attraction": HoursSpec(
        label="기타 관광지 (미분류)",
        open_="09:00",
        close_="18:00",
        break_start=None,
        break_end=None,
        off_days=[],
    ),
}

# ── 키워드 → sub_category 매칭 룰 (위에서 아래로 평가) ───────
KEYWORD_RULES: list[tuple[str, str]] = [
    (
        "봉은사|해동용궁사|불국사|석굴암|낙산사|월정사|향일암|선암사|구인사|마곡사|전등사|진관사|용궁사|부석사|보리암|쌍계사|선운사|용문사|해인사|통도사|범어사|송광사|법주사|미황사|화엄사|쌍봉사|운주사|금산사|내장사|관음사|약천사|약사사|봉정사|봉선사|적천사|자장사|봉선사|동학사|갑사|마이산탑사|청룡사|봉선사|관룡사|사불산|불교문화관",
        "temple",
    ),
    (
        "만장굴|고씨굴|천지연.*동굴|화암동굴|단양고수동굴|고수동굴|환선굴|여천굴|동굴$|관광동굴|대금굴|해저터널|관광터널",
        "cave",
    ),
    ("케이블카|모노레일|곤돌라|로프웨이|루지$|짚라인|집라인|레일바이크", "cable_car"),
    ("목장|양떼목장|허브농장|농원$|체험농장|승마장", "ranch_farm"),
    (
        "산$|^[가-힣]+산\\s|산림욕|봉우리|봉$|폭포|계곡|숲$|호수|호$|강$|바다|해수욕장|해변$|해안|해변로|해돋이|일출|일몰|만$|곶$|섬$|비치$|^.+도$|^오동도|^외도|^청산도|^보길도|^외연도|^안면도|^거문도|^월미도|^남이섬|공원|숲길|올레|둘레길|등산로|언덕|고개|평원|벌판|초원|꽃밭|들꽃|수목원|식물원|지질공원|자연휴양림|휴양림|자연공원|국립공원|도립공원|가든|편백|편백숲|핀크스|메타세콰이어|소쇄원|죽녹원|관방제림|보성녹차밭|녹차밭|식물원|저수지$|^.+호$|의림지|화진포|두물머리|세미원|태화강국가정원|방조림|어부림|^.+림$|불광천|청계천|^.+천$|동촌유원지|유원지$",
        "nature_outdoor",
    ),
    (
        "낙화암|외돌개|주상절리|정방폭포|천지연|용두암|섭지코지|성산일출봉|비자림|사려니숲|에코랜드|카멜리아힐|선유도|영금정|공지천|경포대|정동진|월정리|함덕|애월|순천만습지|순천만|우포늪|화담숲|아침고요|남이섬|쁘띠프랑스|대왕암|간절곶|호미곶|가천다랭이|용궁리|섭지|올레길|둘레길|태종대|갓바위|신선대|촛대바위|하조대|화진포|정선아우라지|탄금대|통일전망대|묵호항|구룡포항|항구$",
        "scenic_spot",
    ),
    ("경복궁|창덕궁|창경궁|덕수궁|경희궁|운현궁|종묘", "palace"),
    (
        "왕릉|^선릉|^정릉|^태릉|^홍릉|^동구릉|능원|능$|고분|고도$|유적|유적지|읍성|산성|토성|주성|남한산성|북한산성|고려궁지|문화유산|서원$|향교$|선비촌|경기전|오죽헌|동궁과월지|대릉원|노서리|쪽샘|첨성대|오목대|월영교|수원화성|행궁$|행궁가|^.+문$|숭례문|흥인지문|독립문|광화문|풍남문|팔달문|장안문|동대문$|남대문$|^.+루$|광한루|촉석루|죽서루|만대루|영남루|^.+사지$|정림사지",
        "tomb_historic",
    ),
    (
        "한옥마을|민속촌|전통마을|민속마을|문화마을|북촌$|서촌$|감천문화마을|양동마을|하회마을|외암마을|왕곡마을|전주한옥|전주한옥마을",
        "traditional_village",
    ),
    ("야시장|밤시장", "night_market"),
    ("수산시장|어시장|자갈치|소래포구|구룡포|주문진|속초중앙시장.*어시장", "market_seafood"),
    (
        "시장$|전통시장|광장시장|남대문시장|동대문시장|통인시장|망원시장|국제시장|부평시장|중앙시장|BIFF광장|깡통시장|남포동$",
        "market_traditional",
    ),
    (
        "백화점|면세점|쇼핑몰|몰$|복합쇼핑|스타필드|이마트|코엑스|롯데월드몰|가로수길.*몰|타임스퀘어|디큐브|디큐브시티|롯데몰|현대시티몰",
        "department_store",
    ),
    ("아울렛|프리미엄아울렛|시즌아울렛", "outlet"),
    (
        "광화문|시청$|청계천|성수동|연남동|이태원|망원동|북촌$|서촌$|을지로$|가로수길|경리단길|샤로수길|망원|연희동|인사동|삼청동|익선동|서순라길|남대문로|홍대|홍익대|건대$|건대거리|신촌$|해방촌|용산공예단지|부산.*해리단길|해리단길|제주.*탑동|탑동광장",
        "street_plaza",
    ),
    (
        "거리$|^.+거리\\s|^.+로$|^.+길$|골목$|광장$|마을$|동네|로데오|단지$|상점가|쇼핑거리|먹자골목|예술의거리|벽화마을",
        "street_plaza",
    ),
    ("타워|전망대|뷰포인트|스카이|루프탑|전망$|^N서울|남산서울타워", "tower_observatory"),
    (
        "박물관|미술관|뮤지엄|museum|기념관|아트센터|아트홀|문학관|역사관|체험관|과학관|전시관|갤러리|예술관|디자인플라자|DDP|테디베어|티뮤지엄|오설록|스페이스워크|아트밸리|포천아트밸리",
        "museum",
    ),
    ("도서관|문화회관|문화원|아트빌리지|예술의전당", "library_culture_center"),
    (
        "에버랜드|롯데월드$|레전드$|월드$|테마파크|놀이공원|랜드$|어드벤처|한국민속촌|드림랜드|월미테마파크",
        "theme_park",
    ),
    ("아쿠아리움|수족관|아쿠아|씨라이프|동물원|사파리|아쿠아필드", "aquarium_zoo"),
    ("성당$|교회$|채플|수도원|^명동성당|약현성당|중림동성당", "religious_site"),
    ("갈비|삼겹살|돼지|소고기|등심|안심|불고기|고기집|숯불|화로구이", "bbq_restaurant"),
    ("국밥|순대|냉면|국수|면옥|분식|떡볶이|김밥|만두|짜장면|짬뽕", "noodle_restaurant"),
    (
        "한정식|한식|삼계탕|곰탕|설렁탕|족발|보쌈|닭갈비|찜닭|토속촌|광장시장.*빈대떡|마약김밥",
        "korean_restaurant",
    ),
    ("베이커리|빵집|제과|제빵|베이글", "bakery"),
    ("카페|커피|coffee|디저트|아이스크림|티하우스|찻집|밀크티", "cafe"),
    (
        "패러글라이딩|서핑|스쿠버|스키장|스키리조트|보드|짚라인|루지|카약|요트|보트|승마|승마장|스카이다이빙|번지점프|체험$|온천$|^.+온천|유성온천|수안보온천|온천랜드|찜질방|스파$|녹차탕|해수탕|^.+탕$|율포해수녹차탕",
        "leisure_sport",
    ),
    ("리조트|호텔|콘도|풀빌라|펜션|모텔|게스트하우스|^워커힐$|^.+호텔$|^.+리조트$", "lodging"),
    ("다리$|^.+다리$|^.+교$|엑스포다리|영도대교|광안대교|새천년대교", "street_plaza"),
    (
        "차이나타운|이태원로|용산기지|양림동|예술촌|아트빌리지|아트밸리|아트타운|예술마을|예술의거리|벽화마을|창동예술촌",
        "street_plaza",
    ),
    ("63빌딩|타워팰리스|롯데월드타워|광화빌딩|^.+빌딩$|광화문빌딩", "tower_observatory"),
    (
        "^.+촌$|선비촌|민속촌|국악촌|문학촌|최참판댁|^.+댁$|^.+종가$|^.+고택$|^.+가옥$",
        "traditional_village",
    ),
]


def resolve_hours(name: str, hint: str | None = None) -> HoursSpec:
    """장소 이름 + 카테고리힌트 → HoursSpec.

    매칭 우선순위: 키워드 > 카테고리힌트 > default_attraction.
    """
    name_clean = (name or "").replace(" ", "")
    for pattern, sub in KEYWORD_RULES:
        if re.search(pattern, name_clean):
            return SUB_CATEGORIES[sub]

    h = (hint or "").strip()
    fallback = {
        "식당": "general_restaurant",
        "카페": "cafe",
        "문화시설": "museum",
        "쇼핑": "department_store",
        "레포츠": "leisure_sport",
        "축제": "default_attraction",
    }.get(h, "default_attraction")
    return SUB_CATEGORIES[fallback]


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def is_open_at(spec: HoursSpec, weekday: int, hhmm: str) -> bool:
    """주어진 요일·시각에 영업 중인지 (주의: 휴무일 + 브레이크 타임 고려)."""
    if weekday in spec.off_days:
        return False
    t = to_minutes(hhmm)
    if not (to_minutes(spec.open_) <= t <= to_minutes(spec.close_)):
        return False
    if spec.break_start and spec.break_end:
        if to_minutes(spec.break_start) <= t < to_minutes(spec.break_end):
            return False
    return True


__all__ = ["HoursSpec", "SUB_CATEGORIES", "KEYWORD_RULES", "resolve_hours", "is_open_at"]
