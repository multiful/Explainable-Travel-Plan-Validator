 전체 분석 완료. 이제 결과를 종합해서 기획 문서로 정리합니다.                                                      
                                                                                          
  ---                                                                                                               
  분석 결과 종합                                                                                                    
   
  실행 요약                                                                                                         
                  
  - 파싱: 50개 항목
  - 지오코딩: 429개 장소 중 411개 성공 (95.8%), 18개 실패
  - 경로 계산: Kakao Mobility 314회 호출
  - 유효 Travel Ratio 산출: 78개 day-record (n=78)

  ---
  핵심 발견 1 — Travel Ratio 기준값 전면 수정 필요

  README 가정과 실측값이 완전히 다릅니다.

  ┌──────┬─────────────┬─────────────┬───────────────┬───────────────┐
  │      │ README 가정 │ 실측 (전체) │ 실측 (1박2일) │ 실측 (2박3일) │
  ├──────┼─────────────┼─────────────┼───────────────┼───────────────┤
  │ 평균 │ 0.38        │ 0.142       │ 0.070         │ 0.191         │
  ├──────┼─────────────┼─────────────┼───────────────┼───────────────┤
  │ P75  │ 0.47        │ 0.118       │ 0.086         │ 0.309         │
  ├──────┼─────────────┼─────────────┼───────────────┼───────────────┤
  │ P90  │ —           │ 0.42        │ 0.104         │ 0.565         │
  └──────┴─────────────┴─────────────┴───────────────┴───────────────┘

  이유: 구석구석 공식 추천 코스는 이미 지역 내 최적화된 경로입니다. 이동시간이 원래부터 짧아서 Travel Ratio가 낮게
  나옵니다. README에서 가정한 0.38은 실측 대비 3배 가까이 부풀려진 수치입니다.

  수정된 threshold 제안 (기간별로 분리):

  ┌──────────┬───────────────────────────────┬────────────────┐
  │   기간   │           경고 구간           │     패널티     │
  ├──────────┼───────────────────────────────┼────────────────┤
  │ 당일여행 │ 0.20~0.30 / 0.30~0.40 / 0.40+ │ -5 / -10 / -20 │
  ├──────────┼───────────────────────────────┼────────────────┤
  │ 1박 2일  │ 0.12~0.18 / 0.18~0.25 / 0.25+ │ -5 / -10 / -20 │
  ├──────────┼───────────────────────────────┼────────────────┤
  │ 2박 3일  │ 0.35~0.50 / 0.50~0.60 / 0.60+ │ -5 / -10 / -20 │
  └──────────┴───────────────────────────────┴────────────────┘

  ---
  핵심 발견 2 — Total Duration 분포

  일일 기준 (per-day):

  ┌───────┬──────┬──────┐
  │ 구간  │ 건수 │ 비율 │
  ├───────┼──────┼──────┤
  │ 0~4h  │ 3    │ 3%   │
  ├───────┼──────┼──────┤
  │ 4~6h  │ 55   │ 54%  │
  ├───────┼──────┼──────┤
  │ 6~8h  │ 31   │ 31%  │
  ├───────┼──────┼──────┤
  │ 8~10h │ 5    │ 5%   │
  ├───────┼──────┼──────┤
  │ 10h+  │ 7    │ 7%   │
  └───────┴──────┴──────┘

  대부분의 하루 일정은 4~7시간 내에 완료됩니다. README의 "10~14시간 패널티" 기준은 전체 여행 기간 합산 기준이어야
  하며, 일일 기준으로는:
  - 8~10h/day: -5
  - 10~12h/day: -10
  - 12h+/day: -20

  으로 수정해야 합니다.

  ---
  핵심 발견 3 — Backtracking 광범위 발생

  45개 day-record에서 backtracking 감지 (전체의 30%). 주목할 건:

  - #40 인천: DAY2에서 4회, DAY3에서 2회 — 단일 최다
  - #46 광주: DAY2에서 3회
  - #32 부산: DAY2에서 3회

  ▎ 문제: 현재 backtracking 탐지 알고리즘(5km 격자)이 도심 밀집 지역에서 너무 민감하게 반응합니다. 인천·광주처럼
  ▎ 좁은 도시 내 이동에서 격자 경계를 자주 넘나드는 것을 "재방문"으로 과탐지합니다. 격자를 10km로 확장하거나 행정구
  ▎ 단위로 전환하는 것이 맞습니다.

  ---
  핵심 발견 4 — 지오코딩 품질 문제 (데이터 신뢰도)

  Route 0% 항목 10개 (#21, #42~#50):
  지오코딩은 성공했으나 Kakao Mobility가 경로를 못 잡음. 원인은 두 가지:
  1. #21 경남 거제: 외도·내도가 해외(13,444km) 좌표로 잘못 매핑됨 → 섬 관련 장소는 Nominatim 신뢰도 낮음
  2. #42~#50: 스크립트 후반부 Kakao Mobility 호출이 연속 실패 → API 일일 호출 한도 초과 가능성

  Geocoding 실패 18개 장소 특성:
  - 이름에 괄호·특수문자 포함: 단양장(1, 6일), 개미집 본점, 송도1913
  - 음식점 단독 상호명 (Nominatim 미수록): 참진주면욕&금돼지집, 까루리웰빙손칼국수
  - 파싱 실패로 두 장소가 합쳐진 경우: 개미집 본점, 송도1913 → 이건 파싱 버그

  ---
  핵심 발견 5 — Cluster Dispersion 이상 outlier

  ┌────────────────────┬───────────────┬───────────────────────────────────┐
  │        항목        │ 최대 직선거리 │               원인                │
  ├────────────────────┼───────────────┼───────────────────────────────────┤
  │ #21 경남 거제 DAY1 │ 13,444km      │ Nominatim 해외 오매핑             │
  ├────────────────────┼───────────────┼───────────────────────────────────┤
  │ #24 서울 DAY3      │ 309.4km       │ 서울 내 장소가 타 지역으로 오매핑 │
  ├────────────────────┼───────────────┼───────────────────────────────────┤
  │ #31 제주 DAY1      │ 288.6km       │ 제주 장소 오매핑                  │
  ├────────────────────┼───────────────┼───────────────────────────────────┤
  │ #32 부산 DAY1      │ 259.5km       │ 부산 장소 오매핑                  │
  └────────────────────┴───────────────┴───────────────────────────────────┘

  실제 정상 범위는 P75 = 7km, P90 = 186km이지만 outlier가 평균(170km)을 심하게 끌어올립니다. 정제 후 정상 P90은 약
  10~15km 예상.

  ---
  기획 관점 문제점 요약

  ┌──────────────────────────────────────┬────────┬───────────────────────────────┐
  │                 문제                 │ 심각도 │             조치              │
  ├──────────────────────────────────────┼────────┼───────────────────────────────┤
  │ Travel Ratio threshold 3배 과대 추정 │ 치명적 │ 기간별 실측값으로 전면 재설정 │
  ├──────────────────────────────────────┼────────┼───────────────────────────────┤
  │ 음식점 지오코딩 실패율 높음          │ 높음   │ Kakao Local API 활성화 필요   │
  ├──────────────────────────────────────┼────────┼───────────────────────────────┤
  │ Backtracking 과탐지 (5km 격자)       │ 높음   │ 행정구 단위로 전환            │
  ├──────────────────────────────────────┼────────┼───────────────────────────────┤
  │ #42~#50 경로 미산출 (10개)           │ 중간   │ API 호출 한도 확인·재실행     │
  ├──────────────────────────────────────┼────────┼───────────────────────────────┤
  │ 섬·외딴 장소 오매핑                  │ 중간   │ TourAPI 우선 적용 범위 확대   │
  ├──────────────────────────────────────┼────────┼───────────────────────────────┤
  │ 파싱 버그 (콤마 포함 장소명)         │ 낮음   │ 정규식 수정                   │
  └──────────────────────────────────────┴────────┴───────────────────────────────┘

  ---
  Kakao Local API 활성화 방법 (필요)

  음식점 좌표 정확도를 높이려면 Kakao Local API가 필요합니다. https://developers.kakao.com → 앱 선택 → 플랫폼 →
  지도/로컬 서비스 활성화

  활성화 후 analyze.py 상단의 geocoding 함수를 Kakao Local로 교체하면 음식점 정확도가 크게 올라갑니다.



  ======================================================================
  2026 04 26

  <!-- updated: 2026-05-03 | hash: 75f20015 | summary: TourAPI 벌크 수집 도입에 따른 프로젝트 고도화 기획 — 데이터 레이크화·임계값 재calibration·검증 엔진 강화·웰니스/무장애 가산점 엔진 추가 -->
# 프로젝트 고도화 기획서 (Enhancement Plan)

> 한국관광공사 국문 관광정보 서비스(TourAPI v2 / data.go.kr 15101578) 전국 약 26만 건 POI 메타를 **벌크 수집**해 CSV 데이터셋으로 보유하게 됨에 따라, 기존 *온디맨드 호출 + 단발성 분석* 구조에서 *데이터 레이크 기반 검증 엔진* 으로 전환하는 고도화 계획.

---

## 0. 한 줄 요약

> **"외부 API 의존을 끊고, 측정 가능한 자체 데이터 자산을 갖춘 검증 엔진으로 진화한다."**

API 호출 단위로 사고하던 구조를 데이터셋 단위로 바꾸면, ① 임계값을 통계로 재산출할 수 있고 ② 운영시간·카테고리 결측이 사라져 Hard Fail/PurposeFit 검증 정확도가 올라가며 ③ 합성 일정(synthetic schedule) 대량 생성으로 모델 평가가 가능해진다.

---

## 1. 현재 구조의 한계 진단

| 영역 | 현재 한계 | 근거 |
|---|---|---|
| **임계값 신뢰성** | Travel Ratio 임계값이 101+89일 표본 기반 → 통계적으로 빈약 | `plan.md` "README 가정 0.38 vs 실측 0.142, 3배 과대" |
| **운영시간 결측** | TourAPI 단발 호출이라 운영시간 데이터 누락 빈번 → Hard Fail 검출 불가 | `phase4-validation/step0.md`의 폴백 로직 — 운영시간 누락 시 검증 스킵 |
| **카테고리 결측** | POI별 cat1/cat2/cat3 분류가 없어서 PurposeFit(코사인) 계산 불가 | `phase4-validation/step1.md`의 INTENT_VECTORS — 코드 매칭 대상 없음 |
| **API 쿼터 의존** | Kakao Mobility 일일 쿼터 소진 시 분석 일부 누락 (10건/50건) | `analyze.py`의 `_quota_exhausted` 플래그 |
| **합성 평가 부재** | "비효율 일정"을 인공 생성해 탐지율을 측정할 수단이 없음 | `phase4-validation/step0.md`의 Synthetic test 자리만 있음 |
| **지오코딩 폴백 다단계** | TourAPI → Kakao Local → Nominatim 3단계 호출이 매번 발생 | `analyze.py:geocode_single` |

---

## 2. TourAPI 벌크 데이터가 해결하는 것 (매핑)

| 기존 한계 | 벌크 CSV 보유 후 해결 방식 |
|---|---|
| 운영시간 결측 | `detailIntro2`로 contentTypeId별 운영시간(usetime, opentime, restdate) 사전 수집 → 검증 시 룩업만 |
| 카테고리 결측 | `areaBasedList2`의 cat1/cat2/cat3 필드 + `categoryCode2`의 분류체계로 INTENT_VECTORS 정합 |
| 지오코딩 다단계 호출 | 26만 POI의 (mapx, mapy)가 미리 확보됨 → TourAPI 호출 없이 정확 일치/유사도 매칭 |
| 임계값 통계적 빈약 | 26만 POI를 조합해 합성 일정 수천 개 생성 → 분포 기반 임계값 재산출 |
| 합성 평가 부재 | 동일 데이터셋에서 "비효율 일정"을 의도적으로 만들어 탐지율 측정 가능 |

---

## 3. 새 phase 구조 제안 (`phase -1: data-lake` 추가)

기존 phase 0~6을 유지하되, **선행 phase `-1`** 을 추가한다. 이게 모든 phase의 입력 자산이 된다.

```
phase -1: data-lake          ← 신규
  ├─ step 0: bulk_collect    ← 본 작업 (CSV 변환)
  ├─ step 1: schema_normalize  cat1·cat2·cat3 + 좌표 정합성 + 운영시간 파싱
  ├─ step 2: enrich_operating  detailIntro2 호출로 운영시간 보강
  └─ step 3: build_indexes     이름→contentid, 좌표→격자 룩업 인덱스 생성

phase 0: setup               ← 기존 (영향 없음)
phase 1: data                ← TourAPIClient를 "API → CSV 룩업"으로 변경
phase 2: matrix              ← 변경 없음 (Kakao Mobility는 그대로 필요)
phase 3: graph               ← Area 노드를 cat1/cat2/cat3 hierarchy로 확장
phase 4: validation
  ├─ step 0: hard-fail       ← 운영시간 룩업 강화
  ├─ step 1: warning         ← INTENT_VECTORS calibration
  ├─ step 2: scoring         ← 임계값 재산출
  └─ step 3: synthetic_eval  ← 신규: 합성 일정 생성 + 탐지율 측정
phase 5: explain             ← 카테고리 명·운영시간 더 풍부한 fact 인용 가능
phase 6: api                 ← 변경 없음
```

---

## 4. 데이터 자산 구조 설계

CSV는 **3개 분리된 정규화 테이블**로 저장한다 (조인 키: `contentid`).

### 4-1. `pois.csv` — 핵심 POI 마스터 (예상 26만 row)

| 컬럼 | 의미 | 출처 |
|---|---|---|
| contentid | TourAPI 고유 ID (조인 키) | areaBasedList2 |
| contenttypeid | 12=관광지, 14=문화시설, 15=축제, 25=여행코스, 28=레포츠, 32=숙박, 38=쇼핑, 39=음식점 | areaBasedList2 |
| title | 장소명 (정규화 키) | areaBasedList2 |
| addr1, addr2 | 주소 | areaBasedList2 |
| mapx, mapy | 경도·위도 (좌표) | areaBasedList2 |
| areacode, sigungucode | 광역·기초 지자체 코드 | areaBasedList2 |
| cat1, cat2, cat3 | 분류체계 3단계 (PurposeFit 계산용) | areaBasedList2 |
| firstimage, firstimage2 | 대표 이미지 URL | areaBasedList2 |
| createdtime, modifiedtime | 등록·수정 시각 (캐시 무효화 기준) | areaBasedList2 |

### 4-2. `operating_hours.csv` — 운영시간·휴무일 (예상 5~10만 row, 옵션)

| 컬럼 | 의미 |
|---|---|
| contentid | 조인 키 |
| usetime / opentime | 운영시간 원문 (예: "09:00~18:00") |
| restdate | 휴무일 원문 (예: "월요일") |
| open_start, open_end | 파싱된 분 단위 정수 (Hard Fail 검증용) |
| parse_confidence | "high"/"mid"/"low" — 정형/비정형 구분 |

> 별도 테이블 분리 이유: detailIntro2는 호출 비용이 크고, contentTypeId마다 응답 스키마가 달라 별도 enrich 단계 필요.

### 4-3. `category_codes.csv` — 분류체계 메타 (수십~수백 row)

| 컬럼 | 의미 |
|---|---|
| code | cat1/cat2/cat3 코드 |
| name | 한글 명칭 ("문화시설", "박물관" 등) |
| level | 1/2/3 |
| parent_code | 상위 분류 |

→ INTENT_VECTORS의 카테고리 매핑을 사람이 읽을 수 있는 형태로 생성 가능.

---

## 5. 기존 phase 영향 분석

### 5-1. `phase 1-data` — TourAPIClient 재설계

**현재**: 매 호출마다 `searchKeyword2` HTTP 요청 → 평균 200~500ms 지연.
**변경**: `pois.csv`를 메모리 인덱스(이름 → row)로 로드 → **O(1) 룩업, ~10μs**.

```python
class TourAPIClient:
    def __init__(self, csv_path: str):
        self._df = pd.read_csv(csv_path)
        self._name_index = {row.title: row for row in self._df.itertuples()}

    async def get_poi(self, name: str) -> POI:
        # 1. 정확 일치 시도
        if name in self._name_index: return self._to_poi(self._name_index[name])
        # 2. 유사도 매칭 (rapidfuzz) — 공공DB의 표기 차이 흡수
        match = process.extractOne(name, self._name_index.keys(), score_cutoff=85)
        if match: return self._to_poi(self._name_index[match[0]])
        # 3. 마지막 수단: live API (Kakao Local 폴백)
        return await self._fallback(name)
```

→ 검증 응답속도 대폭 개선, API 의존 최소화.

### 5-2. `phase 4-validation` — 임계값 재calibration 절차

`phase -1`이 끝나면, **합성 일정 생성기**로 분포를 재추출:

```python
def synthesize_random_itineraries(pois_df, n=10000):
    # 같은 sigungucode 안에서 4~8개 랜덤 추출 → "정상" 일정
    # 다른 sigungucode 섞어서 4~8개 추출 → "비효율" 일정
    ...

# 기존 분석 파이프라인 재사용
results = [analyze_day(itinerary) for itinerary in synthesize_random_itineraries(...)]

# 새 임계값 = 정상군 P75/P90
new_threshold = {
    "travel_ratio_warn": np.percentile(normal_ratios, 75),
    "travel_ratio_crit": np.percentile(normal_ratios, 90),
}
```

표본이 100배(101→10,000+)로 늘어 **통계적 유의성 확보**, 기간(당일/1박/2박)·테마(자연/도시)별 분리 calibration도 가능.

### 5-3. `phase 4-validation/step3` — 합성 평가 (신규 step)

| 합성 시나리오 | 기대 검증 결과 |
|---|---|
| 같은 sigungu 내 4개 POI | 모든 점수 양호 |
| 서울 ↔ 부산 같은 날 섞기 | Cluster Dispersion -10, max_dist > 300km |
| 운영시간 09~18 POI를 19시 도착으로 배치 | OPERATING_HOURS_CONFLICT Hard Fail |
| 동일 cat3(예: 박물관) 5연속 | AREA_REVISIT Warning |
| 도보 이동 가정으로 30km 일정 | PHYSICAL_STRAIN Warning |

→ **탐지율(precision/recall) 측정** 이 가능해진다. 현재는 "이론상 잘 잡을 것" 수준에서 멈춰 있음.

### 5-4. `phase 5-explain` — 인용 가능한 fact 풍부화

LLM 프롬프트에 cat1/cat2/cat3 한글 명을 함께 전달:

```
Fact: "남산서울타워(문화시설>전망대)" 18:30 도착, 운영 09:00~22:30 (잔여 240분)
Rule: 종료 60분 이내 도착 시 -5
Risk: 운영 안전성 양호 (잔여 240분으로 충분)
Suggestion: -
```

→ "왜 이 카테고리에서 이런 점수가 나왔는지" 가 더 명확해진다.

---

## 6. 신규 가능 capability

데이터 자산 보유로 가능해지는 신규 기능 후보 (MVP 외 확장):

| 기능 | 활용 데이터 | 사용자 시나리오 |
|---|---|---|
| **POI 검색·자동완성** | pois.csv title/addr 인덱스 | 사용자가 일정 입력 시 오타 보정 |
| **계절/요일 위험 가점** | operating_hours.csv restdate | "월요일 휴무 박물관" 자동 탐지 |
| **축제/이벤트 충돌 검사** | searchFestival2 → events.csv | 입력 날짜에 해당 지역 축제 동시 추천 |
| **반려동물 동반 가능 필터** | detailPetTour2 → pet_friendly.csv | "petOK"만 필터링한 검증 |
| **카테고리 분포 시각화** | cat1/cat2/cat3 + 일정 | "이 일정의 80%가 음식점" 같은 인사이트 |
| **지자체별 벤치마크** | sigungucode 그룹화 | "서울 강남구 평균 일정 점수 vs 사용자 점수" |

---

## 7. 데이터 거버넌스 / 운영 정책

### 7-1. 갱신 주기

| 데이터 | 갱신 주기 | 방법 |
|---|---|---|
| pois.csv | 월 1회 | `areaBasedSyncList2`로 modifiedtime > 마지막 동기화 시점만 incremental |
| operating_hours.csv | 분기 1회 | detailIntro2 일괄 재호출 (운영시간 변경 빈도 낮음) |
| category_codes.csv | 변경 시 (드뭄) | categoryCode2 |
| events.csv (축제) | 주 1회 | searchFestival2 (eventStartDate ≤ 오늘+90일) |

### 7-2. 무결성 검증

- 한국 좌표 경계(`KR_LAT=33~38.7, KR_LON=124.5~132`) 위반 row 제거 (이미 `analyze.py`에 동일 로직 존재).
- contentid 중복 제거.
- mapx/mapy NULL 비율 모니터링 — 임계값 초과 시 알림.

### 7-3. 라이선스

TourAPI는 **공공누리 4유형**(출처 표시 + 비상업적). 검증 엔진 자체에는 영향 없으나, **재배포 시 출처 명시 필수**. README에 추가 필요.

---

## 8. 마일스톤

| 주차 | 작업 | 산출물 |
|---|---|---|
| **W1** | TourAPI 벌크 수집 스크립트 작성 + 1차 실행 | pois.csv (전국 26만) |
| W2 | detailIntro2 enrich (운영시간) | operating_hours.csv |
| W3 | TourAPIClient를 CSV 룩업으로 교체 + 통합 테스트 | phase 1-data 갱신 |
| W4 | 합성 일정 생성기 + 임계값 재calibration | new threshold 표 + 통계 보고서 |
| W5 | phase 4 step3 (synthetic_eval) | 탐지율 측정 결과 |
| W6 | LLM 프롬프트 v2 (cat1/cat2/cat3 통합) | phase 5-explain 갱신 |

> 본 문서는 **W1 진입 시점**의 기획서. W3 이후 실측 데이터로 phase 4의 임계값을 재산출하면 본 문서의 "예상 효과"를 정량 검증할 수 있다.

---

## 9. 위험 요소 & 대응

| 위험 | 대응 |
|---|---|
| TourAPI 일일 호출 한도 초과 | 페이지당 numOfRows=100, 일일 약 5만 호출 한도 가정 → 26만 POI는 5일에 분산 수집 (resume 지원) |
| 운영시간 표기 비정형 ("월~금 09~18, 토 10~17") | 정규식 + 신뢰도 등급 부여, 파싱 실패 시 Hard Fail 스킵 (기존 정책 유지) |
| 카테고리 분포 불균형 (음식점 과다 등) | INTENT_VECTORS 가중치를 실제 분포 기반으로 재산출 |
| CSV 파일 크기 (~수백 MB) | parquet 포맷 병행 검토, git LFS 또는 .gitignore 처리 |

---

## 10. 본 기획서 체크리스트 (다음 작업 전 확인)

- [ ] TourAPI 벌크 수집 스크립트 실행 → pois.csv 생성 완료
- [ ] CSV 행 수와 contentid unique 수 일치 확인
- [ ] mapx/mapy NULL 비율 < 1% 확인
- [ ] cat1/cat2/cat3 NULL 비율 < 5% 확인
- [ ] 본 문서의 phase -1 step별 작업 정의 (`phases/-1-data-lake/step{0..3}.md`) 작성
- [ ] phase 4 임계값 재산출 후 README "실증 분석 결과" 섹션 갱신

---

======================================================================
2026 05 03

## 웰니스·무장애 가산점 엔진 구현 완료

### 배경

영유아 동반(아기동반)·고령자 동반(어르신동반) 여행자에 대한 접근성 검증 필요성이 확인됨.
한국관광공사가 별도 API(웰니스, 무장애)를 운영 중이므로, 이를 데이터셋으로 선수집해 런타임에 활용하는 구조를 채택.

### 구현 내용

| 파일 | 역할 |
|---|---|
| `src/data/wellness_api.py` | 웰니스 관광 정보 API (B551011/WellnessTourismService) 비동기 클라이언트 |
| `src/data/barrier_free_api.py` | 무장애 여행 정보 API (B551011/KorWithService2) 비동기 클라이언트. `areaBasedList2` 목록 + `detailWithTour2` 접근성 상세 파싱 |
| `src/scoring/bonus_engine.py` | 두 데이터셋 좌표(Haversine 0.3km 반경) 매칭 → 가산점 계산 |
| `scripts/build_poi_dataset.py` | 두 API를 호출해 data/*.json 사전 빌드 (배포 전 1회 실행) |
| `src/explain/pipeline.py` | ValidatorPipeline Step 7에 BonusEngine 통합 |

### 가산점 정책

| 구분 | 점수 | 적용 대상 |
|---|---|---|
| 웰니스 장소 방문 | +3점/장소 | 모든 party_type |
| 무장애 장소 방문 | +5점/장소 | 아기동반·어르신동반·가족만 |
| 총 가산점 상한 (BONUS_CAP) | +20점 | — |

### 최종 점수 공식

```
adjusted = base_score − (cluster_penalty + travel_ratio_penalty + theme_penalty) + bonus
adjusted = clamp(adjusted, 0, 100)
if hard_fails: adjusted = min(adjusted, 59)
```

`bonus_breakdown`(웰니스/무장애 세부 항목)은 `ValidationResult`에 포함되어 API 응답으로 반환됨.

### 환경변수 추가

`.env`에 아래 키 추가. 미설정 시 `TOUR_API_KEY`로 자동 대체(`Settings.fill_gov_api_keys`).
**주의: 공공데이터포털 발급 키는 URL 디코딩 없이(`==` 형태로) 저장할 것 — `%3D%3D` 형태로 저장 시 httpx가 이중인코딩하여 401 발생.**
```
WELLNESS_API_KEY=<decoded key, == 로 끝나는 형태>
BARRIER_FREE_API_KEY=<decoded key, == 로 끝나는 형태>
```

### API 실측 검증 결과 (2026-05-03)

| API | 엔드포인트 | 결과 | 건수 |
|---|---|---|---|
| 무장애 (`KorWithService2/areaBasedList2`) | ✅ 정상 | 10,010건 수신 |
| 무장애 (`KorWithService2/detailWithTour2`) | ✅ 정상 | 접근성 세부 텍스트 반환 확인 |
| 웰니스 (`WellnessTourismService`) | ❌ 500 | **공공데이터포털 별도 신청 필요** |

#### 웰니스 API 미등록 문제 및 대응

현재 API 키(`TOUR_API_KEY`와 동일)는 `KorWithService2`(무장애) 서비스에만 등록돼 있음.  
`B551011/WellnessTourismService` 서비스는 data.go.kr에서 **별도 활용 신청** 후 인증키가 발급돼야 함.

**단기 대응 방안 (웰니스 API 등록 전까지)**:
- `build_poi_dataset.py` 실행 시 웰니스 수집은 자동 스킵 (graceful fallback: 빈 리스트 반환)
- `BonusEngine.from_dataset()` 는 `wellness_places.json` 없으면 웰니스 가산점 0점으로 동작 — 서비스 중단 없음
- 무장애 가산점(+5점, 아기동반·어르신동반·가족)은 즉시 사용 가능

**웰니스 API 등록 절차**:
1. https://data.go.kr → "웰니스관광정보서비스" 검색
2. 활용신청 → 승인 (자동, 약 10분)
3. 발급된 인증키(디코딩 형태)를 `.env`의 `WELLNESS_API_KEY`에 저장
4. `python scripts/build_poi_dataset.py` 재실행

#### `barrier_free_api.py` 버그 수정 (2026-05-03)

매뉴얼(v4.3) 기반으로 아래 두 가지 버그를 수정함:
1. `_LIST_OP = "getList"` → `"areaBasedList2"` (존재하지 않는 오퍼레이션명 수정)
2. `handicapYn`, `babyCarriageYn`, `elevatorYn`, `guideDogYn` 제거 — `areaBasedList2` 응답에 없는 필드 (접근성 상세는 `detailWithTour2` 전용)

실제 `detailWithTour2` 응답 필드 구조:
- 지체장애: `parking`, `publictransport`, `route`, `wheelchair`, `exit`, `elevator`, `restroom`
- 시각장애: `braileblock`, `helpdog`, `guidehuman`, `audioguide`
- 청각장애: `signguide`, `videoguide`
- 영유아가족: `stroller`, `lactationroom`, `babysparechair`
→ 모두 **텍스트** 반환 (Y/N boolean 아님, 예: "대여가능(수동휠체어 2대)")

### 데이터셋 갱신 주기

- 무장애 데이터: 분기 1회 재수집 권장 (`python scripts/build_poi_dataset.py`)
- 웰니스 데이터: API 등록 후 동일하게 분기 1회
- 결과 파일(`data/wellness_places.json`, `data/barrier_free_places.json`)은 `.gitignore`에 추가 필요 (용량·라이선스 고려)
