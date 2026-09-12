<!-- updated: 2026-09-12 | hash: 6580abc2 | summary: 추천 일정 100개 노가다 수집 가이드 + 매칭률 보정 + 파이프라인 사용법 -->
# 추천 일정 수집 가이드

> 100개 추천 일정을 모아 **매칭 → 시간 계산 → Excel 출력**하는 워크플로우.
> 대상: 트리플 + 마이리얼트립 + 네이버 블로그 상위 3개.

---

## 0. 워크플로우 (한눈에)

```
[수집] 추천 사이트 보면서 양식에 입력
   ↓
[양식] gun/data/recommendations_input.xlsx (수동)
   ↓
[파이프라인] python3 gun/scripts/build_itinerary_excel.py
   ↓
[결과] gun/data/itinerary_results_YYYYMMDD.xlsx
       gun/data/match_failed.csv      ← 매칭 실패 POI 모음
   ↓
[보정] 실패 POI 이름 수정 후 재실행
   ↓
[완료] 100개 일정 × 6개 장소 = 600 row Excel
```

---

## 1. 입력 양식 만들기 (1회만)

```bash
cd /Users/guns/Documents/GitHub/portfolio/travel
python3 gun/scripts/create_input_template.py
```

→ `gun/data/recommendations_input.xlsx` 생성 (3 시트: input/guide/예시일정).

**열어서 input 시트의 예시 6 row 확인** — 이 형식으로 채우면 됩니다.

---

## 2. 컬럼 입력 규칙

| 컬럼 | 예시 | 주의사항 |
|---|---|---|
| `source` | "트리플" | 출처 그대로 (트리플/마이리얼트립/블로그명) |
| `plan_id` | "T001", "MRT042", "BLOG_제주가족" | **같은 일정의 모든 row가 동일해야 함** |
| `시도` | "전라남도" | 드롭다운에서 선택 (양식에 자동) |
| `시군구` | "강남구" | 시도 안의 시군구 |
| `여행기간` | "당일치기", "1박2일", "2박3일" | 드롭다운 |
| `일자` | "2025-05-01" | 다일 일정은 day별로 다른 일자 |
| `day` | 1, 2, 3 | 1박2일이면 day=1과 day=2 row 분리 |
| `방문순서` | 1, 2, 3, 4 | 같은 day 안에서 순서 |
| `여행지명` | "경복궁" | **공식 표기 그대로 — 매칭 정확도 핵심** |
| `카테고리힌트` | "관광지", "카페", "식당" | 선택 (자동 매칭 보조) |

---

## 3. 일정 1개 = 5~6 row 입력 예시

**서울 종로구 당일치기 (T001):**

| plan_id | day | 방문순서 | 여행지명 | 카테고리힌트 |
|---|---|---|---|---|
| T001 | 1 | 1 | 경복궁 | 관광지 |
| T001 | 1 | 2 | 광화문 | 관광지 |
| T001 | 1 | 3 | 토속촌삼계탕 | 식당 |
| T001 | 1 | 4 | 북촌한옥마을 | 관광지 |
| T001 | 1 | 5 | 오니오니 | 카페 |
| T001 | 1 | 6 | 광장시장 | 식당 |

**부산 1박2일 (T002):**

| plan_id | day | 방문순서 | 여행지명 |
|---|---|---|---|
| T002 | 1 | 1 | 해운대해수욕장 |
| T002 | 1 | 2 | 누리마루APEC하우스 |
| T002 | 1 | 3 | 마린시티 |
| T002 | 1 | 4 | 광안리해수욕장 |
| T002 | 2 | 1 | 감천문화마을 |
| T002 | 2 | 2 | 자갈치시장 |
| T002 | 2 | 3 | 국제시장 |
| T002 | 2 | 4 | BIFF광장 |

→ 같은 plan_id에서 day=1, day=2로 분리.

---

## 4. 매칭 실패 줄이는 핵심 5가지

### ① 공식 표기 우선

| ❌ 비추천 | ✅ 추천 |
|---|---|
| 경복궁(궁궐) | 경복궁 |
| N서울타워 (남산) | 남산서울타워 또는 N서울타워 |
| 한라산 둘레길 | 한라산 |
| 카페 봄날 (제주) | 카페 봄날 |

### ② 영문 병기 X

| ❌ | ✅ |
|---|---|
| Gyeongbokgung Palace | 경복궁 |
| Haeundae Beach | 해운대해수욕장 |

### ③ 시장은 풀네임

| ❌ | ✅ |
|---|---|
| 광장 | 광장시장 |
| 자갈치 | 자갈치시장 |

### ④ 중복 후보가 많은 카페·식당

여러 지점 있으면 **시군구 정보가 자동 후보 좁힘**. 예: "스타벅스"는 매칭 X — 가능하면 더 specific하게.

### ⑤ TourAPI에 없는 장소 (카페·로컬 식당)

