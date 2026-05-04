"""파이프라인 QA 테스트 — xlsx 샘플 데이터로 HardFail/Warning/Score 검증."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.models import DayPlan, ItineraryPlan, PlaceInput, POI
from src.validation.hard_fail import HardFailDetector
from src.validation.warning import WarningDetector
from src.validation.scoring import ScoreCalculator

# ---------------------------------------------------------------------------
# 좌표 조회 테이블 (제주·서울 주요 관광지 / Haversine 폴백 용)
# ---------------------------------------------------------------------------

COORD_TABLE: dict[str, tuple[float, float]] = {
    # --- 제주 ---
    "제주 국제공항":           (33.5104, 126.4926),
    "함덕 해수욕장":           (33.5430, 126.6697),
    "김녕 해수욕장":           (33.5561, 126.7547),
    "월정리 해변":             (33.5605, 126.7958),
    "성산일출봉":              (33.4580, 126.9424),
    "섭지코지":                (33.4286, 126.9283),
    "우도":                    (33.5000, 126.9517),
    "오설록 티뮤지엄":         (33.3059, 126.2909),
    "협재 해수욕장":           (33.3941, 126.2397),
    "카멜리아힐":              (33.2920, 126.4057),
    "도두동 무지개 해안 도로": (33.5046, 126.4697),
    "이호테우 해변":           (33.4947, 126.4486),
    "애월 해안 도로":          (33.4611, 126.3134),
    "애월 카페 거리":          (33.4611, 126.3134),
    "서귀포 매일 올레 시장":   (33.2489, 126.5641),
    "쇠소깍":                  (33.2419, 126.6328),
    "아르떼뮤지엄 제주":       (33.4486, 126.3256),
    "새별 오름":               (33.3664, 126.2931),
    "동문 재래 시장":          (33.5126, 126.5291),
    "사려니 숲길":             (33.3726, 126.5953),
    "스누피가든":              (33.5070, 126.7250),
    "스누피 가든":             (33.5070, 126.7250),
    "높은오름":                (33.4308, 126.6489),
    "동거문오름":              (33.4180, 126.6820),
    "통오름":                  (33.3700, 126.5500),
    "신산환해장성":            (33.3400, 126.8300),
    "중문색달해수욕장":        (33.2430, 126.4110),
    "꽃귤농장":                (33.3750, 126.7200),
    "빛의 벙커":               (33.4450, 126.9210),
    "9.81파크 제주":           (33.3803, 126.3020),
    "곽지 해수욕장":           (33.4061, 126.2567),
    "산굼부리":                (33.4279, 126.6165),
    "수목원길 야시장":         (33.4892, 126.5019),
    "한라 수목원":             (33.4749, 126.4865),
    "뽀로로 앤 타요 테마 파크 제주": (33.3987, 126.2430),
    "아쿠아플라넷 제주":       (33.4333, 126.9213),
    "에코랜드":                (33.4571, 126.7016),
    "서우봉":                  (33.5465, 126.6740),
    "보롬왓":                  (33.3653, 126.7530),
    "닭머르 해안길":           (33.5600, 126.7800),
    "다려도":                  (33.5256, 126.8947),
    "너븐숭이 4.3기념관":      (33.5553, 126.7358),
    "안성리수국길":            (33.3080, 126.5800),
    "제주 추사관":             (33.2524, 126.3270),
    "박물관은살아있다 제주":   (33.2433, 126.4127),
    "중문카트체험장":          (33.2535, 126.4112),
    "소노벨 제주":             (33.2500, 126.4130),
    "씨에스 호텔 앤 리조트":   (33.4200, 126.9200),
    "세인트비치 호텔":         (33.5430, 126.6700),
    "쿠지홀리데이":            (33.5070, 126.7250),
    # --- 서울 ---
    "흰물결아트센터":          (37.5665, 126.9780),
    "반포한강공원":            (37.5069, 126.9943),
    "경복궁":                  (37.5796, 126.9770),
    "남산타워":                (37.5512, 126.9882),
    "북촌한옥마을":            (37.5826, 126.9830),
}

# 카테고리 코드 (TourAPI 대분류)
CATEGORY_MAP: dict[str, str] = {
    "해수욕장": "12", "해변": "12", "오름": "12", "숲길": "12", "해안": "12",
    "공항": "14", "박물관": "14", "기념관": "14", "미술관": "14", "뮤지엄": "14",
    "추사관": "14", "아트": "14", "문화": "14",
    "파크": "15", "카트": "15", "액티비티": "15", "오름": "15",
    "시장": "38", "마트": "38",
    "식당": "39", "카페": "39", "식탁": "39",
    "호텔": "32", "리조트": "32", "홀리데이": "32",
}

# 체류 시간 추정 (분)
DURATION_HINTS: dict[str, int] = {
    "공항": 60, "시장": 60, "카페": 60, "카페 거리": 60,
    "해수욕장": 90, "해변": 90, "오름": 90, "숲길": 90,
    "박물관": 90, "기념관": 90, "미술관": 90, "뮤지엄": 90,
    "추사관": 90, "아트": 90,
    "파크": 120, "테마 파크": 120, "카트": 90,
    "호텔": 480, "리조트": 480, "홀리데이": 480,
}


def _guess_coords(name: str) -> tuple[float, float]:
    """좌표 테이블 조회 → 없으면 제주 중심 좌표 폴백."""
    # 완전 매칭
    if name in COORD_TABLE:
        return COORD_TABLE[name]
    # 부분 매칭 (긴 키 우선)
    for key in sorted(COORD_TABLE, key=len, reverse=True):
        if key in name:
            return COORD_TABLE[key]
    return (33.4890, 126.4983)  # 제주 중심


def _guess_category(name: str) -> str:
    for kw, code in CATEGORY_MAP.items():
        if kw in name:
            return code
    return ""  # 미분류 — AREA_REVISIT 비교 대상 제외, intent vector에서 "other"로 처리


def _guess_duration(name: str) -> int:
    for kw, mins in DURATION_HINTS.items():
        if kw in name:
            return mins
    return 60


def _is_accommodation(name: str) -> bool:
    keywords = ["호텔", "리조트", "펜션", "게스트하우스", "홀리데이", "숙소"]
    return any(k in name for k in keywords)


def _parse_places(cell: str | float) -> list[str]:
    """'1.장소명, 2.장소명' → ['장소명', '장소명'] (숫자 접두사 제거)."""
    if not isinstance(cell, str):
        return []
    parts = re.split(r",\s*", cell.strip())
    names = []
    for p in parts:
        cleaned = re.sub(r"^\d+\.\s*", "", p).strip()
        if cleaned:
            names.append(cleaned)
    return names


def _trip_days(duration_str: str | float) -> int:
    if not isinstance(duration_str, str):
        return 1
    m = re.search(r"(\d+)박\s*(\d+)일", duration_str)
    if m:
        return int(m.group(2))
    if "당일" in duration_str:
        return 1
    return 1


def _party_type_from_triple(누구와: str | float) -> str:
    if not isinstance(누구와, str):
        return "친구"
    t = 누구와.lower()
    if "혼자" in t:
        return "혼자"
    if "연인" in t:
        return "연인"
    if "친구" in t:
        return "친구"
    if "아이" in t or "배우자" in t:
        return "가족"
    if "부모" in t:
        return "어르신동반"
    return "친구"


def _travel_type_from_theme(theme: str | float) -> str | None:
    if not isinstance(theme, str):
        return None
    if "문화" in theme or "역사" in theme:
        return "cultural"
    if "산" in theme or "바다" in theme or "자연" in theme:
        return "nature"
    if "쇼핑" in theme:
        return "shopping"
    if "먹방" in theme or "음식" in theme:
        return "food"
    if "액티비티" in theme or "체험" in theme or "테마" in theme:
        return "adventure"
    return None


def _make_poi(name: str, is_accom: bool = False) -> POI:
    lat, lng = _guess_coords(name)
    category = "32" if is_accom else _guess_category(name)
    duration = 480 if is_accom else _guess_duration(name)
    open_s = "00:00" if is_accom else "09:00"
    open_e = "23:59" if is_accom else "18:00"
    return POI(
        poi_id=name[:20],
        name=name,
        lat=lat,
        lng=lng,
        open_start=open_s,
        open_end=open_e,
        duration_min=duration,
        category=category,
    )


# ---------------------------------------------------------------------------
# xlsx 파서
# ---------------------------------------------------------------------------

def load_gugseok(path: str, n_samples: int = 3) -> list[dict]:
    """구석구석 xlsx → 샘플 ItineraryPlan 재료 목록."""
    df = pd.read_excel(path, header=3)
    results = []
    current: dict = {}

    for _, row in df.iterrows():
        rec_no = row.get("추천")
        if pd.notna(rec_no):  # 새 추천 시작
            if current and current.get("days"):
                results.append(current)
                if len(results) >= n_samples:
                    break
            day_cols = [c for c in df.columns if str(c).startswith("DAY")]
            day_names: list[list[str]] = [_parse_places(row.get(c, "")) for c in day_cols]
            current = {
                "source": "구석구석",
                "id": int(rec_no),
                "region": str(row.get("지역", "")),
                "duration": str(row.get("여행 기간", "")),
                "theme": str(row.get("테마", "")),
                "type": str(row.get("항목", "")),
                "days": day_names,
                "days_accom": [[] for _ in day_cols],
            }
        elif current:
            항목 = str(row.get("항목", ""))
            if 항목 == "숙소":
                day_cols = [c for c in df.columns if str(c).startswith("DAY")]
                for di, c in enumerate(day_cols):
                    names = _parse_places(row.get(c, ""))
                    current["days_accom"][di].extend(names)

    if current and current.get("days"):
        results.append(current)
    return results[:n_samples]


def load_triple(path: str, n_samples: int = 3) -> list[dict]:
    """트리플 xlsx → 샘플 ItineraryPlan 재료 목록."""
    df = pd.read_excel(path, header=10)
    korean = df[df["나라"] == "대한민국"].reset_index(drop=True)
    day_cols = [c for c in df.columns if str(c).startswith("DAY")]
    results = []

    for _, row in korean.iterrows():
        day_names = [_parse_places(row.get(c, "")) for c in day_cols]
        if not any(day_names):
            continue
        results.append({
            "source": "트리플",
            "id": int(row.get("추천", 0)),
            "region": str(row.get("도시", "")),
            "duration": str(row.get("여행 기간", "")),
            "theme": str(row.get("내가 선호하는 여행 스타일 (다중 선택 가능)", "")),
            "누구와": str(row.get("누구와 (다중 선택 가능)", "")),
            "days": day_names,
            "days_accom": [[] for _ in day_cols],
        })
        if len(results) >= n_samples:
            break
    return results


def _build_itinerary(sample: dict) -> tuple[ItineraryPlan, list[list[POI]]]:
    """샘플 dict → (ItineraryPlan, per-day POI lists).

    다일(multi-day) 연속성: Day N 의 마지막 숙소(category="32")를
    Day N+1 의 첫 POI 로 삽입해 아침 출발 이동 시간을 계산에 반영한다.
    """
    source = sample["source"]
    duration_str = sample["duration"]
    n_days = _trip_days(duration_str)

    party_type = (
        _party_type_from_triple(sample.get("누구와", ""))
        if source == "트리플"
        else "친구"
    )
    travel_type = _travel_type_from_theme(sample.get("theme", ""))

    day_plans: list[DayPlan] = []
    per_day_pois: list[list[POI]] = []
    day_last_accom: list[POI | None] = []  # 각 날의 마지막 숙소 추적

    for day_idx in range(n_days):
        place_names = sample["days"][day_idx] if day_idx < len(sample["days"]) else []
        accom_names = (
            sample["days_accom"][day_idx]
            if day_idx < len(sample.get("days_accom", []))
            else []
        )

        all_names = [(n, False) for n in place_names] + [(n, True) for n in accom_names]
        if not all_names:
            day_last_accom.append(None)
            continue

        places = [PlaceInput(name=n, is_accommodation=is_ac) for n, is_ac in all_names]
        pois = [_make_poi(n, is_ac) for n, is_ac in all_names]

        day_plans.append(DayPlan(places=places))
        per_day_pois.append(pois)

        # 이 날의 마지막 숙소 POI 기록 (category=="32")
        last_accom = next((p for p in reversed(pois) if p.category == "32"), None)
        day_last_accom.append(last_accom)

    if not day_plans:
        day_plans.append(DayPlan(places=[PlaceInput(name="_dummy")]))
        per_day_pois.append([_make_poi("_dummy")])
        day_last_accom.append(None)

    # 다일 depot 연결: Day N+1 앞에 Day N 숙소의 "출발지" POI 삽입
    for day_idx in range(1, len(per_day_pois)):
        prev_accom = day_last_accom[day_idx - 1]
        if prev_accom is not None:
            checkout = POI(
                poi_id=f"dep_{prev_accom.poi_id[:8]}",
                name=f"(출발) {prev_accom.name[:14]}",
                lat=prev_accom.lat,
                lng=prev_accom.lng,
                open_start="08:30",
                open_end="09:30",
                duration_min=30,
                category="32",
            )
            per_day_pois[day_idx].insert(0, checkout)

    plan = ItineraryPlan(
        days=day_plans,
        party_size=2,
        party_type=party_type,
        travel_type=travel_type,
        date="2026-06-01",
    )
    return plan, per_day_pois


# ---------------------------------------------------------------------------
# 파이프라인 실행 + 출력
# ---------------------------------------------------------------------------

def run_pipeline(sample: dict) -> None:
    print("=" * 70)
    src = sample["source"]
    print(f"[{src}] 추천#{sample['id']} — {sample['region']} / {sample['duration']}")
    print(f"  테마: {sample.get('theme', '-')}  |  누구와: {sample.get('누구와', '친구')}")

    plan, per_day_pois = _build_itinerary(sample)
    print(f"  party_type={plan.party_type}  travel_type={plan.travel_type}  travel_days={plan.travel_days}")
    print()

    detector_hf = HardFailDetector()
    detector_warn = WarningDetector()
    scorer = ScoreCalculator()

    all_hard_fails = []
    all_warnings = []
    all_scores = []

    for day_idx, pois in enumerate(per_day_pois):
        day_plan = ItineraryPlan(
            days=[plan.days[day_idx]],
            party_size=plan.party_size,
            party_type=plan.party_type,
            travel_type=plan.travel_type,
            date="2026-06-01",
        )
        matrix: dict = {}

        hf = detector_hf.detect(day_plan, pois, matrix)
        warns = detector_warn.detect(day_plan, pois, matrix)
        scores, final = scorer.compute(day_plan, pois, matrix, hf)
        all_hard_fails.extend(hf)
        all_warnings.extend(warns)
        all_scores.append((day_idx + 1, final, scores))

        place_str = " → ".join(p.name for p in pois)
        print(f"  Day{day_idx + 1}: {place_str}")
        print(f"    점수={final}  efficiency={scores.efficiency:.2f}  feasibility={scores.feasibility:.2f}  purpose_fit={scores.purpose_fit:.2f}  flow={scores.flow:.2f}  area_intensity={scores.area_intensity:.2f}")

        if hf:
            for f in hf:
                print(f"    [HARD FAIL] {f.fail_type}: {f.message[:80]}")
        if warns:
            for w in warns:
                print(f"    [WARN] {w.warning_type} ({w.confidence}): {w.message[:80]}")
        if not hf and not warns:
            print("    → 이상 없음")

    print()
    print(f"  요약: HardFail={len(all_hard_fails)} | Warning={len(all_warnings)} | 평균점수={sum(s for _, s, _ in all_scores) // max(1, len(all_scores))}")


def main() -> None:
    base = Path(__file__).parent.parent / "phases" / "0-setup"
    gug_path = str(base / "대한민국 구석구석 추천 경로.xlsx")
    triple_path = str(base / "트리플 여행 추천 경로.xlsx")

    print("▶ 구석구석 샘플 3건")
    print()
    for sample in load_gugseok(gug_path, n_samples=3):
        run_pipeline(sample)

    print()
    print("▶ 트리플 샘플 3건")
    print()
    for sample in load_triple(triple_path, n_samples=3):
        run_pipeline(sample)


if __name__ == "__main__":
    main()
