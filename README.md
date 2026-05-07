<!-- updated: 2026-05-07 | hash: db0b7d15 | summary: VRPTWEngine 파이프라인 통합 반영 — step 3b, Efficiency Gap 패널티, optimal_route API 공개 -->

# 관광 일정 QA 엔진 — Explainable Travel Plan Validator

> 여행을 **추천**하지 않는다. 그 일정이 실패할지, 성공할지를 **데이터로 증명**한다.

---

## 문제 정의

AI 기반 여행 일정 추천 서비스가 국내에서 빠르게 확산되고 있지만, 생성된 일정이 실제로 실행 가능한지 검증하는 도구는 사실상 없다.

**한국관광공사 공식 추천 경로(구석구석 101일) + 상업 앱(트리플 89일) 직접 분석 결과:**

| 지표 | 구석구석 (n=101일) | 트리플 (n=89일) |
|------|-------------------|----------------|
| 이동 비율 평균 | **0.157** | 0.143 |
| 경고(≥20%) 비율 | **16.8%** | 9.0% |
| 위험(≥40%) 비율 | **11.9%** | 3.4% |
| 최악 사례 Travel Ratio | 0.86 | 0.607 |
| 백트래킹 발생률 | **44.6%** | 32.3% |
| 12h 초과 과밀 일정 | **8.9%** | 6.5% |
| 평균 지리 분산 | **36.3km** | 21.5km |
| VRPTW 개선 가능 케이스 | **55.4%** | 43.0% |

공식 추천임에도 16.8%가 경고, 11.9%가 위험 수준 — **검증 레이어의 필요성이 실증**된다.

---

## 서비스 소개

**관광 일정 QA 엔진** — 다른 여행자나 AI가 추천·생성한 여행 일정의 실행 가능성을 실시간으로 검증하고, 설명 가능한 피드백을 제공하는 서비스

---

## 3-Layer 검증 구조

품질 검증은 3개 Layer로 구성해 단계별 수행한다.

---

### Layer 1 — 일정 검증 (Hard Fail 탐지)

방문 장소의 **운영시간·이동시간·체류시간**을 교차 검증해 물리적으로 실행 불가능한 요소를 탐지한다.

- 이동 시간: Haversine 거리 / 22km/h (시내 신호·지체·주차 포함 유효속도, 자차 기준)
- 체류 시간: `dwell_db` 5단계 폴백 자동 추정 (수동 큐레이션 50개+ 포함)
- 모듈: `src/validation/hard_fail.py` — HardFailDetector

| 위반 유형 | 등급 | 조건 |
|-----------|------|------|
| 운영시간 충돌 | CRITICAL | 도착 시각 > 운영 종료 시각 |
| 이동 불가 | CRITICAL | 직전 체류 + 이동 시간 > 다음 장소 마감 |
| Safety Margin | WARNING | 종료 60분 이내 도착 |

**Soft Warning 6종 (`src/validation/warning.py`, party_type별 임계 적용):**

| 경고 유형 | 탐지 조건 |
|-----------|-----------|
| DENSE_SCHEDULE | 하루 총 시간(이동+체류) > party_type별 피로 한계 |
| INEFFICIENT_ROUTE | 실제 이동거리 > NN 휴리스틱 최적 대비 30% 초과 |
| PHYSICAL_STRAIN | 총 이동거리 > party_type별 체력 한계 km |
| PURPOSE_MISMATCH | 여행 테마 ↔ POI 구성 코사인 유사도 < 0.5 |
| AREA_REVISIT | 동일 카테고리 장소 3회 이상 연속 배치 |
| CUMULATIVE_FATIGUE | 3일 연속 75%+ 강도 또는 전날 85%+ → 다음날 60%+ |

피로 한계: 혼자·친구·연인 = 12h / 가족 = 10h / 아기동반·어르신동반 = 8h

---

### Layer 2 — 종합 Risk Score 산정

**5개 지표 가중합 → 패널티·보너스 적용 → 0~100점 Risk Score:**

| 지표 | 가중치 | 계산 방식 |
|------|--------|-----------|
| efficiency | 0.30 | nn_heuristic_km / actual_km |
| feasibility | 0.25 | hard×0.5 + temporal×0.3 + human×0.2 |
| purpose_fit | 0.20 | 1 − cosine_distance(intent, activity) |
| flow | 0.15 | 1 − (backtrack×0.65 + revisit_area×0.35) |
| area_intensity | 0.10 | 1 − dominant_category_ratio |

```
adjusted = base_score − cluster_penalty − travel_ratio_penalty − theme_penalty + bonus
→ clamp(0, 100)  |  Hard Fail 존재 시 ≤ 59  |  60점 이상 PASS
```

**패널티 항목:**