→ `match_failed.csv` 에 기록됨. 그러면:
- (a) 이름 변형 재시도 (띄어쓰기 변경, 공식명 검색)
- (b) 포기하고 일정에서 제외 (장소 4~5개도 OK)
- (c) 향후 Naver 검색 폴백 추가 (TODO)

---

## 5. 일정 모으기 좋은 출처별 팁

### 트리플 (https://triple.guide)

- "추천 코스" 카테고리에 도시별 1~3박 코스 다수
- 무료 회원이면 코스 상세 페이지 열람 가능
- 한 코스 = 한 plan_id로 입력

### 마이리얼트립 (https://www.myrealtrip.com)

- 도시 가이드 → "테마별 코스" 메뉴
- 가이드가 큐레이션한 1일 추천이 많음
- 보통 4~6 장소

### 네이버 블로그

- 검색어: `[지역] 1박2일 추천 코스`, `[지역] 데이트 코스`, `[지역] 가족여행`
- 인기 블로거 (방문수 100+) 상위 3개 글 선택
- 글에서 **순서대로 등장한 장소** 추출

---

## 6. 파이프라인 실행

### 기본 (Kakao API 사용)

```bash
cd /Users/guns/Documents/GitHub/portfolio/travel
python3 gun/scripts/build_itinerary_excel.py
```

→ Kakao Mobility로 실제 이동시간 계산. 첫 실행 시 느림 (캐시 빌드).
→ 두 번째부터는 `kakao_route_cache.json` 활용해 빠름.

### Kakao 한도 절약 (개발/디버그)

```bash
python3 gun/scripts/build_itinerary_excel.py --no-kakao
```

→ Haversine 직선거리 × 우회계수로 폴백. 정확도 떨어지지만 호출 0회.

### 다른 입력 파일

```bash
python3 gun/scripts/build_itinerary_excel.py \
    --input gun/data/recommendations_v2.xlsx \
    --output-dir gun/data/v2
```

---

## 7. 결과 해석

### 메인 출력: `itinerary_results_YYYYMMDD.xlsx`

| 컬럼군 | 의미 |
|---|---|
| 입력 컬럼 (10개) | 그대로 |
| `매칭상태` | exact / partial / partial+sigungu / not_found |
| `체류시간_분`, `체류출처` | dwell_db 룩업 결과 (manual/lcls3/lcls1/content_type/default) |
| `다음장소_이동시간_분` | Kakao 실측 (마지막 장소는 빈 값) |
| `총_체류시간_분`, `총_이동시간_분`, `총_일정시간_분` | 일정(plan_id+day) 단위 합계 |
| `risk_score` | 0~100 (높을수록 좋은 일정) |
| `travel_ratio` | 이동 시간 비율 (0.20 미만 정상) |
| `cluster_penalty` | 공간 응집도 패널티 (0~-20) |
| `vrptw_warnings` | 발생한 검증 경고 |

### 보조 출력: `match_failed.csv`

매칭 실패 POI 목록. 이름 보정 후 input.xlsx에 다시 입력 → 파이프라인 재실행.

### 캐시 출력: `kakao_route_cache.json`

자동 누적. **삭제 X** — 매번 다시 호출하지 않아 속도/한도 절약.

---

## 8. 자주 발생하는 에러

| 증상 | 원인 | 해결 |
|---|---|---|
| `RuntimeError: 인증 오류 401` | Kakao 키 잘못 | `.env`의 `KAKAO_REST_API_KEY` 재확인 |
| 모든 row의 `이동시간_분 = NULL` | 좌표 매칭 실패 | `match_failed.csv` 보고 이름 보정 |
| 같은 plan_id의 row가 정렬 안 됨 | 방문순서 누락/중복 | 1, 2, 3, 4 순서대로 채웠는지 확인 |
| `risk_score = 0` 만 발생 | 매칭 실패율 100% — pois.csv 확인 | `gun/data/pois_processed.csv` 존재 확인 |
| Kakao `통계: {fallback: N}` | API 한도 임박 / 네트워크 | 다음 날 재실행 (캐시는 유지) |

---

## 9. 진척 관리 — 100개 채우기

100 × 6 = **600 row** 입력. 일정당 평균 2~3분이라 가정 시:
- **100개 × 2.5분 = 250분 (약 4시간)**

권장 분할:
- 1일차: 1~25 일정 (서울)
- 2일차: 26~50 (부산·제주)
- 3일차: 51~75 (강원·경상도)
- 4일차: 76~100 (전라·충청)

---

## 10. 체크리스트

- [ ] `recommendations_input.xlsx` 생성 (`create_input_template.py` 1회 실행)
- [ ] input 시트에 일정 100개 채움 (~600 row)
- [ ] `python3 gun/scripts/build_itinerary_excel.py` 실행
- [ ] `match_failed.csv` 확인 → 실패율 < 10%
- [ ] `itinerary_results_YYYYMMDD.xlsx` 결과 검토
- [ ] (있으면) 실패 POI 이름 보정 → 재실행
