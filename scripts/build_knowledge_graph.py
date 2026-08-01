#!/usr/bin/env python3
"""제주특별자치도_통합.xlsx → data_construct.md 스키마 기반 지식그래프 CSV 빌더.

`신분류체계정보 관광타입정보 연계 정의서.xlsx`(국문 매뉴얼 부속 카테고리표)로
소분류(신) 코드를 관광타입명(구분류체계: 음식점/숙박/관광지/문화시설/레포츠/쇼핑 등)에
매핑하고, Place/Region/Category 노드와 IS_LOCATED_IN/PART_OF/HAS_CATEGORY/NEAR_BY
관계를 Neo4j `neo4j-admin database import` 호환 CSV로 data/graph/ 에 출력한다.

원본 xlsx에 없는 데이터(Theme/Audience/business_hours/off_days, Itinerary/Visit)는
만들어내지 않고 건너뛴다 — data_construct.md "5. 현재 데이터 상태" 참고.

Usage:
    python scripts/build_knowledge_graph.py
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).parent.parent
PLACE_XLSX = ROOT / "제주특별자치도_통합.xlsx"
CATEGORY_XLSX = ROOT / "신분류체계정보 관광타입정보 연계 정의서.xlsx"
OUT_DIR = ROOT / "data" / "graph"

NEAR_BY_RADIUS_M = 300
# Aura Free 관계 400,000개 하드캡: 나머지 관계(IS_LOCATED_IN+PART_OF+HAS_CATEGORY)
# 50,831개를 뺀 예산 349,169 안에 들어오도록 Top-K를 낮춰서 맞춘다.
NEAR_BY_TOP_K = 16
WALK_SPEED_M_PER_MIN = 75  # 300m ≈ 도보 4분 (data_construct.md 근거)

PLACE_TYPE_BY_MAJOR = {
    "FD": "RESTAURANT",
    "AC": "ACCOMMODATION",
    "SH": "ACTIVITY",
    "VE": "ACTIVITY",  # 리조트류만 예외 (아래 _place_type 참고)
    "LS": "ACTIVITY",
    "EX": "ACTIVITY",
    "HS": "ACTIVITY",
}

# 원본 데이터에 존재하지만 카테고리 연계 정의서(240개 리프)에는 없는 소분류코드.
# 상위 대분류명 기준 상식적으로 귀속되는 관광타입명을 수동 지정한다.
CATEGORY_GROUP_OVERRIDE = {
    "AC999900": "숙박",
    "FD019900": "음식점",
    "FD999900": "음식점",
}

CITY_RE = re.compile(r"(제주시|서귀포시)")
EUPMYEON_RE = re.compile(r"(제주시|서귀포시)\s+(\S+?(?:읍|면))\b")
PAREN_DONG_RE = re.compile(r"\(([가-힣0-9]+동)[,\)]")
BARE_DONG_RE = re.compile(r"(제주시|서귀포시)\s+([가-힣]+동)\b")


def _place_type(major_code: str, medium_name: str, minor_name: str) -> str:
    if major_code == "VE" and ("리조트" in (medium_name or "") or "리조트" in (minor_name or "")):
        return "ACCOMMODATION"
    return PLACE_TYPE_BY_MAJOR.get(major_code, "ACTIVITY")


def _parse_region_chain(address: str) -> list[tuple[str, str]]:
    """주소 → [(id, name), ...] 최상위(읍/면/동 또는 시) → 시 → 도 순서.

    반환 리스트의 첫 항목이 Place가 IS_LOCATED_IN으로 연결될 가장 구체적인 Region.
    """
    city_m = CITY_RE.search(address or "")
    if not city_m:
        return [("jeju_do", "제주도")]

    city_name = city_m.group(1)
    city_id = "jeju_si" if city_name == "제주시" else "seogwipo_si"
    chain = [(city_id, city_name), ("jeju_do", "제주도")]

    sub = None
    m = EUPMYEON_RE.search(address)
    if m:
        sub = m.group(2)
    else:
        m = PAREN_DONG_RE.search(address)
        if m:
            sub = m.group(1)
        else:
            m = BARE_DONG_RE.search(address)
            if m:
                sub = m.group(2)

    if sub:
        sub_id = f"{city_id}__{sub}"
        chain.insert(0, (sub_id, sub))

    return chain


def _load_category_group_map() -> dict[str, str]:
    raw = pd.read_excel(CATEGORY_XLSX, sheet_name=0, header=None)
    tbl = raw.iloc[5:, 0:9].copy()
    tbl.columns = [
        "대분류코드", "대분류명", "중분류코드", "중분류명",
        "소분류코드", "소분류명", "국문코드", "다국어코드", "관광타입명",
    ]
    tbl = tbl.dropna(subset=["소분류코드"])
    group_map = dict(zip(tbl["소분류코드"], tbl["관광타입명"], strict=True))
    group_map.update(CATEGORY_GROUP_OVERRIDE)
    return group_map


def _project_meters(lat: np.ndarray, lng: np.ndarray) -> np.ndarray:
    """소범위(제주도)용 등장방형 투영 — 300m 스케일에서 오차 무시 가능."""
    lat0 = math.radians(float(np.mean(lat)))
    x = lng * 111_320 * math.cos(lat0)
    y = lat * 110_540
    return np.column_stack([x, y])


def build_near_by(places: pd.DataFrame) -> pd.DataFrame:
    coords_df = places.dropna(subset=["lat", "lng"])
    xy = _project_meters(coords_df["lat"].to_numpy(), coords_df["lng"].to_numpy())
    ids = coords_df["id"].to_numpy()

    tree = cKDTree(xy)
    pairs = tree.query_pairs(r=NEAR_BY_RADIUS_M, output_type="ndarray")

    # query_pairs는 무방향 쌍(i<j) 1회만 반환 → 양방향 후보로 펼친 뒤 head별 Top-20 컷.
    dist = np.linalg.norm(xy[pairs[:, 0]] - xy[pairs[:, 1]], axis=1)
    fwd = np.column_stack([pairs[:, 0], pairs[:, 1], dist])
    bwd = np.column_stack([pairs[:, 1], pairs[:, 0], dist])
    edges = np.vstack([fwd, bwd])

    df = pd.DataFrame(edges, columns=["head_idx", "tail_idx", "distance_m"])
    df["head_idx"] = df["head_idx"].astype(int)
    df["tail_idx"] = df["tail_idx"].astype(int)
    df = df.sort_values(["head_idx", "distance_m"]).groupby("head_idx").head(NEAR_BY_TOP_K)

    df[":START_ID"] = ids[df["head_idx"].to_numpy()]
    df[":END_ID"] = ids[df["tail_idx"].to_numpy()]
    df["distance_m:float"] = df["distance_m"].round(1)
    df["walk_min:int"] = np.maximum(1, np.round(df["distance_m"] / WALK_SPEED_M_PER_MIN)).astype(int)
    df[":TYPE"] = "NEAR_BY"

    isolated = coords_df["id"].nunique() - df[":START_ID"].nunique()
    capped = (df.groupby(":START_ID").size() == NEAR_BY_TOP_K).sum()
    print(f"  NEAR_BY: 좌표 보유 {len(coords_df)}건 중 고립 노드 {isolated}건, "
          f"캡(={NEAR_BY_TOP_K}) 도달 {capped}건, 총 엣지 {len(df)}개")

    return df[[":START_ID", ":END_ID", "distance_m:float", "walk_min:int", ":TYPE"]]


def _selfcheck() -> None:
    assert _place_type("FD", "한식", "한식(일반)") == "RESTAURANT"
    assert _place_type("VE", "복합관광시설", "리조트") == "ACCOMMODATION"
    assert _place_type("VE", "공연시설", "공연장") == "ACTIVITY"

    chain = _parse_region_chain("제주특별자치도 제주시 한림읍 한림로 247, 2층")
    assert [n for _, n in chain] == ["한림읍", "제주시", "제주도"], chain

    chain = _parse_region_chain("제주특별자치도 제주시 항골남길 46, 1층 (이호일동)")
    assert [n for _, n in chain] == ["이호일동", "제주시", "제주도"], chain

    chain = _parse_region_chain("제주특별자치도 제주시 신대로 60")
    assert [n for _, n in chain] == ["제주시", "제주도"], chain
    print("  self-check 통과")


def main() -> None:
    print("[0/5] self-check")
    _selfcheck()

    print("[1/5] 원본 로드")
    places_raw = pd.read_excel(PLACE_XLSX)
    group_map = _load_category_group_map()

    print("[2/5] Place / Category 구성")
    places_raw["place_id"] = "kakao_" + places_raw["ID"].astype(str)
    places_raw["place_type"] = places_raw.apply(
        lambda r: _place_type(r["대분류코드"], r["중분류명"], r["소분류명"]), axis=1
    )
    places_raw["category_group"] = places_raw["소분류코드"].map(group_map)
    unmapped = places_raw.loc[places_raw["category_group"].isna(), "소분류코드"].unique()
    if len(unmapped):
        print(f"  경고: 관광타입명 매핑 실패 소분류코드 {list(unmapped)} (group 값 비움)")

    place_nodes = pd.DataFrame({
        "id:ID": places_raw["place_id"],
        "name": places_raw["상호명"],
        "place_type": places_raw["place_type"],
        "category_major_code": places_raw["대분류코드"],
        "category_major_name": places_raw["대분류명"],
        "category_medium_code": places_raw["중분류코드"],
        "category_medium_name": places_raw["중분류명"],
        "address": places_raw["도로명주소"].fillna(""),
        "lat:float": places_raw["위도"],
        "lng:float": places_raw["경도"],
        "business_hours": "",  # 원본에 없음 — data_construct.md 5절 참고
        "off_days": "",        # 원본에 없음
        ":LABEL": "Place",
    })

    category_nodes = (
        places_raw[["소분류코드", "소분류명", "category_group"]]
        .drop_duplicates(subset=["소분류코드"])
        .rename(columns={"소분류코드": "code:ID", "소분류명": "name", "category_group": "group"})
    )
    category_nodes[":LABEL"] = "Category"

    rel_has_category = pd.DataFrame({
        ":START_ID": places_raw["place_id"],
        ":END_ID": places_raw["소분류코드"],
        ":TYPE": "HAS_CATEGORY",
    })

    print("[3/5] Region 구성 (주소 파싱)")
    chains = places_raw["도로명주소"].fillna("").map(_parse_region_chain)
    places_raw["region_id"] = chains.map(lambda c: c[0][0])

    region_seen: dict[str, str] = {}
    part_of_edges: set[tuple[str, str]] = set()
    for chain in chains:
        for rid, rname in chain:
            region_seen[rid] = rname
        for (child_id, _), (parent_id, _) in zip(chain, chain[1:], strict=False):
            part_of_edges.add((child_id, parent_id))

    region_nodes = pd.DataFrame(
        [{"id:ID": rid, "name": rname, ":LABEL": "Region"} for rid, rname in region_seen.items()]
    )
    rel_part_of = pd.DataFrame(
        [{":START_ID": c, ":END_ID": p, ":TYPE": "PART_OF"} for c, p in sorted(part_of_edges)]
    )
    rel_is_located_in = pd.DataFrame({
        ":START_ID": places_raw["place_id"],
        ":END_ID": places_raw["region_id"],
        ":TYPE": "IS_LOCATED_IN",
    })

    print("[4/5] NEAR_BY 계산 (반경 300m + Top-20)")
    near_by_input = pd.DataFrame({
        "id": places_raw["place_id"], "lat": places_raw["위도"], "lng": places_raw["경도"],
    })
    rel_near_by = build_near_by(near_by_input)

    print("[5/5] CSV 출력")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    place_nodes.to_csv(OUT_DIR / "place_nodes.csv", index=False)
    region_nodes.to_csv(OUT_DIR / "region_nodes.csv", index=False)
    category_nodes.to_csv(OUT_DIR / "category_nodes.csv", index=False)
    rel_is_located_in.to_csv(OUT_DIR / "rel_is_located_in.csv", index=False)
    rel_part_of.to_csv(OUT_DIR / "rel_part_of.csv", index=False)
    rel_has_category.to_csv(OUT_DIR / "rel_has_category.csv", index=False)
    rel_near_by.to_csv(OUT_DIR / "rel_near_by.csv", index=False)

    print(f"""
=== 완료 ===
Place    : {len(place_nodes):,}
Region   : {len(region_nodes):,}
Category : {len(category_nodes):,}
IS_LOCATED_IN : {len(rel_is_located_in):,}
PART_OF       : {len(rel_part_of):,}
HAS_CATEGORY  : {len(rel_has_category):,}
NEAR_BY       : {len(rel_near_by):,}
출력 위치: {OUT_DIR}

건너뜀 (원본 xlsx에 데이터 없음): Theme/HAS_THEME, Audience/SUITABLE_FOR,
Place.business_hours/off_days 값, Itinerary/Visit — data_construct.md 5절 참고.
""")


if __name__ == "__main__":
    sys.exit(main())