| 항목 | 모듈 | 패널티 범위 |
|------|------|------------|
| Travel Ratio (이동 비율) | `scoring/travel_ratio.py` | 0 / −5 / −10 / −20 |
| Cluster Dispersion M1~M4 | `scoring/cluster_dispersion.py` | 0 ~ −20 (캡) |
| Theme Alignment (Claude LLM) | `scoring/theme_alignment.py` | 0 / −5 / −10 / −20 |
| VRPTW Efficiency Gap | `validation/vrptw_engine.py` | 0 / −5 / −10 / −15 |
| 웰니스·무장애 가산점 | `scoring/bonus_engine.py` | 최대 +20 |

**Cluster Dispersion M1~M4 상세:**

| 메트릭 | 기준 | 패널티 |
|--------|------|--------|
| M1. sigungu_switches | 같은 날 시군구 전환 ≥3회 / ≥4회 | −5 / −10 |
| M2. max_pairwise_distance | 하루 최대 직선거리 ≥30 / ≥50 / ≥100km | −5 / −10 / −20 |
| M3. area_backtrack_count | 시군구 비연속 재진입 1회 / 2회+ | −5 / −10 |
| M4. geo_cluster_backtrack | DBSCAN(eps=2km) 클러스터 재진입 (M3 중복 제외) | −5 / −10 |

**패널티 유형별 발생 빈도 (70개 일정 분석 기준):**

| 패널티 유형 | 발생 횟수 |
|------------|----------|
| Travel Ratio | 21회 |
| Cluster M3 | 13회 |
| Congestion | 11회 |
| Cluster M4 | 9회 |
| Theme | 7회 |

**70개 일정 Risk Score 등급 분포:**

| 등급 | 기준 | 비율 |
|------|------|------|
| PASS | 60점 이상 | 67.1% (47개) |
| REVIEW | 40~59점 (주로 Hard Fail) | 25.7% (18개) |
| FAIL | 40점 미만 | 7.1% (5개) |

---

### Layer 3 — LLM 판단 (설명 + 교정)

**ExplainEngine** (`src/explain/explain_engine.py`):
규칙 엔진이 산출한 구조화 JSON을 4단계 자연어 보고서로 변환.

```
Fact       → 데이터 기반 수치 사실
Rule       → 적용된 기준 및 threshold
Risk       → 판정 결과 및 패널티 등급
Suggestion → 구체적 개선 제안
```

출력 예시:
> "부산 1박 2일 AI004 일정은 광안리를 가장 붐비는 오후 시간대에 방문하고, 전체 일정의 16%를 이동에 소비하며, 해운대에서 감천까지 동선이 부산 전역으로 퍼지는 세 가지 문제가 겹쳐 총 53점이 감점되어 위험도 점수 47점 REVIEW 판정을 받았습니다."

---

## 수정 전략 — Minimal Interference

사용자가 선택한 장소 목록을 유지하며 제약 조건만 최적화한다. **장소 대체(substitution)는 금지.**

| 순위 | 전략 | 조건 |
|------|------|------|
| 1 | **Re-ordering** | 순열 전수 탐색(n≤7, 최대 5,040회) → Hard Fail 없는 방문 순서 탐색 |
| 2 | **Stay-time Tuning** | dwell_db 최솟값(원래의 50%, 절대 20분)까지 5분 단위 감소 시뮬레이션 |
| 3 | **Outlier Deletion** | 이동 절감 최대 장소 삭제 (최소 삭제 → 최대 효율, 지리적 이상치 수학적 식별) |

3단계 후에도 미해결 시 LLM이 Fact 기반 삭제 제안을 생성한다.

---

## 데이터 활용 구조

### 한국관광공사 OpenAPI (3개 서비스 활용)

| 서비스 | 활용 내용 | 데이터 현황 |
|--------|-----------|------------|
| 국문관광정보 (KorService2) | 전국 POI 좌표·카테고리·운영시간 | `data/pois.csv` 20,168건 |
| 무장애 여행 정보 (KorWithService2) | 아기동반·어르신동반 +5점/장소 가산점 소스 | 1,799건 |
| 웰니스관광 정보 (WellnessTursmService) | 전 party_type 힐링 +3점/장소 가산점 소스 | 175건 |

### 보조 데이터

| 소스 | 활용 |
|------|------|
| Kakao Local API | 이름 → 위경도 지오코딩 (2차 소스) |
| Kakao Mobility API | 실도로 이동시간 (현재 Haversine 22km/h 추정, 고도화 예정) |
| 서울 도시데이터 API | 115개 지역 실시간 인구 혼잡도 (5분 단위) |
| Naver 블로그 검색 | 1,000 POI 메타데이터 (웨이팅·예약·감성) |
| Claude API | ExplainEngine + ThemeAlignmentJudge |

### 좌표 조회 우선순위

