<!-- updated: 2026-07-30 | hash: 528a7ecf | summary: NEAR_BY 캡을 반경 300m+Top-20으로 재확정(실측 밀집도 검증) -->

# 제주 Place 지식그래프 스키마 (Head - Relation - Tail)

## 0. 개요

- **데이터 소스**: `제주특별자치도_통합.xlsx` (25,377건 — 여행업/법인등록 등 비대상 제외, 좌표 결측 22건 잔존)
- **설계 원칙**: 노드 하나에 속성을 몰아넣지 않는다. 분류·지역·테마처럼 그 자체로 의미를 갖는 값은 **별도 노드 + 관계**로 뺀다. Place 노드는 장소 고유 속성만 남긴다.
- **범위**: 장소 마스터 데이터(Place~Audience) + 사용자 여행 일정(Itinerary/Visit) 둘 다 포함.

```text
(Place) ──IS_LOCATED_IN──▶ (Region)
(Place) ──HAS_CATEGORY──▶ (Category)
(Place) ──HAS_THEME──▶ (Theme)
(Place) ──SUITABLE_FOR──▶ (Audience)
(Place) ──NEAR_BY──▶ (Place)
(Region) ──PART_OF──▶ (Region)

(Itinerary) ──HAS_VISIT──▶ (Visit)
(Visit) ──VISITS──▶ (Place)
(Visit) ──NEXT──▶ (Visit)
```

---

## 1. 노드 (Entity)

### Place — 장소

| 속성 | 설명 |
|---|---|
| `id` (PK) | Kakao Place ID |
| `name` | 상호명 |
| `place_type` | 타입 — `RESTAURANT`(음식점) \| `ACCOMMODATION`(숙박업소) \| `ACTIVITY`(액티비티). VRPTW 스코어링용 3분류 |
| `category_major_code`, `category_major_name` | **대분류(신)** (TourAPI `lclsSystm1Cd/Nm`, 예: `FD`/음식, `AC`/숙박) |
| `category_medium_code`, `category_medium_name` | **중분류(신)** (TourAPI `lclsSystm2Cd/Nm`, 예: `FD01`/한식, `AC05`/캠핑) |
| `address` | 도로명주소 |
| `lat`, `lng` | 좌표 (WGS84) |
| `business_hours` | 영업시간 |
| `off_days` | 휴무일 |

> 대분류(신)·중분류(신)는 종류가 적고(대분류 7종·중분류 30여 종) 필터링/설명 문구 생성에 자주 쓰여 Place에 직접 둔다. 반면 **소분류(신, 240개 리프)** 는 값 종류가 많고 Place 1건당 1개뿐이라 `HAS_CATEGORY` 관계로 뺐다.

### Region — 지역

| 속성 | 설명 |
|---|---|
| `id` (PK) | 지역 코드 |
| `name` | 예: 제주도, 제주시, 애월읍 |

계층은 `PART_OF` 관계로 표현 (애월읍 → 제주시 → 제주도).

### Category — 분류 (소분류(신) 리프)

| 속성 | 설명 |
|---|---|
| `code` (PK) | 소분류(신)코드, 예: FD010100 |
| `name` | 소분류(신)명, 예: 관광식당 |
| `group` | 관광타입명(구분류체계), 예: 음식점/숙박/관광지/문화시설/레포츠/쇼핑 |

### Theme — 테마 태그

| 속성 | 설명 |
|---|---|
| `name` (PK) | 예: 바다뷰, 로컬맛집, 실내관광 |

### Audience — 추천 대상

| 속성 | 설명 |
|---|---|
| `name` (PK) | 예: 혼밥, 가족여행, 데이트 |

### Itinerary — 여행 일정

| 속성 | 설명 |
|---|---|
| `id` (PK) | 일정 ID |
| `start_date` | 여행 시작일 |
| `end_date` | 여행 종료일 |

### Visit — 방문 일정(일정 내 한 스케줄 항목)

| 속성 | 설명 |
|---|---|
| `id` (PK) | 방문 ID |
| `day_index` | 몇 일차 (1, 2, 3 …) |
| `arrival_time` | 도착 예정 시각 |
| `departure_time` | 출발 예정 시각 |

---

## 2. 관계 (Head → Relation → Tail)

| Relation | Head | Tail | 의미 / 근거 |
|---|---|---|---|
| `IS_LOCATED_IN` | Place | Region | 주소 파싱 |
| `PART_OF` | Region | Region | 행정구역 계층 |
| `HAS_CATEGORY` | Place | Category | 소분류(신) 매핑 |
| `HAS_THEME` | Place | Theme | Kakao 키워드 |
| `SUITABLE_FOR` | Place | Audience | Kakao 키워드 |
| `NEAR_BY` | Place | Place | **반경 300m 이내 + 거리순 Top-20** (둘 다 만족). 관계 속성 `distance_m`, `walk_min` |
| `HAS_VISIT` | Itinerary | Visit | 일정에 포함된 방문 항목 |
| `VISITS` | Visit | Place | 그 방문이 실제 찾아가는 장소 |
| `NEXT` | Visit | Visit | 방문 순서(다음 일정). 관계 속성 `travel_min` — 이 일정에서만 유효한 구간별 이동시간 |

> 장소 간 전체 이동시간은 그래프에 저장하지 않는다(`src/matrix/`, `kakao_matrix.py`에서 Kakao Mobility로 조회). `NEXT.travel_min`은 특정 Itinerary의 연속된 두 Visit 사이 값만 담는 것이라 전체 행렬과는 다르다.
>
> **NEAR_BY 캡 확정: 반경 300m + Top-20** (실측 검증, 좌표 보유 25,355건 기준). 총 엣지 **419,215개**로 이전 검토안(200m+Top-30, 527,610개)보다 오히려 적으면서도, 반경이 넓어진 만큼 고립 노드(반경 내 이웃 0개)는 866개(3.4%) → **434개(1.7%)**로 줄어든다. 캡에 걸리는(20개 초과) 노드는 70.8%(17,949개)로 더 늘지만, 이는 후보가 넉넉하다는 뜻이라 repair 엔진 관점에선 문제 없다. 300m는 도보 약 4분 거리라 "근처"라는 설명 문구로도 무리 없다.

---

## 3. 예시 (Cypher)

```cypher
(:Place {
  id:"kakao_1001", name:"자매국수", place_type:"RESTAURANT",
  category_major_code:"FD", category_major_name:"음식",
  category_medium_code:"FD01", category_medium_name:"한식"
})
  -[:IS_LOCATED_IN]->(:Region {name:"제주시"})
  -[:PART_OF]->(:Region {name:"제주도"})

(:Place {name:"자매국수"})-[:HAS_CATEGORY]->(:Category {code:"FD019900", name:"한식(일반)", group:"음식점"})
(:Place {name:"자매국수"})-[:HAS_THEME]->(:Theme {name:"로컬맛집"})
(:Place {name:"자매국수"})-[:SUITABLE_FOR]->(:Audience {name:"혼밥"})
(:Place {name:"자매국수"})-[:NEAR_BY {distance_m:450, walk_min:6}]->(:Place {name:"용두암"})

(:Itinerary {id:"trip_001", start_date:"2026-08-01", end_date:"2026-08-03"})
  -[:HAS_VISIT]->(v1:Visit {id:"v1", day_index:1, arrival_time:"12:00", departure_time:"13:00"})
  -[:VISITS]->(:Place {name:"자매국수"})

(v1)-[:NEXT {travel_min:8}]->(v2:Visit {id:"v2", day_index:1, arrival_time:"13:10"})
(v2)-[:VISITS]->(:Place {name:"용두암"})
```

---

## 4. Category 그룹 요약

| 대분류(신)코드 | 대분류(신)명 | 건수 | 비율 | place_type |
|---|---|---:|---:|---|
| FD | 음식 | 21,165 | 83.4% | RESTAURANT |
| AC | 숙박 | 2,035 | 8.0% | ACCOMMODATION |
| SH | 쇼핑 | 926 | 3.6% | ACTIVITY |
| VE | 문화관광 | 783 | 3.1% | ACTIVITY (일부 리조트류만 ACCOMMODATION) |
| LS | 레저스포츠 | 289 | 1.1% | ACTIVITY |
| EX | 체험관광 | 156 | 0.6% | ACTIVITY |
| HS | 역사관광 | 23 | 0.1% | ACTIVITY |

세부 소분류(신, 118개) → Category 매핑 전체 내역은 `제주특별자치도_통합.xlsx`의 `대분류코드~소분류명` 컬럼에 이미 반영되어 있음 (원본 참고).

---

## 5. 현재 데이터 상태

- 좌표 결측 22건 잔존 (Kakao 지오코딩으로 262/284건 복구 완료) — 처리 방침 미확정
- 상호명 중복 701종 / 1,461행 — Place 노드 병합 규칙 미확정 (상호명+주소+place_type 동일 시 병합 제안)
- Itinerary/Visit은 스키마 설계만 반영된 상태 — 실제 적재는 미착수