```
1차: data/pois.csv  (TourAPI 원본, 20,168건)
2차: data/naver/naver_metadata.json  (보조, 1,000건)
보정: _COORD_CATALOG  (수동 큐레이션 86건, pois.csv 오류 보정)
폴백: 서울 시청 (37.5665, 126.9780) — 신뢰도 Low
```

### 데이터 신뢰도 3단계

| 등급 | 조건 | 처리 |
|------|------|------|
| High | pois.csv 매칭 + TourAPI 운영시간 정상 | 패널티 정상 계산 |
| Medium | naver_metadata 보조 매칭 또는 dwell_db 추정 | 결과에 "(추정)" 표시 |
| Low | 서울 중심 폴백 또는 운영시간 기본값 | 경고 메시지 출력 |

출력 예: `Risk Score: 68/100 | 데이터 신뢰도: 72/100 (운영시간 2건 누락 [Medium], 이동시간 1건 haversine [Low])`

---

## 입력 / 출력 스키마

**필수 입력 (4개):**

| 항목 | 형식 |
|------|------|
| `days` | 일별 장소 목록 (1~8개/일) |
| `party_size` | 1 / 2 / 3 / 4 / 5이상 |
| `party_type` | 혼자 / 친구 / 연인 / 가족 / 아기동반 / 어르신동반 |
| `date` | YYYY-MM-DD (여행 시작일) |

**선택 입력:** `visit_order`, `travel_type` (cultural / nature / shopping / food / adventure)

> 체류시간·이동수단은 시스템 자동 추정. 자차 단일 이동수단 가정 (22km/h 유효속도).

**출력:**
- 종합 Risk Score (0~100) + PASS/FAIL
- 데이터 신뢰도 점수 (0~100)
- 레이어별 하위 점수 (CRITICAL/WARNING 건수 + 패널티 breakdown)
- 4단계 설명 (Fact · Rule · Risk · Suggestion) — 모든 패널티 항목에 적용
- repair_suggestions (Minimal Interference 3단계 교정 결과)
- bonus_breakdown (웰니스·무장애 가산점 세부 항목)

**입력 예시 (2박 3일):**

```json
{
  "days": [
    {"places": [{"name": "경복궁"}, {"name": "인사동"}, {"name": "북촌한옥마을"}]},
    {"places": [{"name": "남산타워"}, {"name": "명동"}, {"name": "광장시장"}]},
    {"places": [{"name": "홍대"}, {"name": "연남동"}]}
  ],
  "party_size": 2,
  "party_type": "연인",
  "travel_type": "cultural",
  "date": "2026-05-10"
}
```

---

## 서비스 포지셔닝

| 구분 | 대상 | 가치 |
|------|------|------|
| **B2G** | 지자체 · 한국관광공사 | 공식 추천 코스 품질 점검 자동화 → 구석구석 16.8% 경고 사례 사전 차단 |
| **B2B** | 여행 앱 · 플랫폼 | AI 생성 일정 배포 전 QA 게이트 → score < 60 시 일정 재생성 트리거 |
| **B2C** | 개인 여행자 | 직접 만든 일정의 실행 가능성 사전 검증 → 근거 기반 개선 제안 즉시 제공 |

**기존 서비스 대비 차별점:**

| 기능 | 네이버 | 카카오 | 구글 | 트리플 | 본 솔루션 |
|------|--------|--------|------|--------|-----------|
| POI 추천·검색 | ● | ● | ● | ● | ○ |
| 지도·길찾기 | ● | ● | ● | ○ | API |
| 운영시간 충돌 검증 | ○ | ○ | ○ | ○ | **●** |
| 이동 vs 관광 비율 | ○ | ○ | ○ | ○ | **●** |
| 테마 정합성 (LLM) | ○ | ○ | ○ | ○ | **●** |
| 일자별 동선 밀집도 | ○ | ○ | ○ | ○ | **●** |
| 근거 기반 설명 | ○ | ○ | ○ | ○ | **●** |

---

## 구현 현황

| # | 요구사항 | 모듈 | 상태 |
|---|---------|------|------|
| ① | 영업시간 준수 (Time Window) | `validation/hard_fail.py` | ✅ |
| ② | 이동 시간 계산 (자차 Haversine × 22km/h) | `utils/geo.py` | ✅ |
| ③ | 체류시간 추정 (dwell_db, 5단계 폴백) | `data/dwell_db.py` | ✅ |
| ④ | 이동 vs 관광 시간 비율 (travel_ratio) | `scoring/travel_ratio.py` | ✅ |
| ⑤ | 경로 밀집도 + 백트래킹 (M1~M4, DBSCAN) | `scoring/cluster_dispersion.py` | ✅ |
| ⑥ | 테마 일치성 (Claude LLM) | `scoring/theme_alignment.py` | ✅ |
| ⑦ | 혼잡도 — 서울 실시간 | `data/seoul_citydata_client.py` | ✅ |
| ⑧ | 혼잡도 — 전국 계절성 | `scoring/congestion_engine.py` | ✅ |
| ⑨ | 웰니스·무장애 가산점 | `scoring/bonus_engine.py` | ✅ |
| ⑩ | FastAPI /validate + /places 엔드포인트 | `api/main.py · router.py` | ✅ |
| ⑪ | 브라우저 검증 UI (장소 DB + 결과 시각화) | `api/static/index.html` | ✅ |
| ⑫ | Minimal Interference RepairEngine (3단계) | `explain/repair.py` | ✅ |
| ⑬ | 누적 피로도 경고 (CUMULATIVE_FATIGUE) | `validation/warning.py` | ✅ |
| ⑭ | ExplainEngine (4단계 자연어 보고서 + 캐시) | `explain/explain_engine.py` | ✅ |
| ⑮ | 데이터 신뢰도 점수 (data_reliability) | `api/schemas.py` | ✅ |
| ⑯ | VRPTWEngine 파이프라인 통합 (OR-Tools 최적 경로 + Efficiency Gap 패널티) | `validation/vrptw_engine.py` · `explain/pipeline.py` | ✅ |

---

## 파이프라인 실행 순서

```
ValidatorPipeline.run() — src/explain/pipeline.py

1  → HardFail 탐지 (per-day)
2  → Warning 탐지 (per-day + PURPOSE_MISMATCH + CUMULATIVE_FATIGUE 후처리)
3  → ScoreCalculator → base_score
3b → VRPTWEngine 실행 (OR-Tools 최적 경로 탐색 + Efficiency Gap 계산)
       efficiency_gap > 20% → −5 / > 40% → −10 / > 60% → −15
       optimal_route (일자별 최적 방문 순서) → API 응답으로 공개
4  → ClusterDispersion 패널티 (M1~M4, vrptw_days 재사용)
5  → TravelRatio 패널티 (vrptw_days 재사용)
6  → ThemeAlignment 패널티 (travel_type 제공 시)
7  → BonusEngine 가산점
8  → 최종 점수 조립 (cluster + travel_ratio + theme + vrptw_efficiency − bonus)
9  → generate_rewards
10 → RepairEngine (Hard Fail 있을 때만)
11 → ExplainEngine → 자연어 보고서
```

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| API 서버 | FastAPI 0.115+ |
| HTTP 클라이언트 | httpx 0.27+ (async) |
| 데이터 모델 | Pydantic 2.9+ / pydantic-settings 2.6+ |
| LLM | Anthropic Claude API (claude-sonnet-4-6) |
| 좌표·운영시간 | 한국관광공사 TourAPI |
| 지오코딩 | Kakao Local API |
| 실시간 혼잡도 | 서울 도시데이터 API |
| 테스트 | pytest 8.3+ |
| 린터 | ruff 0.8+ |

---

## 설계 철학

| 원칙 | 내용 |
|------|------|
| **Constraint-based Repair** | 새로운 장소를 추천하지 않는다. 사용자의 선택을 제약 조건 내에 맞춘다. |
| **LLM 역할 분리** | 수치 계산은 결정론적 규칙 엔진. Claude API는 JSON → 자연어 변환 전담. |
| **기회비용 벤치마킹** | "이 순서를 유지하기 위해 최적 대비 40분이 추가 소요됩니다"라는 데이터 증거 제시. 판단은 사용자에게. |
| **Minimal Interference** | 사용자의 선택에는 데이터로 포착되지 않는 의도(예약, 선호, 추억)가 담겨 있다. |

---

## 향후 발전 방향

1. **경량화** — 1회 호출 200ms 이하, Redis 캐싱 전략 적용으로 여행 앱 임베딩 가능 형태로 최적화
2. **B2B 배포** — AI 생성 일정 자동 QA 게이트 + 검증 점수 배지 표시
3. **대중교통 통합** — 자차 단일 가정에서 지하철·버스 환승 시간 복합 이동 모델 확장
4. **체류시간 자동 보정** — EXIF 위치 메타데이터로 실제 체류 패턴 학습, 장소별 자동 보정
5. **공공 파트너십** — 한국관광공사 '대한민국 구석구석' 연계, 공식 추천 코스 품질 점검 자동화
6. **인바운드 확장** — 외국인 여행자 동선 최적화 + 다국어 설명 보고서 생성

---

## 명령어

```bash
uvicorn src.api.main:app --reload    # 개발 서버 (port 8000)
python -m pytest tests/ -q          # 전체 테스트
python scripts/execute.py {phase}   # 하네스 실행
ruff check src/ tests/              # 린트
```

---

> 공식 추천도 검증이 필요하다. 한국관광공사 구석구석 추천의 16.8%가 이동 과다 경고 수준이다.
